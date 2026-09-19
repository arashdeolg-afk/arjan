"""Tests for the Polymarket paper-trading harness.

The important ones are the ground-truth tests: on a synthetic market whose
true edge is known by construction, the harness must recover it when it is
there and refuse to invent it when it is not.
"""

from __future__ import annotations

import math
import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pmpaper import feeds                                    # noqa: E402
from pmpaper.book import FillModel, Snapshot, settle         # noqa: E402
from pmpaper.engine import replay                            # noqa: E402
from pmpaper.market import SyntheticMarket, fair_yes         # noqa: E402
from pmpaper.stats import (bootstrap_mean_ci, evaluate,      # noqa: E402
                           inv_norm_cdf, max_drawdown, required_n,
                           risk_of_ruin, wilson_interval)
from pmpaper.strategy import AlwaysBuy, FairValueArb         # noqa: E402


def snap(ts=0.0, spot=100.0, strike=100.0, bid=0.49, ask=0.51,
         w0=0.0, w1=300.0, bsz=1e9, asz=1e9):
    return Snapshot(ts=ts, window_start=w0, window_end=w1, strike=strike,
                    spot=spot, yes_bid=bid, yes_ask=ask,
                    yes_bid_size=bsz, yes_ask_size=asz)


class TestFillModel(unittest.TestCase):
    def test_buy_crosses_to_the_ask(self):
        f = FillModel(latency_ms=0).execute("buy", 1, snap(), snap())
        self.assertEqual(f.price, 0.51)

    def test_sell_crosses_to_the_bid(self):
        f = FillModel(latency_ms=0).execute("sell", 1, snap(), snap())
        self.assertEqual(f.price, 0.49)

    def test_latency_moves_the_fill_against_you(self):
        seen = snap(ts=0.0)
        arrive = snap(ts=0.15, bid=0.52, ask=0.54)
        f = FillModel(latency_ms=150).execute("buy", 1, seen, arrive)
        self.assertAlmostEqual(f.price, 0.54)
        self.assertAlmostEqual(f.intended_price, 0.51)
        self.assertAlmostEqual(f.slippage, 0.03)

    def test_slippage_is_signed_so_positive_is_always_worse(self):
        # Selling into a HIGHER bid is favourable -> negative slippage.
        f = FillModel(latency_ms=100).execute("sell", 1, snap(), snap(bid=0.55))
        self.assertLess(f.slippage, 0)

    def test_no_fill_when_the_order_lands_after_expiry(self):
        self.assertIsNone(FillModel().execute("buy", 1, snap(), None))

    def test_fill_is_capped_by_available_size(self):
        f = FillModel(max_size=1000).execute("buy", 500, snap(), snap(asz=7))
        self.assertEqual(f.size, 7)

    def test_fee_charged_on_notional(self):
        f = FillModel(latency_ms=0, fee_bps=100).execute("buy", 10, snap(), snap())
        self.assertAlmostEqual(f.fee, 0.51 * 10 * 0.01)

    def test_rejects_unknown_side(self):
        with self.assertRaises(ValueError):
            FillModel().execute("hodl", 1, snap(), snap())

    def test_negative_latency_rejected(self):
        with self.assertRaises(ValueError):
            FillModel(latency_ms=-5)


class TestSettlement(unittest.TestCase):
    def test_long_pays_out_above_strike(self):
        f = FillModel(latency_ms=0).execute("buy", 1, snap(), snap())
        self.assertAlmostEqual(settle(f, 101.0), 1 - 0.51)
        self.assertAlmostEqual(settle(f, 99.0), -0.51)

    def test_short_is_the_mirror(self):
        f = FillModel(latency_ms=0).execute("sell", 1, snap(), snap())
        self.assertAlmostEqual(settle(f, 101.0), 0.49 - 1)
        self.assertAlmostEqual(settle(f, 99.0), 0.49)

    def test_exact_tie_resolves_down(self):
        f = FillModel(latency_ms=0).execute("buy", 1, snap(), snap())
        self.assertAlmostEqual(settle(f, 100.0), -0.51)

    def test_fees_reduce_pnl(self):
        f = FillModel(latency_ms=0, fee_bps=100).execute("buy", 1, snap(), snap())
        self.assertAlmostEqual(settle(f, 101.0), (1 - 0.51) - f.fee)


class TestPricing(unittest.TestCase):
    def test_at_the_money_is_just_under_half(self):
        """Phi(-sigma*sqrt(tau)/2): the drift-free digital sits below 0.5."""
        p = fair_yes(60_000, 60_000, 300, 0.50)
        self.assertLess(p, 0.5)
        self.assertGreater(p, 0.499)

    def test_five_minute_sigma_is_about_15bps(self):
        """The number that makes short-horizon prediction hopeless."""
        sigma = 0.50 * math.sqrt(300 / (365 * 24 * 3600))
        self.assertAlmostEqual(sigma * 10_000, 15.4, places=1)

    def test_deep_in_the_money_approaches_one(self):
        self.assertGreater(fair_yes(70_000, 60_000, 60, 0.50), 0.99)
        self.assertLess(fair_yes(50_000, 60_000, 60, 0.50), 0.01)

    def test_expired_resolves_binary(self):
        self.assertEqual(fair_yes(101, 100, 0, 0.5), 1.0)
        self.assertEqual(fair_yes(99, 100, 0, 0.5), 0.0)


class TestSyntheticMarket(unittest.TestCase):
    def test_fair_maker_quotes_track_truth(self):
        snaps, truth = SyntheticMarket(mm_lag_ms=0, seed=3).generate(600)
        err = [abs(s.mid - t) for s, t in zip(snaps, truth)]
        self.assertLess(sum(err) / len(err), 0.01)   # only tick rounding

    def test_lagged_maker_quotes_drift_from_truth(self):
        _, t0 = SyntheticMarket(mm_lag_ms=0, seed=3).generate(600)
        s0, _ = SyntheticMarket(mm_lag_ms=0, seed=3).generate(600)
        s2, _ = SyntheticMarket(mm_lag_ms=5000, seed=3).generate(600)
        e0 = sum(abs(s.mid - t) for s, t in zip(s0, t0)) / len(t0)
        e2 = sum(abs(s.mid - t) for s, t in zip(s2, t0)) / len(t0)
        self.assertGreater(e2, e0 * 2, "stale quotes must be measurably wrong")

    def test_book_is_never_crossed(self):
        snaps, _ = SyntheticMarket(mm_lag_ms=3000, seed=9).generate(1200)
        self.assertTrue(all(s.yes_ask > s.yes_bid for s in snaps))

    def test_strike_resets_each_window(self):
        snaps, _ = SyntheticMarket(window_s=60, seed=4).generate(300)
        self.assertGreater(len({s.strike for s in snaps}), 1)

    def test_is_deterministic_for_a_seed(self):
        a, _ = SyntheticMarket(seed=11).generate(120)
        b, _ = SyntheticMarket(seed=11).generate(120)
        self.assertEqual([s.spot for s in a], [s.spot for s in b])


class TestStats(unittest.TestCase):
    def test_inverse_normal_matches_known_values(self):
        self.assertAlmostEqual(inv_norm_cdf(0.975), 1.959964, places=5)
        self.assertAlmostEqual(inv_norm_cdf(0.80), 0.841621, places=5)
        self.assertAlmostEqual(inv_norm_cdf(0.5), 0.0, places=9)

    def test_wilson_interval_brackets_the_estimate(self):
        lo, hi = wilson_interval(55, 100)
        self.assertLess(lo, 0.55)
        self.assertGreater(hi, 0.55)
        self.assertAlmostEqual(lo, 0.4524, places=3)

    def test_wilson_stays_inside_zero_one(self):
        lo, hi = wilson_interval(0, 3)
        self.assertGreaterEqual(lo, 0.0)
        self.assertLessEqual(hi, 1.0)

    def test_bootstrap_ci_contains_the_mean(self):
        vals = [1.0, 2.0, 3.0, 4.0, 5.0] * 20
        lo, hi = bootstrap_mean_ci(vals)
        self.assertLess(lo, 3.0)
        self.assertGreater(hi, 3.0)

    def test_required_n_grows_as_edge_shrinks(self):
        rng = random.Random(4)
        big = [rng.gauss(0.10, 0.5) for _ in range(400)]
        small = [rng.gauss(0.01, 0.5) for _ in range(400)]
        self.assertLess(required_n(big), required_n(small))

    def test_max_drawdown(self):
        self.assertAlmostEqual(max_drawdown([1.0, -3.0, 1.0]), 3.0)
        self.assertAlmostEqual(max_drawdown([1.0, 1.0]), 0.0)

    def test_risk_of_ruin_is_certain_when_bankroll_is_tiny(self):
        self.assertGreater(risk_of_ruin([-1.0] * 50, bankroll=2.0), 0.99)

    def test_risk_of_ruin_is_zero_when_never_losing(self):
        self.assertEqual(risk_of_ruin([1.0] * 50, bankroll=100.0), 0.0)

    def test_coin_flip_shows_no_edge(self):
        rng = random.Random(7)
        pnls = [0.5 if rng.random() < 0.5 else -0.5 for _ in range(400)]
        v = evaluate(pnls, [0.5] * 400, [p > 0 for p in pnls], notional=200)
        self.assertFalse(v.significant)
        self.assertEqual(v.verdict, "NO EDGE DETECTED")

    def test_large_real_edge_is_detected(self):
        rng = random.Random(8)
        pnls = [0.5 if rng.random() < 0.75 else -0.5 for _ in range(400)]
        v = evaluate(pnls, [0.5] * 400, [p > 0 for p in pnls], notional=200)
        self.assertTrue(v.significant)
        self.assertEqual(v.verdict, "EDGE DETECTED")

    def test_consistent_loser_is_called_negative(self):
        rng = random.Random(9)
        pnls = [0.5 if rng.random() < 0.25 else -0.5 for _ in range(400)]
        v = evaluate(pnls, [0.5] * 400, [p > 0 for p in pnls], notional=200)
        self.assertEqual(v.verdict, "NEGATIVE EDGE")

    def test_multiple_testing_raises_the_bar(self):
        rng = random.Random(10)
        pnls = [0.5 if rng.random() < 0.575 else -0.5 for _ in range(400)]
        wins = [p > 0 for p in pnls]
        one = evaluate(pnls, [0.5] * 400, wins, notional=200, strategies_tested=1)
        many = evaluate(pnls, [0.5] * 400, wins, notional=200, strategies_tested=50)
        self.assertGreaterEqual(one.pnl_ci[0], many.pnl_ci[0],
                                "correcting for many tests must widen the interval")

    def test_no_trades_is_reported_not_crashed(self):
        v = evaluate([], [], [], notional=0)
        self.assertEqual(v.verdict, "NO TRADES")
        self.assertEqual(v.n, 0)


class TestEngineGroundTruth(unittest.TestCase):
    """The tests that matter: known truth in, correct answer out."""

    def _run(self, strat_factory, mm_lag, latency, seeds=3, windows=120,
             window_s=120.0):
        P, E, W, N = [], [], [], 0.0
        for s in range(1, seeds + 1):
            snaps, _ = SyntheticMarket(vol=0.5, spread=0.02, mm_lag_ms=mm_lag,
                                       window_s=window_s, tick_ms=100.0,
                                       seed=s).generate(window_s * windows)
            r = replay(snaps, strat_factory(), FillModel(latency_ms=latency))
            P += r.pnls; E += r.entry_prices; W += r.wins; N += r.notional
        return evaluate(P, E, W, notional=N) if P else None

    def test_control_loses_the_half_spread(self):
        """If this drifts, every other result in the harness is worthless."""
        v = self._run(AlwaysBuy, mm_lag=0, latency=0)
        theory = fair_yes(1.0, 1.0, 120.0, 0.5) - 0.51
        se = 0.5 / v.n ** 0.5
        self.assertLess(abs(v.mean_pnl - theory), 3 * se,
                        f"mean {v.mean_pnl:.4f} vs theory {theory:.4f}")

    def test_no_edge_invented_on_a_fair_market(self):
        v = self._run(lambda: FairValueArb(vol=0.5), mm_lag=0, latency=150)
        if v is not None:
            self.assertFalse(v.significant,
                             "a perfectly priced market must yield no edge")

    def test_real_edge_is_recovered(self):
        v = self._run(lambda: FairValueArb(vol=0.5), mm_lag=10_000, latency=100)
        self.assertIsNotNone(v)
        self.assertTrue(v.significant)
        self.assertGreater(v.roi, 0)

    def test_edge_disappears_when_you_are_slower_than_the_maker(self):
        fast = self._run(lambda: FairValueArb(vol=0.5), mm_lag=10_000, latency=100)
        slow = self._run(lambda: FairValueArb(vol=0.5), mm_lag=10_000, latency=15_000)
        self.assertGreater(fast.roi, slow.roi)
        self.assertLess(slow.roi, 0, "being the slow side must cost money")

    def test_one_trade_per_window(self):
        snaps, _ = SyntheticMarket(window_s=60, seed=2).generate(600)
        r = replay(snaps, AlwaysBuy(), FillModel(latency_ms=0))
        self.assertEqual(len(r.fills), len({f.window_end for f in r.fills}))

    def test_empty_input_is_safe(self):
        r = replay([], AlwaysBuy(), FillModel())
        self.assertEqual(r.fills, [])


class TestFeedParsers(unittest.TestCase):
    def test_best_bid_and_ask_from_polymarket_ordering(self):
        """Bids come back ascending and asks descending; [0] is the trap."""
        book = {"bids": [{"price": "0.40", "size": "10"},
                         {"price": "0.48", "size": "55"}],
                "asks": [{"price": "0.60", "size": "8"},
                         {"price": "0.52", "size": "33"}]}
        self.assertEqual(feeds.parse_book(book), (0.48, 0.52, 55.0, 33.0))

    def test_crossed_book_rejected(self):
        book = {"bids": [{"price": "0.60", "size": "1"}],
                "asks": [{"price": "0.40", "size": "1"}]}
        self.assertIsNone(feeds.parse_book(book))

    def test_empty_or_malformed_book(self):
        self.assertIsNone(feeds.parse_book({"bids": [], "asks": []}))
        self.assertIsNone(feeds.parse_book({}))
        self.assertIsNone(feeds.parse_book("nonsense"))
        self.assertIsNone(feeds.parse_book(
            {"bids": [{"price": "x"}], "asks": [{"price": "y"}]}))

    def test_spot_from_both_venues(self):
        self.assertAlmostEqual(
            feeds.parse_spot({"bidPrice": "59999.5", "askPrice": "60000.5"}), 60000.0)
        self.assertAlmostEqual(feeds.parse_spot({"bid": "100", "ask": "102"}), 101.0)
        self.assertAlmostEqual(feeds.parse_spot({"price": "42.5"}), 42.5)
        self.assertIsNone(feeds.parse_spot({"nope": 1}))

    def test_markets_filtered_and_token_ids_decoded(self):
        payload = [
            {"question": "Bitcoin Up or Down", "slug": "btc-5m",
             "clobTokenIds": '["aaa","bbb"]'},
            {"question": "Election 2028", "clobTokenIds": '["zzz"]'},
            {"question": "Bitcoin no tokens"},
        ]
        got = feeds.parse_markets(payload, "bitcoin")
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["yes_token"], "aaa")
        self.assertEqual(got[0]["no_token"], "bbb")


class TestPersistence(unittest.TestCase):
    def test_snapshots_round_trip(self):
        from pmpaper.db import connect, load_snapshots, new_run, save_snapshots
        conn = connect(":memory:")
        rid = new_run(conn, "test", {"a": 1})
        snaps, _ = SyntheticMarket(seed=1).generate(30)
        save_snapshots(conn, rid, snaps)
        back = load_snapshots(conn, rid)
        self.assertEqual(len(back), len(snaps))
        self.assertAlmostEqual(back[0].spot, snaps[0].spot)
        self.assertAlmostEqual(back[-1].yes_ask, snaps[-1].yes_ask)


if __name__ == "__main__":
    unittest.main()
