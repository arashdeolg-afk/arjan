"""Deol Tech test suite.

Run with:  python3 -m unittest discover -s tests -v

Two rules this suite holds itself to:

**No network.** Every market-data test runs against the deterministic synthetic
feed or against recorded Finviz fixtures. A suite that fails when a vendor is
down is not testing your code.

**No real database.** `setUpModule` points `DEOLTECH_DB` at a temporary file, so
a test run can never touch `data/deoltech.db`.

The matching-engine tests are the important ones. They pin down the behaviours
that make simulated results trustworthy — stops that gap through, signals that
cannot see the future, limits that fill at the limit — and each is written so
that the *optimistic* implementation fails it.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

_TMPDIR: str = ""


def setUpModule() -> None:
    """Point every test at a throwaway database before anything imports it."""
    global _TMPDIR
    _TMPDIR = tempfile.mkdtemp(prefix="deoltech-tests-")
    os.environ["DEOLTECH_DB"] = os.path.join(_TMPDIR, "test.db")


def tearDownModule() -> None:
    shutil.rmtree(_TMPDIR, ignore_errors=True)


import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from deoltech import analytics, instruments  # noqa: E402
from deoltech.backtest import Backtester  # noqa: E402
from deoltech.clock import (  # noqa: E402
    Session, equity_session, fx_session, market_status, session_close,
    swap_multiplier,
)
from deoltech.engine.book import build_book, spread_bps_for  # noqa: E402
from deoltech.engine.broker import PaperBroker  # noqa: E402
from deoltech.engine.fees import (  # noqa: E402
    FeeSchedule, borrow_charge, compute_fees, round_trip_cost_bps, swap_charge,
)
from deoltech.engine.matching import MatchContext, Matcher  # noqa: E402
from deoltech.engine.risk import RiskEngine, RiskLimits, RiskState  # noqa: E402
from deoltech.engine.slippage import SlippageModel, walk_the_book  # noqa: E402
from deoltech.feeds.base import ParseError, RateLimiter, CircuitBreaker, parse_number  # noqa: E402
from deoltech.feeds.finviz import (  # noqa: E402
    parse_all_pairs, parse_export_csv, parse_quote_page, parse_screener_page,
    parse_series,
)
from deoltech.feeds.synthetic import SyntheticFeed  # noqa: E402
from deoltech.instruments import AssetClass, classify, resolve  # noqa: E402
from deoltech.portfolio import Portfolio, round_money  # noqa: E402
from deoltech.strategies import indicators  # noqa: E402
from deoltech.types import (  # noqa: E402
    Bar, Fill, Liquidity, Order, OrderStatus, OrderType, Quote, Side,
    TimeInForce, round_to_lot, round_to_tick,
)

UTC = timezone.utc
# A Monday, 11:00 New York time: unambiguously inside a regular session.
OPEN_TS = datetime(2026, 8, 24, 15, 0, tzinfo=UTC)


def make_quote(symbol: str = "AAPL", last: float = 200.0, ts=None, **kw) -> Quote:
    return Quote(symbol=symbol, ts=ts or OPEN_TS, last=last,
                 open=kw.pop("open", last), high=kw.pop("high", last * 1.01),
                 low=kw.pop("low", last * 0.99), volume=kw.pop("volume", 5e7),
                 prev_close=kw.pop("prev_close", last), **kw)


# ============================================================ value objects


class TestTypes(unittest.TestCase):
    def test_tick_rounding_never_favours_the_trader(self):
        # A buy limit rounds DOWN and a sell limit rounds UP, so snapping to the
        # tick grid can never make an order more aggressive than requested.
        self.assertEqual(round_to_tick(10.017, 0.01, Side.BUY), 10.01)
        self.assertEqual(round_to_tick(10.013, 0.01, Side.SELL), 10.02)
        self.assertEqual(round_to_tick(10.015, 0.01), 10.02)

    def test_lot_rounding_never_rounds_size_up(self):
        self.assertEqual(round_to_lot(3.9, 1.0), 3.0)
        self.assertEqual(round_to_lot(1999.0, 1000.0), 1000.0)

    def test_order_validation_rejects_incoherent_orders(self):
        with self.assertRaises(ValueError):
            Order("AAPL", Side.BUY, 0)
        with self.assertRaises(ValueError):
            Order("AAPL", Side.BUY, 1, OrderType.LIMIT)          # no limit price
        with self.assertRaises(ValueError):
            Order("AAPL", Side.BUY, 1, OrderType.STOP)           # no stop price
        with self.assertRaises(ValueError):
            Order("AAPL", Side.BUY, 1, tif=TimeInForce.GTD)      # no expiry

    def test_fill_cash_direction(self):
        buy = Fill("o", "AAPL", Side.BUY, 10, 100.0, OPEN_TS, fee=1.0)
        sell = Fill("o", "AAPL", Side.SELL, 10, 100.0, OPEN_TS, fee=1.0)
        self.assertEqual(buy.cash_delta, -1001.0)     # pay out, plus the fee
        self.assertEqual(sell.cash_delta, 999.0)      # take in, less the fee

    def test_terminal_statuses(self):
        self.assertTrue(OrderStatus.FILLED.is_terminal)
        self.assertTrue(OrderStatus.REJECTED.is_terminal)
        self.assertFalse(OrderStatus.PARTIALLY_FILLED.is_terminal)
        self.assertTrue(OrderStatus.NEW.is_open)


# ================================================================ calendars


class TestClock(unittest.TestCase):
    def test_regular_session(self):
        self.assertIs(equity_session(OPEN_TS), Session.REGULAR)

    def test_premarket_and_afterhours(self):
        self.assertIs(equity_session(datetime(2026, 8, 24, 11, 0, tzinfo=UTC)),
                      Session.PREMARKET)
        self.assertIs(equity_session(datetime(2026, 8, 24, 22, 0, tzinfo=UTC)),
                      Session.AFTERHOURS)

    def test_weekend_and_holiday_are_closed(self):
        self.assertIs(equity_session(datetime(2026, 8, 22, 15, 0, tzinfo=UTC)),
                      Session.CLOSED)                          # Saturday
        self.assertIs(equity_session(datetime(2026, 7, 3, 15, 0, tzinfo=UTC)),
                      Session.CLOSED)                          # Independence Day

    def test_early_close_ends_the_day(self):
        # Christmas Eve closes at 1pm ET; 2pm is shut, not after-hours.
        self.assertIs(equity_session(datetime(2026, 12, 24, 17, 0, tzinfo=UTC)),
                      Session.REGULAR)                         # 12:00 ET
        self.assertIs(equity_session(datetime(2026, 12, 24, 19, 0, tzinfo=UTC)),
                      Session.CLOSED)                          # 14:00 ET

    def test_fx_week(self):
        self.assertIs(fx_session(datetime(2026, 8, 22, 16, 0, tzinfo=UTC)),
                      Session.CLOSED)                          # Saturday
        self.assertIs(fx_session(datetime(2026, 8, 23, 22, 0, tzinfo=UTC)),
                      Session.REGULAR)                         # Sunday 18:00 ET
        self.assertIs(fx_session(datetime(2026, 8, 21, 22, 0, tzinfo=UTC)),
                      Session.CLOSED)                          # Friday 18:00 ET

    def test_crypto_never_closes(self):
        for ts in (datetime(2026, 8, 22, 3, 0, tzinfo=UTC),
                   datetime(2026, 12, 25, 12, 0, tzinfo=UTC)):
            self.assertTrue(market_status("crypto", ts).session.is_tradeable)

    def test_wednesday_swap_is_tripled(self):
        self.assertEqual(swap_multiplier(datetime(2026, 8, 26, 21, 0, tzinfo=UTC)), 3)
        self.assertEqual(swap_multiplier(datetime(2026, 8, 25, 21, 0, tzinfo=UTC)), 1)

    def test_next_open_is_reported_when_closed(self):
        st = market_status("equity", datetime(2026, 8, 22, 15, 0, tzinfo=UTC))
        self.assertIs(st.session, Session.CLOSED)
        self.assertIsNotNone(st.opens_at)
        self.assertGreater(st.opens_at, datetime(2026, 8, 22, 15, 0, tzinfo=UTC))


# ============================================================== instruments


class TestInstruments(unittest.TestCase):
    def test_asset_class_inference(self):
        self.assertIs(classify("AAPL"), AssetClass.EQUITY)
        self.assertIs(classify("BTCUSD"), AssetClass.CRYPTO)
        self.assertIs(classify("EURUSD"), AssetClass.FX)

    def test_usdcad_is_forex_not_a_coin(self):
        # 'USD' is a crypto quote suffix too; FX must be tested first or this
        # resolves to "the USD... coin priced in CAD".
        self.assertIs(classify("USDCAD"), AssetClass.FX)
        self.assertIs(classify("USDJPY"), AssetClass.FX)

    def test_contract_specs_match_venue_conventions(self):
        eur = resolve("EURUSD")
        self.assertEqual(eur.pip_size, 0.0001)
        self.assertEqual(eur.pip_value(100_000), 10.0)      # $10 per pip
        self.assertEqual(eur.max_leverage, 50.0)            # CFTC major cap
        jpy = resolve("USDJPY")
        self.assertEqual(jpy.pip_size, 0.01)                # JPY crosses
        self.assertEqual(resolve("GBPJPY").max_leverage, 20.0)   # minor cap

    def test_fractional_rules(self):
        ok, why = resolve("AAPL").valid_qty(0.5)
        self.assertFalse(ok)
        self.assertTrue(resolve("BTCUSD").valid_qty(0.001)[0])

    def test_unknown_symbols_resolve_with_sane_defaults(self):
        inst = resolve("ZZQQ")
        self.assertIs(inst.asset_class, AssetClass.EQUITY)
        self.assertEqual(inst.tick_size, 0.01)

    def test_symbol_normalization(self):
        self.assertEqual(resolve("btc-usd").symbol, "BTCUSD")
        self.assertEqual(resolve(" aapl ").symbol, "AAPL")

    def test_adv_is_in_units_not_dollars(self):
        # If ADV were dollar-denominated the impact model would divide coins by
        # dollars. Bitcoin trades hundreds of thousands of coins a day, not
        # billions.
        self.assertLess(resolve("BTCUSD").adv, 5_000_000)


# =========================================================== finviz parsers


QUOTE_HTML = """
<table class="snapshot-table2">
<tr><td class="snapshot-td2-cp">P/E</td><td class="snapshot-td2"><b>33.18</b></td>
    <td class="snapshot-td2-cp">Market Cap</td><td class="snapshot-td2"><b>3241.55B</b></td></tr>
<tr><td class="snapshot-td2-cp">Prev Close</td><td class="snapshot-td2"><b>214.29</b></td>
    <td class="snapshot-td2-cp">Price</td><td class="snapshot-td2"><b>217.96</b></td></tr>
<tr><td class="snapshot-td2-cp">Volume</td><td class="snapshot-td2"><b>42,088,412</b></td>
    <td class="snapshot-td2-cp">Change</td><td class="snapshot-td2"><b>1.71%</b></td></tr>
<tr><td class="snapshot-td2-cp">Range</td><td class="snapshot-td2"><b>214.60 - 218.34</b></td>
    <td class="snapshot-td2-cp">Open</td><td class="snapshot-td2"><b>215.10</b></td></tr>
</table>"""

SCREENER_HTML = """
<table class="table-light">
<tr><td>No.</td><td>Ticker</td><td>Company</td><td>Price</td><td>Change</td><td>Volume</td></tr>
<tr><td>1</td><td><a href="quote.ashx?t=AAPL">AAPL</a></td><td>Apple Inc.</td>
    <td>217.96</td><td>1.71%</td><td>42,088,412</td></tr>
<tr><td>2</td><td><a href="quote.ashx?t=MSFT">MSFT</a></td><td>Microsoft</td>
    <td>405.12</td><td>-0.44%</td><td>18,220,100</td></tr>
</table>"""

COLUMN_SERIES = {"date": ["2026-08-20", "2026-08-21"], "open": [100, 102],
                 "high": [103, 105], "low": [99, 101], "close": [102, 104],
                 "volume": [1e6, 1.2e6]}


class TestFinvizParsers(unittest.TestCase):
    """Parsers run against recorded fixtures — never against the live site."""

    def test_quote_page(self):
        quote, fundamentals = parse_quote_page(QUOTE_HTML, "AAPL")
        self.assertEqual(quote.last, 217.96)
        self.assertEqual(quote.prev_close, 214.29)
        self.assertEqual(quote.volume, 42088412)
        self.assertEqual((quote.low, quote.high), (214.60, 218.34))
        self.assertEqual(fundamentals["P/E"], "33.18")

    def test_screener_page(self):
        quotes = parse_screener_page(SCREENER_HTML)
        self.assertEqual(quotes["AAPL"].last, 217.96)
        self.assertAlmostEqual(quotes["MSFT"].change_pct, -0.44, places=6)

    def test_export_csv_change_is_a_fraction(self):
        # The CSV writes change as 0.0171 where the HTML writes "1.71%".
        quotes = parse_export_csv(
            "Ticker,Price,Change,Volume\nAAPL,217.96,0.0171,42088412\n")
        self.assertAlmostEqual(quotes["AAPL"].change_pct, 1.71, places=2)

    def test_every_known_series_shape(self):
        shapes = [
            COLUMN_SERIES,                                  # parallel columns
            {"candles": COLUMN_SERIES},                     # nested
            [{"date": "2026-08-20", "open": 100, "high": 103, "low": 99,
              "close": 102, "volume": 1e6},
             {"date": "2026-08-21", "open": 102, "high": 105, "low": 101,
              "close": 104, "volume": 1.2e6}],              # records
            [[1755648000, 100, 103, 99, 102, 1e6],
             [1755734400, 102, 105, 101, 104, 1.2e6]],      # positional rows
        ]
        for shape in shapes:
            bars = parse_series(shape, "AAPL")
            self.assertEqual(len(bars), 2)
            self.assertEqual(bars[-1].close, 104)

    def test_bulk_pair_shapes(self):
        mapping = parse_all_pairs({"BTCUSD": {"last": 64210.55, "change": 2.31}})
        self.assertAlmostEqual(mapping["BTCUSD"].last, 64210.55)
        listed = parse_all_pairs([{"ticker": "EURUSD", "last": 1.08523,
                                   "change": 0.12}])
        self.assertAlmostEqual(listed["EURUSD"].last, 1.08523)

    def test_unreadable_responses_raise_rather_than_invent_a_price(self):
        # The one thing a market data adapter must never do is guess.
        for bad in ("<html>nothing here</html>",
                    "<table><tr><td>Price</td><td>-</td></tr></table>"):
            with self.assertRaises(ParseError):
                parse_quote_page(bad, "AAPL")
        with self.assertRaises(ParseError):
            parse_series({"unexpected": 1}, "AAPL")
        with self.assertRaises(ParseError):
            parse_all_pairs({})

    def test_number_parsing_handles_vendor_formats(self):
        cases = {"1,234.56": 1234.56, "$1,234.56": 1234.56, "-2.31%": -2.31,
                 "12.4M": 12_400_000, "1.2B": 1.2e9, "(4.2)": -4.2,
                 "-": 0.0, "N/A": 0.0, "3.5K": 3500}
        for text, expected in cases.items():
            self.assertAlmostEqual(parse_number(text), expected, msg=text)


class TestFeedInfrastructure(unittest.TestCase):
    def test_circuit_breaker_opens_then_half_opens(self):
        breaker = CircuitBreaker(threshold=2, cooldown_s=0.05)
        breaker.record_failure()
        self.assertTrue(breaker.allow())
        breaker.record_failure()
        self.assertFalse(breaker.allow())            # open: fail fast
        import time
        time.sleep(0.06)
        self.assertEqual(breaker.state, "half_open")  # probe again
        breaker.record_success()
        self.assertEqual(breaker.state, "closed")

    def test_rate_limiter_bounds_throughput(self):
        limiter = RateLimiter(rate_per_s=1000, burst=2)
        self.assertTrue(limiter.acquire())
        self.assertTrue(limiter.acquire())
        self.assertTrue(limiter.acquire(timeout=1.0))   # refills


class TestSyntheticFeed(unittest.TestCase):
    def setUp(self):
        self.feed = SyntheticFeed()

    def test_prices_are_a_pure_function_of_time(self):
        # Two independent instances must agree, or the simulator cannot be used
        # as a fallback: prices would teleport on restart.
        ts = datetime(2026, 8, 24, 15, 0, tzinfo=UTC)
        self.assertEqual(self.feed.price_at("BTCUSD", ts),
                         SyntheticFeed().price_at("BTCUSD", ts))

    def test_bars_are_internally_consistent(self):
        for bar in self.feed.get_bars("AAPL", "1d", 60):
            self.assertLessEqual(bar.low, min(bar.open, bar.close))
            self.assertGreaterEqual(bar.high, max(bar.open, bar.close))

    def test_equity_dailies_skip_weekends_but_crypto_does_not(self):
        equity = self.feed.get_bars("AAPL", "1d", 40)
        self.assertEqual([b for b in equity if b.ts.weekday() >= 5], [])
        crypto = self.feed.get_bars("BTCUSD", "1d", 40)
        self.assertTrue(any(b.ts.weekday() >= 5 for b in crypto))

    def test_volatility_is_in_a_realistic_range(self):
        import statistics
        closes = [b.close for b in self.feed.get_bars("AAPL", "1d", 200)]
        rets = [closes[i] / closes[i - 1] - 1 for i in range(1, len(closes))]
        annual = statistics.pstdev(rets) * (252 ** 0.5)
        self.assertTrue(0.10 < annual < 0.80, f"implausible vol {annual:.0%}")


# ======================================================================= fees


class TestFees(unittest.TestCase):
    def test_equity_regulatory_fees_are_sell_side_only(self):
        aapl = resolve("AAPL")
        buy = compute_fees(aapl, Side.BUY, 100, 217.96)
        sell = compute_fees(aapl, Side.SELL, 100, 217.96)
        self.assertEqual(buy.regulatory, 0.0)
        self.assertGreater(sell.regulatory, 0.0)

    def test_finra_taf_is_capped(self):
        # $0.000166/share would be $166 on a million shares; the cap is $8.30.
        fees = compute_fees(resolve("AAPL"), Side.SELL, 1_000_000, 1.0)
        self.assertLess(fees.regulatory, 40.0)

    def test_maker_pays_less_than_taker(self):
        btc = resolve("BTCUSD")
        maker = compute_fees(btc, Side.BUY, 0.5, 64000, liquidity=Liquidity.MAKER)
        taker = compute_fees(btc, Side.BUY, 0.5, 64000, liquidity=Liquidity.TAKER)
        self.assertLess(maker.total, taker.total)

    def test_crypto_fee_tiers_reward_volume(self):
        btc = resolve("BTCUSD")
        retail = compute_fees(btc, Side.BUY, 1, 64000, volume_30d=0)
        whale = compute_fees(btc, Side.BUY, 1, 64000, volume_30d=20_000_000)
        self.assertLess(whale.total, retail.total)

    def test_fx_swap_converts_to_the_account_currency(self):
        # A long 100k USD/JPY earns roughly $10/day of carry. Without the
        # conversion it reads as ¥1,572 — a 147x overstatement.
        jpy = resolve("USDJPY")
        usd = swap_charge(jpy, 100_000, 147.22, 1, quote_to_account=1 / 147.22)
        self.assertTrue(-15 < usd.swap < -5, usd.swap)

    def test_wednesday_swap_is_three_days(self):
        eur = resolve("EURUSD")
        one = swap_charge(eur, 100_000, 1.0852, 1).swap
        three = swap_charge(eur, 100_000, 1.0852, 3).swap
        self.assertAlmostEqual(three, one * 3, places=6)

    def test_only_shorts_pay_borrow(self):
        gme = resolve("GME")
        self.assertEqual(borrow_charge(gme, 100, 22.40).borrow, 0.0)
        self.assertGreater(borrow_charge(gme, -100, 22.40).borrow, 0.0)

    def test_round_trip_cost_ranks_correctly(self):
        # Crypto costs far more to round trip than a liquid large cap.
        self.assertGreater(round_trip_cost_bps(resolve("BTCUSD"), 10_000),
                           round_trip_cost_bps(resolve("AAPL"), 10_000))


# ============================================================ microstructure


class TestBookAndSlippage(unittest.TestCase):
    def setUp(self):
        self.inst = resolve("AAPL")
        self.quote = make_quote()
        self.book = build_book(self.inst, self.quote)
        self.model = SlippageModel()

    def test_synthesized_book_straddles_the_last_price(self):
        self.assertTrue(self.book.synthetic)
        self.assertLess(self.book.bid, self.quote.last)
        self.assertGreater(self.book.ask, self.quote.last)
        self.assertGreaterEqual(self.book.ask - self.book.bid,
                                self.inst.tick_size)

    def test_real_book_is_used_when_the_feed_supplies_one(self):
        quote = make_quote(bid=199.98, ask=200.02, bid_size=500, ask_size=500)
        book = build_book(self.inst, quote)
        self.assertFalse(book.synthetic)
        self.assertEqual((book.bid, book.ask), (199.98, 200.02))

    def test_spreads_widen_outside_regular_hours(self):
        regular = spread_bps_for(self.inst, self.quote, Session.REGULAR)
        pre = spread_bps_for(self.inst, self.quote, Session.PREMARKET)
        self.assertGreater(pre, regular)

    def test_slippage_is_always_adverse(self):
        buy = self.model.apply(self.inst, Side.BUY, 10_000, self.book.ask,
                               self.quote, "O1")
        sell = self.model.apply(self.inst, Side.SELL, 10_000, self.book.bid,
                                self.quote, "O1")
        self.assertGreaterEqual(buy.price, self.book.ask)
        self.assertLessEqual(sell.price, self.book.bid)

    def test_impact_grows_with_size(self):
        small = self.model.apply(self.inst, Side.BUY, 100, self.book.ask,
                                 self.quote, "O").total_bps
        large = self.model.apply(self.inst, Side.BUY, 2_000_000, self.book.ask,
                                 self.quote, "O").total_bps
        self.assertGreater(large, small * 5)

    def test_slippage_is_deterministic(self):
        a = self.model.apply(self.inst, Side.BUY, 1000, self.book.ask,
                             self.quote, "ORD-1").price
        b = self.model.apply(self.inst, Side.BUY, 1000, self.book.ask,
                             self.quote, "ORD-1").price
        self.assertEqual(a, b)

    def test_walking_the_book_costs_more_than_the_touch(self):
        vwap, filled = walk_the_book(self.book, self.inst, Side.BUY,
                                     self.book.ask_size * 4)
        self.assertGreater(filled, 0)
        self.assertGreater(vwap, self.book.ask)


# =========================================================== matching engine


class TestMatchingEngine(unittest.TestCase):
    """The behaviours that decide whether a paper result means anything."""

    def setUp(self):
        self.inst = resolve("AAPL")
        # Slippage disabled so these assertions isolate matching logic; the
        # modelled half-spread is still applied, hence the tolerances.
        self.matcher = Matcher(SlippageModel(enabled=False))

    def ctx(self, last: float, ts=None) -> MatchContext:
        return MatchContext.build(self.inst, make_quote(last=last, ts=ts),
                                  ts or OPEN_TS)

    # -------------------------------------------------------- the gap rule

    def test_sell_stop_fills_at_the_gap_not_the_stop_price(self):
        order = Order("AAPL", Side.SELL, 100, OrderType.STOP, stop_price=100.0)
        gap = Bar("AAPL", OPEN_TS, open=92.0, high=93.0, low=90.0, close=91.0,
                  volume=1e6)
        fill = self.matcher.match_bar(order, self.inst, gap).fills[0]
        self.assertAlmostEqual(fill.price, 92.0, delta=0.06)
        self.assertLess(fill.price, 99.0, "a stop must not fill at its trigger "
                                          "when the market gapped past it")

    def test_buy_stop_fills_at_the_gap_up(self):
        order = Order("AAPL", Side.BUY, 100, OrderType.STOP, stop_price=100.0)
        gap = Bar("AAPL", OPEN_TS, open=110.0, high=112.0, low=109.0,
                  close=111.0, volume=1e6)
        fill = self.matcher.match_bar(order, self.inst, gap).fills[0]
        self.assertAlmostEqual(fill.price, 110.0, delta=0.06)

    def test_stop_without_a_gap_fills_at_the_stop(self):
        order = Order("AAPL", Side.SELL, 100, OrderType.STOP, stop_price=100.0)
        bar = Bar("AAPL", OPEN_TS, open=102.0, high=103.0, low=98.0, close=99.0,
                  volume=1e6)
        fill = self.matcher.match_bar(order, self.inst, bar).fills[0]
        self.assertAlmostEqual(fill.price, 100.0, delta=0.06)

    # ---------------------------------------------------------- lookahead

    def test_market_orders_fill_at_the_bar_open_not_the_close(self):
        # Filling at the close of the bar that produced the signal is lookahead.
        order = Order("AAPL", Side.BUY, 100, OrderType.MARKET)
        bar = Bar("AAPL", OPEN_TS, open=100.0, high=115.0, low=99.0,
                  close=114.0, volume=1e6)
        fill = self.matcher.match_bar(order, self.inst, bar).fills[0]
        self.assertAlmostEqual(fill.price, 100.0, delta=0.06)

    def test_limit_fills_at_the_limit_not_the_bar_extreme(self):
        order = Order("AAPL", Side.BUY, 100, OrderType.LIMIT, limit_price=95.0)
        bar = Bar("AAPL", OPEN_TS, open=100.0, high=101.0, low=90.0, close=99.0,
                  volume=1e6)
        fill = self.matcher.match_bar(order, self.inst, bar).fills[0]
        self.assertEqual(fill.price, 95.0)   # not 90.0 — you did not catch the low

    def test_limit_that_was_not_touched_does_not_fill(self):
        order = Order("AAPL", Side.BUY, 100, OrderType.LIMIT, limit_price=85.0)
        bar = Bar("AAPL", OPEN_TS, open=100.0, high=101.0, low=90.0, close=99.0,
                  volume=1e6)
        self.assertEqual(self.matcher.match_bar(order, self.inst, bar).fills, [])

    def test_stop_limit_can_miss_a_gap_entirely(self):
        # The real failure mode: elected but unfillable, leaving the position
        # open and unprotected.
        order = Order("AAPL", Side.SELL, 100, OrderType.STOP_LIMIT,
                      stop_price=100.0, limit_price=99.0)
        gap = Bar("AAPL", OPEN_TS, open=94.0, high=94.5, low=93.0, close=93.5,
                  volume=1e6)
        result = self.matcher.match_bar(order, self.inst, gap)
        self.assertTrue(order.triggered)
        self.assertEqual(result.fills, [])
        # A plain stop would have protected the position, at a bad price.
        plain = Order("AAPL", Side.SELL, 100, OrderType.STOP, stop_price=100.0)
        self.assertTrue(self.matcher.match_bar(plain, self.inst, gap).fills)

    # ------------------------------------------------------ live matching

    def test_slippage_is_measured_against_the_decision_price(self):
        """Slippage must compare the fill to what the order could have expected
        to pay, not to wherever the bar happened to close. Referencing the close
        reports the whole day's move as an execution cost — 250bps instead of 2.
        """
        order = Order("AAPL", Side.BUY, 100, OrderType.MARKET)
        bar = Bar("AAPL", OPEN_TS, open=100.0, high=130.0, low=99.0,
                  close=128.0, volume=1e6)
        fill = Matcher(SlippageModel()).match_bar(order, self.inst, bar).fills[0]
        self.assertLess(abs(fill.slippage_bps), 60.0, fill.slippage_bps)
        self.assertGreaterEqual(fill.slippage_bps, 0.0,
                                "slippage is a cost, never a gift")

    def test_a_gapped_stop_reports_the_gap_as_its_slippage(self):
        order = Order("AAPL", Side.SELL, 100, OrderType.STOP, stop_price=100.0)
        gap = Bar("AAPL", OPEN_TS, open=92.0, high=93.0, low=90.0, close=91.0,
                  volume=1e6)
        fill = Matcher(SlippageModel()).match_bar(order, self.inst, gap).fills[0]
        # Roughly 8% worse than the stop, and reported as such.
        self.assertGreater(fill.slippage_bps, 700)

    def test_marketable_limit_gets_price_improvement(self):
        ctx = self.ctx(200.0)
        order = Order("AAPL", Side.BUY, 100, OrderType.LIMIT,
                      limit_price=ctx.book.ask + 1)
        fill = self.matcher.match(order, ctx).fills[0]
        self.assertLessEqual(fill.price, ctx.book.ask + 1e-9)
        self.assertIs(fill.liquidity, Liquidity.TAKER)

    def test_resting_limit_crossed_later_is_a_maker_fill_at_its_own_limit(self):
        ctx = self.ctx(200.0)
        order = Order("AAPL", Side.BUY, 100, OrderType.LIMIT,
                      limit_price=ctx.book.bid - 5)
        self.assertEqual(self.matcher.match(order, ctx).fills, [])
        self.assertTrue(order.rested)
        fill = self.matcher.match(order, self.ctx(ctx.book.bid - 6)).fills[0]
        self.assertEqual(fill.price, order.limit_price)
        self.assertIs(fill.liquidity, Liquidity.MAKER)

    def test_post_only_is_rejected_rather_than_crossing(self):
        ctx = self.ctx(200.0)
        order = Order("AAPL", Side.BUY, 100, OrderType.LIMIT,
                      limit_price=ctx.book.ask + 1, post_only=True)
        self.assertIs(self.matcher.match(order, ctx).status, OrderStatus.REJECTED)

    def test_nothing_fills_in_a_closed_market(self):
        closed = datetime(2026, 8, 23, 15, 0, tzinfo=UTC)      # Sunday
        ctx = self.ctx(200.0, closed)
        self.assertEqual(
            self.matcher.match(Order("AAPL", Side.BUY, 100), ctx).fills, [])

    def test_ioc_cancels_when_the_market_is_closed(self):
        closed = datetime(2026, 8, 23, 15, 0, tzinfo=UTC)
        order = Order("AAPL", Side.BUY, 100, tif=TimeInForce.IOC)
        result = self.matcher.match(order, self.ctx(200.0, closed))
        self.assertIs(result.status, OrderStatus.CANCELED)

    def test_extended_hours_is_opt_in(self):
        pre = datetime(2026, 8, 24, 11, 0, tzinfo=UTC)         # 07:00 ET
        ctx = self.ctx(200.0, pre)
        self.assertEqual(self.matcher.match(Order("AAPL", Side.BUY, 100), ctx).fills, [])
        allowed = Order("AAPL", Side.BUY, 100, allow_extended=True)
        self.assertTrue(self.matcher.match(allowed, ctx).fills)

    def test_large_orders_partially_fill_at_a_worse_price(self):
        ctx = self.ctx(200.0)
        result = self.matcher.match(Order("AAPL", Side.BUY, 5_000_000), ctx)
        self.assertGreater(result.filled_qty, 0)
        self.assertLess(result.filled_qty, 5_000_000)
        self.assertGreater(result.fills[0].price, ctx.book.ask)

    def test_iceberg_exposes_only_the_display_quantity(self):
        result = self.matcher.match(
            Order("AAPL", Side.BUY, 1000, display_qty=100), self.ctx(200.0))
        self.assertEqual(result.filled_qty, 100)

    def test_trailing_stop_ratchets_one_way_only(self):
        order = Order("AAPL", Side.SELL, 100, OrderType.TRAILING_STOP,
                      trail_pct=5.0)
        for price in (200, 210, 220, 215, 205):
            self.matcher.update_trailing(order, self.ctx(price))
        self.assertEqual(order.peak_price, 220)
        self.assertAlmostEqual(order.stop_price, 209.0, delta=0.02)
        self.assertTrue(self.matcher.match(order, self.ctx(208)).fills)


# ================================================================ portfolio


class TestPortfolio(unittest.TestCase):
    def setUp(self):
        self.p = Portfolio(starting_cash=100_000)

    def fill(self, symbol, side, qty, price, minutes=0, fee=0.0):
        return Fill("o", symbol, side, qty, price,
                    OPEN_TS + timedelta(minutes=minutes), fee=fee)

    def test_fifo_realizes_the_oldest_lot_first(self):
        self.p.apply_fill(self.fill("AAPL", Side.BUY, 100, 100.0))
        self.p.apply_fill(self.fill("AAPL", Side.BUY, 100, 120.0, 1))
        realized = self.p.apply_fill(self.fill("AAPL", Side.SELL, 100, 130.0, 2))
        # FIFO consumes the $100 lot: $30/share. Average cost would say $20.
        self.assertAlmostEqual(realized, 3000.0)

    def test_average_cost_is_recomputed_from_surviving_lots(self):
        self.p.apply_fill(self.fill("AAPL", Side.BUY, 100, 100.0))
        self.p.apply_fill(self.fill("AAPL", Side.BUY, 100, 120.0, 1))
        self.p.apply_fill(self.fill("AAPL", Side.SELL, 100, 130.0, 2))
        # The cheap lot is gone; what remains cost $120, not the old $110 mean.
        self.assertAlmostEqual(self.p.position("AAPL").avg_price, 120.0)
        self.p.mark({"AAPL": 130.0})
        self.assertAlmostEqual(self.p.unrealized_pnl(), 1000.0)

    def test_shorts_credit_cash_and_profit_when_prices_fall(self):
        self.p.apply_fill(self.fill("AAPL", Side.SELL, 100, 200.0))
        self.assertEqual(self.p.position("AAPL").qty, -100)
        self.assertAlmostEqual(self.p.balance(), 120_000.0)
        self.p.mark({"AAPL": 190.0})
        self.assertAlmostEqual(self.p.unrealized_pnl(), 1000.0)
        realized = self.p.apply_fill(self.fill("AAPL", Side.BUY, 100, 190.0))
        self.assertAlmostEqual(realized, 1000.0)

    def test_flipping_through_zero_opens_a_fresh_position(self):
        self.p.apply_fill(self.fill("AAPL", Side.BUY, 100, 100.0))
        realized = self.p.apply_fill(self.fill("AAPL", Side.SELL, 250, 110.0))
        position = self.p.position("AAPL")
        self.assertAlmostEqual(realized, 1000.0)     # only the 100 long closed
        self.assertEqual(position.qty, -150)
        self.assertEqual(position.avg_price, 110.0)

    def test_fx_pnl_converts_from_the_quote_currency(self):
        self.p.mark({"USDJPY": 147.20})
        self.p.apply_fill(self.fill("USDJPY", Side.BUY, 100_000, 147.20))
        self.p.mark({"USDJPY": 147.50})
        # +30,000 JPY is about +$203, not +$30,000.
        self.assertTrue(195 < self.p.unrealized_pnl() < 215)

    def test_reg_t_margin_call_threshold(self):
        p = Portfolio(starting_cash=10_000)
        p.mark({"AAPL": 200.0})
        p.apply_fill(self.fill("AAPL", Side.BUY, 100, 200.0))    # $20k on $10k
        p.mark({"AAPL": 140.0})
        self.assertFalse(p.margin_call())     # equity 4,000 vs maintenance 3,500
        p.mark({"AAPL": 130.0})
        self.assertTrue(p.margin_call())      # equity 3,000 vs maintenance 3,250

    def test_leverage_differs_by_asset_class(self):
        p = Portfolio(starting_cash=10_000)
        p.mark({"AAPL": 200.0, "BTCUSD": 64_000.0, "EURUSD": 1.085})
        self.assertAlmostEqual(p.buying_power("AAPL"), 20_000.0)     # Reg-T 2:1
        self.assertAlmostEqual(p.buying_power("BTCUSD"), 10_000.0)   # cash
        self.assertAlmostEqual(p.buying_power("EURUSD"), 500_000.0)  # 50:1

    def test_deposits_are_not_counted_as_profit(self):
        p = Portfolio(starting_cash=10_000)
        p.credit(5_000, "deposit", note="wire")
        self.assertEqual(p.equity(), 15_000)
        self.assertEqual(p.snapshot()["total_pnl"], 0)

    def test_cash_is_rounded_to_the_minor_unit(self):
        self.p.credit(0.1 + 0.2, "adjustment")
        self.assertEqual(self.p.balance(), 100_000.30)
        self.assertEqual(round_money(1.005, "JPY"), 1)

    def test_liquidation_order_is_biggest_requirement_first(self):
        p = Portfolio(starting_cash=100_000)
        p.mark({"AAPL": 200.0, "MSFT": 400.0})
        p.apply_fill(self.fill("AAPL", Side.BUY, 10, 200.0))     # $2k
        p.apply_fill(self.fill("MSFT", Side.BUY, 50, 400.0))     # $20k
        self.assertEqual(p.liquidation_order()[0].symbol, "MSFT")


# ===================================================================== risk


class TestRisk(unittest.TestCase):
    def setUp(self):
        self.p = Portfolio(starting_cash=10_000)
        self.p.mark({"AAPL": 200.0, "BTCUSD": 64_000.0, "EURUSD": 1.085})
        self.engine = RiskEngine(RiskLimits())
        self.state = RiskState(start_of_day_equity=10_000)

    def check(self, order, price, engine=None):
        return (engine or self.engine).check(order, self.p, self.state, price,
                                             OPEN_TS)

    def test_buying_power_respects_per_class_leverage(self):
        self.assertTrue(self.check(Order("AAPL", Side.BUY, 100), 200.0))
        self.assertFalse(self.check(Order("AAPL", Side.BUY, 200), 200.0))
        # 100k EUR/USD is $108k of notional but only $2.2k of margin.
        self.assertTrue(self.check(Order("EURUSD", Side.BUY, 100_000), 1.085))

    def test_concentration_is_measured_on_margin_not_notional(self):
        # Measuring notional would make every ordinary FX position look like
        # 1,000% of the account.
        decision = self.check(Order("EURUSD", Side.BUY, 100_000), 1.085)
        self.assertTrue(decision, decision.reason)

    def test_fat_finger_collar(self):
        decision = self.check(
            Order("AAPL", Side.BUY, 1, OrderType.LIMIT, limit_price=20.0), 200.0)
        self.assertFalse(decision)
        self.assertEqual(decision.code, "price_collar")

    def test_kill_switch_blocks_everything(self):
        engine = RiskEngine(RiskLimits(trading_halted=True, halt_reason="review"))
        self.assertFalse(self.check(Order("AAPL", Side.BUY, 1), 200.0, engine))

    def test_daily_loss_limit_blocks_new_risk_only(self):
        lost = Portfolio(starting_cash=9_000)
        lost.mark({"AAPL": 200.0})
        engine = RiskEngine(RiskLimits(daily_loss_limit=500))
        state = RiskState(start_of_day_equity=10_000)
        self.assertFalse(engine.check(Order("AAPL", Side.BUY, 1), lost, state,
                                      200.0, OPEN_TS))

    def test_margin_call_permits_only_reducing_orders(self):
        p = Portfolio(starting_cash=10_000)
        p.mark({"AAPL": 200.0})
        p.apply_fill(Fill("o", "AAPL", Side.BUY, 100, 200.0, OPEN_TS))
        p.mark({"AAPL": 130.0})
        self.assertTrue(p.margin_call())
        state = RiskState(start_of_day_equity=10_000)
        self.assertFalse(self.engine.check(Order("AAPL", Side.BUY, 1), p, state,
                                           130.0, OPEN_TS))
        self.assertTrue(self.engine.check(Order("AAPL", Side.SELL, 50), p, state,
                                          130.0, OPEN_TS))

    def test_shorting_can_be_disabled(self):
        engine = RiskEngine(RiskLimits(allow_shorting=False))
        self.assertFalse(self.check(Order("AAPL", Side.SELL, 5), 200.0, engine))

    def test_reduce_only_cannot_open_a_position(self):
        decision = self.check(Order("AAPL", Side.BUY, 1, reduce_only=True), 200.0)
        self.assertEqual(decision.code, "reduce_only_no_position")

    def test_max_qty_matches_what_the_checks_allow(self):
        qty = self.engine.max_qty("AAPL", Side.BUY, self.p, 200.0)
        self.assertTrue(self.check(Order("AAPL", Side.BUY, qty), 200.0))
        self.assertFalse(self.check(Order("AAPL", Side.BUY, qty + 1), 200.0))


# =================================================================== broker


class TestBroker(unittest.TestCase):
    def setUp(self):
        self.feed = SyntheticFeed()
        self.broker = PaperBroker(
            Portfolio(starting_cash=100_000), feed=self.feed,
            risk_limits=RiskLimits(max_position_pct_equity=1.0,
                                   enforce_pdt=False))
        self.price = self.feed.get_quote("BTCUSD").last

    def test_market_order_fills_and_updates_the_portfolio(self):
        order = self.broker.submit(Order("BTCUSD", Side.BUY, 0.5))
        self.assertIs(order.status, OrderStatus.FILLED)
        self.assertAlmostEqual(self.broker.portfolio.position("BTCUSD").qty, 0.5)

    def test_bracket_arms_an_oco_pair_and_one_cancels_the_other(self):
        self.broker.submit(Order("BTCUSD", Side.BUY, 0.5,
                                 take_profit=self.price * 1.05,
                                 stop_loss=self.price * 0.97))
        children = self.broker.open_orders("BTCUSD")
        self.assertEqual(len(children), 2)
        self.assertEqual(children[0].oco_group, children[1].oco_group)
        self.assertTrue(all(c.reduce_only for c in children))

        self.broker.on_market_data({"BTCUSD": make_quote(
            "BTCUSD", self.price * 1.06, ts=datetime.now(UTC),
            high=self.price * 1.07, low=self.price)})
        statuses = {c.order_type: c.status for c in children}
        self.assertIs(statuses[OrderType.LIMIT], OrderStatus.FILLED)
        self.assertIs(statuses[OrderType.STOP], OrderStatus.CANCELED)

    def test_rejected_orders_carry_a_reason(self):
        order = self.broker.submit(Order("BTCUSD", Side.BUY, 1000))
        self.assertIs(order.status, OrderStatus.REJECTED)
        self.assertTrue(order.reject_reason)

    def test_halt_cancels_working_orders_and_blocks_new_ones(self):
        self.broker.submit(Order("BTCUSD", Side.BUY, 0.01, OrderType.LIMIT,
                                 limit_price=self.price * 0.8,
                                 tif=TimeInForce.GTC))
        self.assertEqual(len(self.broker.working), 1)
        self.broker.halt("compliance review")
        self.assertEqual(len(self.broker.working), 0)
        blocked = self.broker.submit(Order("BTCUSD", Side.BUY, 0.01))
        self.assertIs(blocked.status, OrderStatus.REJECTED)
        self.broker.resume()
        self.assertIs(self.broker.submit(Order("BTCUSD", Side.BUY, 0.01)).status,
                      OrderStatus.FILLED)

    def test_flatten_all_closes_every_position(self):
        self.broker.submit(Order("BTCUSD", Side.BUY, 0.2))
        self.broker.submit(Order("ETHUSD", Side.BUY, 2))
        self.broker.flatten_all()
        self.assertEqual(self.broker.portfolio.open_positions(), [])

    def test_close_position_is_reduce_only(self):
        self.broker.submit(Order("BTCUSD", Side.BUY, 0.2))
        order = self.broker.close_position("BTCUSD")
        self.assertTrue(order.reduce_only)
        self.assertTrue(self.broker.portfolio.position("BTCUSD").is_flat)

    def test_day_order_placed_after_hours_rolls_to_the_next_session(self):
        """A DAY order submitted while the market is shut belongs to the next
        session. Pinning it to a close already in the past would expire it on
        arrival — which silently broke every backtest until it was fixed."""
        from deoltech.clock import next_open
        closed = datetime(2026, 8, 23, 15, 0, tzinfo=UTC)      # Sunday
        broker = PaperBroker(Portfolio(starting_cash=100_000),
                             feed=self.feed, clock=lambda: closed,
                             risk_limits=RiskLimits(enforce_pdt=False))
        # Priced just under the market so the fat-finger collar is not what
        # this test ends up measuring.
        market = self.feed.get_quote("AAPL").last
        order = broker.submit(Order("AAPL", Side.BUY, 1, OrderType.LIMIT,
                                    limit_price=round(market * 0.95, 2),
                                    tif=TimeInForce.DAY))
        self.assertTrue(order.is_open, order.reject_reason)
        self.assertIsNotNone(order.expires_at)
        self.assertGreater(order.expires_at, closed)

    def test_journal_records_every_transition(self):
        self.broker.submit(Order("BTCUSD", Side.BUY, 0.1))
        kinds = [e.kind for e in self.broker.events]
        for expected in ("submit", "accept", "fill"):
            self.assertIn(expected, kinds)


# ================================================================ analytics


class TestAnalytics(unittest.TestCase):
    def curve(self, values):
        from deoltech.engine.broker import EquityPoint
        base = datetime(2026, 1, 5, tzinfo=UTC)
        return [EquityPoint(base + timedelta(days=i), v, v, 0, 0)
                for i, v in enumerate(values)]

    def test_round_trips_are_reconstructed_fifo(self):
        fills = [
            Fill("1", "AAPL", Side.BUY, 100, 100.0, OPEN_TS),
            Fill("2", "AAPL", Side.BUY, 100, 110.0, OPEN_TS + timedelta(days=1)),
            Fill("3", "AAPL", Side.SELL, 150, 120.0, OPEN_TS + timedelta(days=2)),
        ]
        trips = analytics.reconstruct_trades(fills)
        self.assertEqual(len(trips), 2)
        self.assertAlmostEqual(trips[0].pnl, 2000.0)    # 100 from the $100 lot
        self.assertAlmostEqual(trips[1].pnl, 500.0)     # 50 from the $110 lot

    def test_open_positions_are_not_counted_as_results(self):
        trips = analytics.reconstruct_trades(
            [Fill("1", "AAPL", Side.BUY, 100, 100.0, OPEN_TS)])
        self.assertEqual(trips, [])

    def test_low_sample_is_flagged_and_annualization_suppressed(self):
        perf = analytics.analyze(self.curve([100_000, 101_000]), [])
        self.assertTrue(perf.low_confidence)
        self.assertIsNone(perf.cagr_pct)
        self.assertIn("Low confidence", perf.caveats[0])

    def test_a_single_outlier_cannot_masquerade_as_an_edge(self):
        # 19 small losses and one large win: profitable in total, but the median
        # trade loses. The verdict must say so.
        fills = []
        base = datetime(2026, 1, 5, tzinfo=UTC)
        for i in range(20):
            entry = base + timedelta(days=i * 2)
            exit_price = 100.0 + (80.0 if i == 19 else -1.0)
            fills.append(Fill(str(i), "XYZ", Side.BUY, 10, 100.0, entry))
            fills.append(Fill(str(i), "XYZ", Side.SELL, 10, exit_price,
                              entry + timedelta(days=1)))
        perf = analytics.analyze(self.curve([100_000 + i * 10 for i in range(60)]),
                                 fills)
        self.assertGreater(perf.mean_trade_pnl, 0)
        self.assertLessEqual(perf.median_trade_pnl, 0)
        self.assertIn("MEDIAN", perf.verdict())

    def test_drawdown_measures_peak_to_trough(self):
        frac, absolute, _ = analytics.max_drawdown(
            self.curve([100, 120, 90, 110]))
        self.assertAlmostEqual(frac, 0.25)          # 120 -> 90
        self.assertAlmostEqual(absolute, 30.0)

    def test_sharpe_is_zero_without_variation(self):
        self.assertEqual(analytics.sharpe([0.01] * 10), 0.0)

    def test_attribution_flags_thin_samples(self):
        fills = [Fill("a", "TSLA", Side.BUY, 10, 200.0, OPEN_TS),
                 Fill("b", "TSLA", Side.SELL, 10, 260.0,
                      OPEN_TS + timedelta(days=1))]
        rows = analytics.by_symbol(fills)
        self.assertTrue(rows[0]["low_confidence"])


# ================================================================ backtester


class TestBacktester(unittest.TestCase):
    def setUp(self):
        self.bars = SyntheticFeed().get_bars("AAPL", "1d", 300)

    def test_buy_and_hold_tracks_the_benchmark_and_pays_costs(self):
        """Buy-and-hold should shadow the benchmark, not match it exactly.

        The benchmark measures the first bar's open to the last bar's close.
        The strategy cannot act until a bar has completed, so it enters one bar
        later at a different price — that gap is real and can go either way.
        What must hold is that it takes exactly one position, pays genuine
        costs, and ends up in the same neighbourhood as holding the asset.
        """
        from deoltech.strategies import BuyAndHold
        result = Backtester(starting_cash=100_000).run(
            BuyAndHold(allocation=0.95), self.bars, symbol="AAPL")
        self.assertIsNotNone(result.benchmark_return_pct)
        self.assertEqual(result.performance.trades, 1)
        self.assertGreater(result.performance.total_fees, 0,
                           "even buy-and-hold pays to get in and out")
        drift = abs(result.total_return_pct - result.benchmark_return_pct)
        self.assertLess(drift, 15.0,
                        "buy-and-hold should shadow the underlying, not diverge")

    def test_strategies_pay_real_costs(self):
        from deoltech.strategies import SmaCrossover
        result = Backtester(starting_cash=100_000).run(
            SmaCrossover(fast=5, slow=15), self.bars, symbol="AAPL")
        self.assertGreater(len(result.fills), 0)
        self.assertGreater(result.performance.total_fees, 0)

    def test_a_strategy_cannot_see_the_future(self):
        """A strategy that buys the low of every bar would be enormously
        profitable if the engine allowed it. It cannot, because an order placed
        while looking at a completed bar is matched against the NEXT one."""
        from deoltech.strategies.base import Strategy

        class Clairvoyant(Strategy):
            name = "clairvoyant"

            def on_bar(self, ctx, bar):
                if ctx.is_flat:
                    ctx.buy(10, limit=bar.low)      # the low ALREADY happened
                else:
                    ctx.close()

        result = Backtester(starting_cash=100_000).run(
            Clairvoyant(), self.bars, symbol="AAPL")
        self.assertLess(result.total_return_pct, 25.0,
                        "buying each bar's low should not be possible")

    def test_results_are_reproducible(self):
        from deoltech.strategies import DonchianBreakout
        a = Backtester().run(DonchianBreakout(), self.bars, symbol="AAPL")
        b = Backtester().run(DonchianBreakout(), self.bars, symbol="AAPL")
        self.assertEqual(a.ending_equity, b.ending_equity)
        self.assertEqual(len(a.fills), len(b.fills))

    def test_too_few_bars_is_an_error(self):
        with self.assertRaises(ValueError):
            Backtester().run(None, self.bars[:1], symbol="AAPL")


class TestIndicators(unittest.TestCase):
    def test_series_stay_aligned_to_their_input(self):
        values = list(range(1, 31))
        for series in (indicators.sma(values, 5), indicators.ema(values, 5),
                       indicators.rsi(values, 14)):
            self.assertEqual(len(series), len(values))

    def test_donchian_excludes_the_current_bar(self):
        # Including it would make a breakout undetectable until after the fact.
        bars = [Bar("X", OPEN_TS + timedelta(days=i), open=v, high=v + 1,
                    low=v - 1, close=v, volume=100)
                for i, v in enumerate([10, 11, 12, 13, 14, 20])]
        highs, _ = indicators.donchian(bars, 5)
        self.assertEqual(highs[5], 15.0)     # max of bars 0-4, not bar 5's 21

    def test_atr_is_positive_and_warmed_up(self):
        bars = [Bar("X", OPEN_TS + timedelta(days=i), open=100, high=102,
                    low=98, close=101, volume=100) for i in range(30)]
        values = indicators.atr(bars, 14)
        self.assertIsNone(values[5])
        self.assertGreater(values[-1], 0)


# ===================================================================== auth


class TestAuth(unittest.TestCase):
    def setUp(self):
        from deoltech import auth, db
        self.auth, self.db = auth, db
        self.path = os.path.join(_TMPDIR, f"auth-{id(self)}.db")
        self.conn = db.connect(self.path)
        self.admin, self.password = auth.bootstrap_admin(self.conn, "root")

    def test_passwords_are_salted_and_verifiable(self):
        a = self.auth.hash_password("Str0ng&Passphrase!")
        b = self.auth.hash_password("Str0ng&Passphrase!")
        self.assertNotEqual(a, b)                      # unique salts
        self.assertTrue(self.auth.verify_password("Str0ng&Passphrase!", a)[0])
        self.assertFalse(self.auth.verify_password("wrong", a)[0])

    def test_password_policy(self):
        self.assertTrue(self.auth.password_problems("short"))
        self.assertTrue(self.auth.password_problems("alllowercaseletters"))
        self.assertFalse(self.auth.password_problems("Str0ng&Passphrase!"))

    def test_generated_passwords_satisfy_the_policy(self):
        for _ in range(10):
            self.assertFalse(self.auth.password_problems(
                self.auth.generate_password()))

    def test_bootstrap_is_idempotent(self):
        user, password = self.auth.bootstrap_admin(self.conn, "root")
        self.assertEqual(user.id, self.admin.id)
        self.assertIsNone(password, "must not print a password it did not set")

    def test_roles_gate_permissions(self):
        trader = self.auth.create_user(self.conn, "trader1", "Tr@derPass2026!",
                                       role=self.auth.Role.TRADER,
                                       actor=self.admin)
        viewer = self.auth.create_user(self.conn, "viewer1", "V!ewerPass2026x",
                                       role=self.auth.Role.VIEWER,
                                       actor=self.admin)
        self.assertTrue(self.admin.can("admin.users"))
        self.assertTrue(trader.can("trade.submit"))
        self.assertFalse(trader.can("admin.users"))
        self.assertFalse(viewer.can("trade.submit"))
        self.assertTrue(viewer.can("view.market"))
        with self.assertRaises(self.auth.PermissionDenied):
            trader.require("admin.users")

    def test_login_and_session_lifecycle(self):
        user, token = self.auth.login(self.conn, "root", self.password)
        self.assertEqual(self.auth.session_user(self.conn, token).id, user.id)
        self.assertIsNone(self.auth.session_user(self.conn, "not-a-token"))
        self.auth.logout(self.conn, token, user)
        self.assertIsNone(self.auth.session_user(self.conn, token))

    def test_failed_logins_are_indistinguishable(self):
        messages = set()
        for username, password in (("nosuchuser", "x"), ("root", "wrong")):
            try:
                self.auth.login(self.conn, username, password)
            except self.auth.AuthError as e:
                messages.add(str(e))
        self.assertEqual(len(messages), 1, "message must not leak whether the "
                                           "username exists")

    def test_repeated_failures_lock_the_account(self):
        self.auth.create_user(self.conn, "target", "T@rgetPass2026!",
                              role=self.auth.Role.VIEWER, actor=self.admin)
        for _ in range(self.auth.MAX_FAILED_LOGINS + 1):
            with self.assertRaises(self.auth.AuthError):
                self.auth.login(self.conn, "target", "wrong")
        # Even the CORRECT password is refused while locked.
        with self.assertRaises(self.auth.AuthError) as ctx:
            self.auth.login(self.conn, "target", "T@rgetPass2026!")
        self.assertIn("locked", str(ctx.exception).lower())

    def test_the_last_administrator_is_protected(self):
        for action in (
            lambda: self.auth.set_role(self.conn, self.admin, self.admin.id,
                                       self.auth.Role.TRADER),
            lambda: self.auth.set_status(self.conn, self.admin, self.admin.id,
                                         "suspended"),
            lambda: self.auth.delete_user(self.conn, self.admin, self.admin.id),
        ):
            with self.assertRaises(self.auth.AuthError):
                action()

    def test_suspension_revokes_live_sessions_immediately(self):
        trader = self.auth.create_user(self.conn, "trader2", "Tr@derPass2026!",
                                       role=self.auth.Role.TRADER,
                                       actor=self.admin)
        _, token = self.auth.login(self.conn, "trader2", "Tr@derPass2026!")
        self.assertIsNotNone(self.auth.session_user(self.conn, token))
        self.auth.set_status(self.conn, self.admin, trader.id, "suspended")
        self.assertIsNone(self.auth.session_user(self.conn, token))

    def test_role_change_revokes_live_sessions(self):
        trader = self.auth.create_user(self.conn, "trader3", "Tr@derPass2026!",
                                       role=self.auth.Role.TRADER,
                                       actor=self.admin)
        _, token = self.auth.login(self.conn, "trader3", "Tr@derPass2026!")
        self.auth.set_role(self.conn, self.admin, trader.id,
                           self.auth.Role.VIEWER)
        self.assertIsNone(self.auth.session_user(self.conn, token))

    def test_api_tokens_resolve_and_revoke(self):
        token = self.auth.create_api_token(self.conn, self.admin, "ci")
        self.assertEqual(self.auth.token_user(self.conn, token).id, self.admin.id)
        self.assertIsNone(self.auth.token_user(self.conn, "dt_bogus"))
        token_id = self.auth.list_api_tokens(self.conn, self.admin.id)[0]["id"]
        self.auth.revoke_api_token(self.conn, self.admin, token_id)
        self.assertIsNone(self.auth.token_user(self.conn, token))

    def test_admin_actions_are_audited(self):
        self.auth.create_user(self.conn, "audited", "@uditedPass2026!",
                              role=self.auth.Role.TRADER, actor=self.admin)
        actions = [e["action"] for e in self.db.audit_trail(self.conn, 50)]
        self.assertIn("user.create", actions)
        self.assertIn("system.bootstrap", actions)


# ============================================================== persistence


class TestAccountPersistence(unittest.TestCase):
    def setUp(self):
        from deoltech import accounts, auth, db
        self.accounts, self.db = accounts, db
        self.path = os.path.join(_TMPDIR, f"acct-{id(self)}.db")
        os.environ["DEOLTECH_DB"] = self.path
        self.conn = db.connect(self.path)
        self.user, _ = auth.bootstrap_admin(self.conn, "owner")
        self.account_id = accounts.create_account(self.conn, self.user.id,
                                                  "Main", starting_cash=50_000)
        from deoltech.feeds import build_feed
        self.service = accounts.AccountService(
            lambda: db.connect(self.path), feed=build_feed("synthetic"))

    def tearDown(self):
        os.environ["DEOLTECH_DB"] = os.path.join(_TMPDIR, "test.db")

    def test_state_survives_a_restart(self):
        for order in (Order("BTCUSD", Side.BUY, 0.1),
                      Order("ETHUSD", Side.BUY, 1),
                      Order("EURUSD", Side.BUY, 10_000)):
            self.service.submit(self.account_id, order)
        before = self.service.broker(self.account_id).portfolio.snapshot()

        self.service.evict(self.account_id)           # simulate a restart
        after = self.service.broker(self.account_id).portfolio.snapshot()
        for key in ("equity", "cash", "realized_pnl", "fees_paid",
                    "market_value", "margin_used"):
            self.assertAlmostEqual(before[key], after[key], places=2, msg=key)

    def test_tax_lots_are_preserved_across_a_reload(self):
        self.service.submit(self.account_id, Order("BTCUSD", Side.BUY, 0.05))
        self.service.submit(self.account_id, Order("BTCUSD", Side.BUY, 0.05))
        self.service.evict(self.account_id)
        position = self.service.broker(self.account_id).portfolio.position("BTCUSD")
        self.assertEqual(len(position.lots), 2)

    def test_working_orders_are_restored(self):
        price = self.service.quote("BTCUSD").last
        self.service.submit(self.account_id,
                            Order("BTCUSD", Side.BUY, 0.01, OrderType.LIMIT,
                                  limit_price=round(price * 0.85, 2),
                                  tif=TimeInForce.GTC))
        self.service.evict(self.account_id)
        self.assertEqual(len(self.service.broker(self.account_id).working), 1)

    def test_reset_clears_everything(self):
        self.service.submit(self.account_id, Order("BTCUSD", Side.BUY, 0.1))
        self.accounts.reset_account(self.conn, self.account_id)
        self.service.evict(self.account_id)
        broker = self.service.broker(self.account_id)
        self.assertEqual(broker.portfolio.open_positions(), [])
        self.assertEqual(broker.portfolio.equity(), 50_000)

    def test_watchlist_normalizes_and_deduplicates(self):
        result = self.service.set_watchlist(self.user.id,
                                            ["nvda", "btc-usd", "NVDA", "eurusd"])
        self.assertEqual(result, ["NVDA", "BTCUSD", "EURUSD"])


class TestBackup(unittest.TestCase):
    """A backup that has never been restored is a hypothesis, so test both."""

    def test_backup_round_trips(self):
        import gzip
        import shutil
        import sqlite3
        from deoltech import accounts, auth, db
        from deoltech.cli import main

        path = os.path.join(_TMPDIR, f"backup-src-{id(self)}.db")
        os.environ["DEOLTECH_DB"] = path
        conn = db.connect(path)
        user, _ = auth.bootstrap_admin(conn, "backupowner")
        accounts.create_account(conn, user.id, "Main", starting_cash=25_000)

        dest = os.path.join(_TMPDIR, f"backup-out-{id(self)}")
        try:
            self.assertEqual(main(["backup", dest]), 0)
            archives = [f for f in os.listdir(dest) if f.endswith(".db.gz")]
            self.assertEqual(len(archives), 1)

            restored = os.path.join(dest, "restored.db")
            with gzip.open(os.path.join(dest, archives[0]), "rb") as src, \
                 open(restored, "wb") as dst:
                shutil.copyfileobj(src, dst)
            check = sqlite3.connect(restored)
            try:
                self.assertEqual(
                    check.execute("PRAGMA integrity_check").fetchone()[0], "ok")
                self.assertEqual(
                    check.execute("SELECT COUNT(*) FROM users").fetchone()[0], 1)
                self.assertEqual(
                    check.execute("SELECT username FROM users").fetchone()[0],
                    "backupowner")
                self.assertEqual(
                    check.execute("SELECT COUNT(*) FROM accounts").fetchone()[0], 1)
            finally:
                check.close()
        finally:
            os.environ["DEOLTECH_DB"] = os.path.join(_TMPDIR, "test.db")

    def test_backup_of_a_missing_database_fails_loudly(self):
        from deoltech.cli import main
        os.environ["DEOLTECH_DB"] = os.path.join(_TMPDIR, "definitely-not-here.db")
        try:
            self.assertEqual(main(["backup", os.path.join(_TMPDIR, "nope")]), 1)
        finally:
            os.environ["DEOLTECH_DB"] = os.path.join(_TMPDIR, "test.db")


# ================================================================== the web


class TestWebApp(unittest.TestCase):
    """Drives the real WSGI-less request path — routing, auth, CSRF, JSON."""

    @classmethod
    def setUpClass(cls):
        from deoltech.web.app import Platform, build_app
        cls.path = os.path.join(_TMPDIR, "web.db")
        os.environ["DEOLTECH_DB"] = cls.path
        cls.platform = Platform(feed_mode="synthetic")
        cls.app = build_app(cls.platform, secret="test-secret")

    @classmethod
    def tearDownClass(cls):
        os.environ["DEOLTECH_DB"] = os.path.join(_TMPDIR, "test.db")

    def request(self, path, method="GET", form=None, token="", headers=None):
        """Drive one request through the real dispatcher.

        Splits the query string the way the HTTP layer does, so paths with
        parameters route the same here as they do over a socket.
        """
        from urllib.parse import parse_qs, urlparse
        from deoltech.web.server import Request
        parsed = urlparse(path)
        req = Request(
            method=method, path=parsed.path,
            query={k: v[-1] for k, v in parse_qs(parsed.query,
                                                 keep_blank_values=True).items()},
            form=form or {},
            headers={"accept": "application/json"
                     if parsed.path.startswith("/api/") else "text/html",
                     **(headers or {})},
            session_token=token, remote_addr="127.0.0.1")
        return self.app.handle(req)

    def setUp(self):
        if self.platform.needs_setup():
            self.request("/setup", "POST", {
                "username": "arjan", "password": "Deol&Tech2026x!",
                "confirm": "Deol&Tech2026x!"})
        from deoltech.auth import login
        _, self.token = login(self.platform.conn(), "arjan", "Deol&Tech2026x!")
        self.csrf = self.app.csrf_token(self.token)

    def test_unauthenticated_pages_redirect(self):
        response = self.request("/")
        self.assertIn(response.status, (302, 303))
        self.assertIn("/login", response.headers.get("Location", ""))

    def test_unauthenticated_api_returns_401_json(self):
        response = self.request("/api/account")
        self.assertEqual(response.status, 401)
        self.assertIn("error", json.loads(response.body))

    def test_every_page_renders_for_an_admin(self):
        for path in ("/", "/terminal", "/terminal?symbol=BTCUSD", "/positions",
                     "/orders", "/blotter", "/analytics", "/markets",
                     "/backtest", "/profile", "/admin", "/admin/users",
                     "/admin/accounts", "/admin/audit", "/admin/system"):
            with self.subTest(path=path):
                response = self.request(path, token=self.token)
                self.assertEqual(response.status, 200, path)
                self.assertIn(b"Deol Tech", response.body)

    def test_csrf_is_required_for_mutations(self):
        response = self.request("/api/orders", "POST",
                                {"symbol": "BTCUSD", "side": "buy", "qty": "0.01"},
                                token=self.token)
        self.assertEqual(response.status, 403)

    def test_order_placement_round_trip(self):
        response = self.request("/api/orders", "POST", {
            "symbol": "BTCUSD", "side": "buy", "qty": "0.01",
            "order_type": "market", "csrf_token": self.csrf}, token=self.token)
        self.assertEqual(response.status, 200)
        self.assertEqual(json.loads(response.body)["status"], "filled")

    def test_invalid_orders_are_rejected_with_a_reason(self):
        cases = [
            ({"symbol": "AAPL", "side": "buy", "qty": "0"}, "greater than zero"),
            ({"symbol": "AAPL", "side": "buy", "qty": "0.5"}, "AAPL"),
            ({"symbol": "AAPL", "side": "buy", "qty": "1",
              "order_type": "limit"}, "limit price"),
            ({"symbol": "", "side": "buy", "qty": "1"}, "symbol"),
            ({"symbol": "AAPL", "side": "sideways", "qty": "1"}, "Side"),
        ]
        for form, expected in cases:
            with self.subTest(form=form):
                response = self.request("/api/orders", "POST",
                                        {**form, "csrf_token": self.csrf},
                                        token=self.token)
                self.assertEqual(response.status, 400)
                self.assertIn(expected, json.loads(response.body)["error"])

    def test_quotes_and_bars_endpoints(self):
        data = json.loads(self.request("/api/quotes?symbols=AAPL,BTCUSD",
                                       token=self.token).body)
        self.assertIn("AAPL", data["quotes"])
        self.assertIn("feed", data)
        bars = json.loads(self.request("/api/bars?symbol=AAPL&interval=1d&limit=30",
                                       token=self.token).body)
        self.assertEqual(len(bars["bars"]), 30)

    def test_health_is_public_and_honest_about_the_data_source(self):
        response = self.request("/api/health")
        self.assertEqual(response.status, 200)
        body = json.loads(response.body)
        self.assertEqual(body["status"], "ok")
        # This instance runs the simulator; saying "live" here would hide a
        # misconfiguration behind a green check.
        self.assertEqual(body["market_data"], "simulated")

    def test_static_assets_are_served_with_an_etag(self):
        response = self.request("/static/app.css")
        self.assertEqual(response.status, 200)
        self.assertIn("ETag", response.headers)

    def test_unknown_routes_404(self):
        self.assertEqual(self.request("/nope", token=self.token).status, 404)

    def test_html_is_escaped(self):
        from deoltech.web.templates import esc
        self.assertEqual(esc("<script>alert(1)</script>"),
                         "&lt;script&gt;alert(1)&lt;/script&gt;")

    def test_viewers_cannot_trade(self):
        from deoltech.auth import Role, create_user, get_user, login
        conn = self.platform.conn()
        admin = get_user(conn, 1)
        create_user(conn, "watcher", "W@tcherPass2026!", role=Role.VIEWER,
                    actor=admin)
        _, token = login(conn, "watcher", "W@tcherPass2026!")
        response = self.request("/api/orders", "POST", {
            "symbol": "BTCUSD", "side": "buy", "qty": "0.01",
            "csrf_token": self.app.csrf_token(token)}, token=token)
        self.assertEqual(response.status, 403)

    def test_non_admins_cannot_reach_the_admin_console(self):
        from deoltech.auth import Role, create_user, get_user, login
        conn = self.platform.conn()
        create_user(conn, "plaintrader", "Pl@inPass2026!!", role=Role.TRADER,
                    actor=get_user(conn, 1))
        _, token = login(conn, "plaintrader", "Pl@inPass2026!!")
        self.assertEqual(self.request("/admin/users", token=token).status, 403)


if __name__ == "__main__":
    unittest.main(verbosity=2)
