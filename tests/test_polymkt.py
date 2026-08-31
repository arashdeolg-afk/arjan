"""Tests for the Polymarket client. Run:

    python3 -m unittest discover -s tests -v

Every test here is offline. The HTTP layer takes an injectable transport
precisely so this file never touches the network — which also means these
pass in an environment where polymarket.com is blocked entirely.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from polymkt import config as C                 # noqa: E402
from polymkt import endpoints as E              # noqa: E402
from polymkt import store as S                  # noqa: E402
from polymkt.clob import Clob                   # noqa: E402
from polymkt.cli import main                    # noqa: E402
from polymkt.data import Data                   # noqa: E402
from polymkt.gamma import Gamma                 # noqa: E402
from polymkt.http import (Client, HTTPError, TransportError,  # noqa: E402
                          _encode)
from polymkt.models import Book, Market, as_float, as_list  # noqa: E402
from polymkt.samples import fake_transport      # noqa: E402


def json_response(payload, status=200):
    def transport(method, url, headers, body):
        return status, {}, json.dumps(payload).encode()
    return transport


class TestNormalisation(unittest.TestCase):
    """The stringified-JSON trap is the whole reason models.py exists."""

    def test_stringified_array_becomes_a_list(self):
        self.assertEqual(as_list('["Yes", "No"]'), ["Yes", "No"])

    def test_a_plain_string_is_not_iterated_character_by_character(self):
        # The bug this guards: "Yes" -> ["Y", "e", "s"]
        self.assertEqual(as_list("Yes"), ["Yes"])

    def test_empty_and_null_are_empty(self):
        for value in (None, "", []):
            self.assertEqual(as_list(value), [])

    def test_float_coercion_never_raises(self):
        self.assertEqual(as_float("0.62"), 0.62)
        self.assertEqual(as_float(0.62), 0.62)
        self.assertIsNone(as_float("not a number"))
        self.assertIsNone(as_float(None))
        self.assertEqual(as_float(None, 0.0), 0.0)

    def test_gamma_market_pairs_outcomes_tokens_and_prices(self):
        m = Market.from_gamma({
            "id": "1", "question": "Q?", "slug": "q", "conditionId": "0xc",
            "outcomes": json.dumps(["Yes", "No"]),
            "outcomePrices": json.dumps(["0.62", "0.38"]),
            "clobTokenIds": json.dumps(["1001", "1002"]),
        })
        self.assertEqual([o.name for o in m.outcomes], ["Yes", "No"])
        self.assertEqual(m.token_ids, ["1001", "1002"])
        self.assertEqual(m.outcome("yes").price, 0.62)
        self.assertAlmostEqual(m.book_sum(), 1.0)
        self.assertEqual(m.favourite().name, "Yes")

    def test_ragged_arrays_do_not_lose_outcomes(self):
        """A market with prices but no tokens must still list its outcomes."""
        m = Market.from_gamma({
            "id": "1", "question": "Q?", "slug": "q", "conditionId": "0xc",
            "outcomes": json.dumps(["Yes", "No", "Maybe"]),
            "outcomePrices": json.dumps(["0.5", "0.3"]),
            "clobTokenIds": json.dumps([]),
        })
        self.assertEqual(len(m.outcomes), 3)
        self.assertIsNone(m.outcomes[2].price)
        self.assertEqual(m.token_ids, [])

    def test_clob_market_shape_also_works(self):
        m = Market.from_clob({
            "condition_id": "0xc", "question": "Q?", "market_slug": "q",
            "tokens": [{"token_id": "1", "outcome": "Yes", "price": "0.7"},
                       {"token_id": "2", "outcome": "No", "price": "0.3"}],
        })
        self.assertEqual(m.condition_id, "0xc")
        self.assertEqual(m.outcome("No").price, 0.3)


class TestBook(unittest.TestCase):
    def setUp(self):
        # Deliberately unsorted, as the server sometimes sends it.
        self.book = Book.from_clob({
            "asset_id": "1001",
            "bids": [{"price": "0.58", "size": "4200"},
                     {"price": "0.61", "size": "900"},
                     {"price": "0.60", "size": "1500"}],
            "asks": [{"price": "0.65", "size": "3300"},
                     {"price": "0.63", "size": "1100"},
                     {"price": "0.64", "size": "2000"}],
        })

    def test_sides_are_sorted_best_first_regardless_of_input_order(self):
        self.assertEqual([l.price for l in self.book.bids], [0.61, 0.60, 0.58])
        self.assertEqual([l.price for l in self.book.asks], [0.63, 0.64, 0.65])

    def test_best_prices_cannot_invert(self):
        self.assertLess(self.book.best_bid, self.book.best_ask)
        self.assertAlmostEqual(self.book.midpoint, 0.62)
        self.assertAlmostEqual(self.book.spread, 0.02)

    def test_sweep_costs_more_than_the_midpoint(self):
        avg, filled = self.book.sweep(1000)
        self.assertAlmostEqual(filled, 1000)
        self.assertGreater(avg, self.book.midpoint)

    def test_sweep_reports_a_partial_fill_rather_than_pretending(self):
        # Total ask capacity is 0.63*1100 + 0.64*2000 + 0.65*3300 = $4,118.
        avg, filled = self.book.sweep(10_000)
        self.assertAlmostEqual(filled, 4118.0, places=2)
        self.assertLess(filled, 10_000)

    def test_empty_book_is_not_a_crash(self):
        empty = Book.from_clob({"asset_id": "x", "bids": [], "asks": []})
        self.assertIsNone(empty.midpoint)
        self.assertIsNone(empty.spread)
        self.assertEqual(empty.sweep(100), (None, 0.0))

    def test_book_keeps_the_metadata_the_live_response_carries(self):
        b = Book.from_clob({
            "asset_id": "1001", "bids": [], "asks": [],
            "tick_size": "0.01", "min_order_size": "5",
            "last_trade_price": "0.57", "neg_risk": True,
        })
        self.assertEqual(b.tick_size, 0.01)
        self.assertEqual(b.min_order_size, 5.0)
        self.assertEqual(b.last_trade_price, 0.57)
        self.assertTrue(b.neg_risk)

    def test_book_metadata_is_optional(self):
        b = Book.from_clob({"asset_id": "x", "bids": [], "asks": []})
        self.assertIsNone(b.tick_size)
        self.assertFalse(b.neg_risk)

    def test_zero_size_levels_are_dropped(self):
        b = Book.from_clob({"asset_id": "x",
                            "bids": [{"price": "0.5", "size": "0"}], "asks": []})
        self.assertEqual(b.bids, [])


class TestHttp(unittest.TestCase):
    def test_query_encoding_drops_none_expands_lists_lowercases_bools(self):
        self.assertEqual(_encode({"a": None, "b": True, "c": False}), "b=true&c=false")
        self.assertEqual(_encode({"tag_id": [1, 2]}), "tag_id=1&tag_id=2")
        self.assertEqual(_encode({}), "")

    def test_4xx_raises_without_retrying(self):
        calls = []

        def transport(method, url, headers, body):
            calls.append(url)
            return 404, {}, b'{"error":"not found"}'

        client = Client("https://x.test", transport=transport, min_interval=0)
        with self.assertRaises(HTTPError) as ctx:
            client.get("/nope")
        self.assertEqual(ctx.exception.status, 404)
        self.assertEqual(len(calls), 1, "4xx is final; retrying it is just noise")

    def test_429_is_retried_then_succeeds(self):
        attempts = []

        def transport(method, url, headers, body):
            attempts.append(url)
            if len(attempts) < 3:
                return 429, {"Retry-After": "0"}, b""
            return 200, {}, b'{"ok":true}'

        client = Client("https://x.test", transport=transport, min_interval=0, retries=3)
        with mock.patch("polymkt.http.time.sleep"):
            self.assertEqual(client.get("/thing"), {"ok": True})
        self.assertEqual(len(attempts), 3)

    def test_retries_are_finite(self):
        def always_500(method, url, headers, body):
            return 500, {}, b"boom"

        client = Client("https://x.test", transport=always_500, min_interval=0, retries=2)
        with mock.patch("polymkt.http.time.sleep"):
            with self.assertRaises(HTTPError):
                client.get("/thing")
        self.assertEqual(client.calls, 3, "one initial attempt plus two retries")

    def test_transport_failure_surfaces_as_transport_error(self):
        def dead(method, url, headers, body):
            raise TransportError("no route to host")

        client = Client("https://x.test", transport=dead, min_interval=0, retries=1)
        with mock.patch("polymkt.http.time.sleep"):
            with self.assertRaises(TransportError):
                client.get("/thing")

    def test_non_json_body_is_reported_clearly(self):
        client = Client("https://x.test", min_interval=0,
                        transport=lambda *a: (200, {}, b"<html>maintenance</html>"))
        with self.assertRaisesRegex(Exception, "not JSON"):
            client.get("/thing")

    def test_empty_body_is_none_not_an_error(self):
        client = Client("https://x.test", min_interval=0,
                        transport=lambda *a: (200, {}, b""))
        self.assertIsNone(client.get("/thing"))


class TestClients(unittest.TestCase):
    def setUp(self):
        self.gamma = Gamma(transport=fake_transport)
        self.clob = Clob(transport=fake_transport)
        self.data = Data(transport=fake_transport)

    def test_gamma_lists_markets(self):
        markets = self.gamma.markets(limit=3)
        self.assertEqual(len(markets), 3)
        self.assertTrue(all(m.condition_id for m in markets))

    def test_gamma_resolves_a_slug(self):
        m = self.gamma.market_by_slug("fed-cut-september")
        self.assertIn("Fed", m.question)

    def test_gamma_missing_slug_raises_lookup_error(self):
        with self.assertRaises(LookupError):
            self.gamma.market_by_slug("no-such-market")

    def test_gamma_search_returns_both_kinds(self):
        found = self.gamma.search("fed")
        self.assertTrue(found["events"])
        self.assertTrue(found["markets"])

    def test_gamma_unwraps_a_data_envelope(self):
        wrapped = Gamma(transport=json_response({"data": [{"id": "7", "question": "Q"}]}))
        self.assertEqual(wrapped.markets()[0].id, "7")

    def test_clob_quote_comes_from_one_book(self):
        q = self.clob.quote("1001")
        self.assertAlmostEqual(q["mid"], 0.62)
        self.assertLess(q["bid"], q["ask"])
        self.assertGreater(q["ask_depth"], 0)

    def test_clob_history_is_parsed_into_points(self):
        rows = self.clob.history("1001")
        self.assertEqual(len(rows), 12)
        self.assertEqual(set(rows[0]), {"t", "p"})

    def test_clob_markets_treats_the_end_cursor_as_none(self):
        client = Clob(transport=json_response({"data": [], "next_cursor": E.END_CURSOR}))
        _, cursor = client.markets()
        self.assertIsNone(cursor)

    def test_clob_markets_always_sends_a_start_cursor(self):
        """Omitting next_cursor is not the same request as starting at zero."""
        seen = []

        def transport(method, url, headers, body):
            seen.append(url)
            return 200, {}, b'{"data": [], "next_cursor": "LTE="}'

        Clob(transport=transport).markets()
        self.assertIn(f"next_cursor={E.FIRST_CURSOR.replace('=', '%3D')}", seen[0])

    def test_clob_markets_honours_an_explicit_cursor(self):
        seen = []

        def transport(method, url, headers, body):
            seen.append(url)
            return 200, {}, b'{"data": [], "next_cursor": "LTE="}'

        Clob(transport=transport).markets(next_cursor="MTAw")
        self.assertIn("next_cursor=MTAw", seen[0])

    def test_last_trade_price_is_read_from_the_price_field(self):
        client = Clob(transport=json_response({"price": "0.57"}))
        self.assertEqual(client.last_trade_price("1001"), 0.57)

    def test_tick_size_accepts_either_field_name(self):
        self.assertEqual(
            Clob(transport=json_response({"minimum_tick_size": "0.01"})).tick_size("1"),
            0.01)

    def test_data_positions_and_value(self):
        positions = self.data.positions("0x" + "1" * 40)
        self.assertEqual(positions[0].outcome, "Yes")
        self.assertEqual(self.data.value("0x" + "1" * 40), 310.0)


class TestEndpointCatalog(unittest.TestCase):
    def test_names_are_unique(self):
        names = [e.name for e in E.CATALOG]
        self.assertEqual(len(names), len(set(names)))

    def test_every_endpoint_points_at_a_known_service(self):
        for e in E.CATALOG:
            self.assertIn(e.service, E.SERVICES, e.name)

    def test_probeable_endpoints_need_no_user_supplied_id(self):
        """`doctor` must never probe a path it has to invent an id for."""
        for e in E.probeable():
            self.assertIsNone(e.needs, e.name)
            self.assertNotIn("{", e.path, e.name)

    def test_confidence_is_declared_honestly(self):
        levels = {"recall", "documented", "client", "verified"}
        for e in E.CATALOG:
            self.assertIn(e.confidence, levels, e.name)

    def test_prices_history_is_not_credited_to_the_official_client(self):
        """It is absent from py-clob-client, so it must not claim otherwise."""
        self.assertEqual(E.BY_NAME["clob.prices_history"].confidence, "recall")

    def test_paginated_probes_start_at_the_first_cursor(self):
        for name in ("clob.markets", "clob.simplified_markets",
                     "clob.sampling_markets"):
            self.assertEqual(E.BY_NAME[name].probe, {"next_cursor": E.FIRST_CURSOR})

    def test_url_building(self):
        self.assertEqual(
            E.BY_NAME["gamma.market"].url(market_id=5),
            "https://gamma-api.polymarket.com/markets/5")


class StoreBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        # Never let a test touch the real database.
        os.environ["POLYMKT_DB"] = str(Path(self.tmp.name) / "t.db")
        self.conn = S.connect()

    def tearDown(self):
        self.conn.close()
        os.environ.pop("POLYMKT_DB", None)
        self.tmp.cleanup()


class TestStore(StoreBase):
    def test_db_path_follows_the_env_var(self):
        self.assertTrue(str(S.db_path()).startswith(self.tmp.name))

    def test_watch_add_is_idempotent_and_updates_metadata(self):
        S.watch_add(self.conn, "1001", question="Old", outcome="Yes")
        S.watch_add(self.conn, "1001", question="New", outcome="Yes")
        rows = S.watch_list(self.conn)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["question"], "New")

    def test_watch_remove_reports_whether_it_did_anything(self):
        S.watch_add(self.conn, "1001")
        self.assertTrue(S.watch_remove(self.conn, "1001"))
        self.assertFalse(S.watch_remove(self.conn, "1001"))

    def test_quotes_are_append_only(self):
        S.watch_add(self.conn, "1001", outcome="Yes")
        for mid in (0.41, 0.52, 0.58):
            S.record_quote(self.conn, {"token_id": "1001", "mid": mid})
        count = self.conn.execute("SELECT COUNT(*) c FROM quotes").fetchone()["c"]
        self.assertEqual(count, 3, "a new snapshot is a new fact, not an update")
        self.assertEqual(S.latest_quote(self.conn, "1001")["mid"], 0.58)

    def test_moves_reports_change_and_sample_size(self):
        S.watch_add(self.conn, "1001", outcome="Yes", question="Q")
        S.record_quote(self.conn, {"token_id": "1001", "mid": 0.41,
                                   "captured_at": "2026-08-20T09:00:00+00:00"})
        S.record_quote(self.conn, {"token_id": "1001", "mid": 0.58,
                                   "captured_at": "2026-08-24T09:00:00+00:00"})
        row = S.moves(self.conn, days=30)[0]
        self.assertAlmostEqual(row["change_pp"], 17.0)
        self.assertEqual(row["samples"], 2)

    def test_moves_excludes_snapshots_outside_the_window(self):
        S.watch_add(self.conn, "1001", outcome="Yes")
        S.record_quote(self.conn, {"token_id": "1001", "mid": 0.10,
                                   "captured_at": "2020-01-01T00:00:00+00:00"})
        S.record_quote(self.conn, {"token_id": "1001", "mid": 0.60})
        row = S.moves(self.conn, days=7)[0]
        self.assertEqual(row["samples"], 1)
        self.assertAlmostEqual(row["change_pp"], 0.0)

    def test_a_watched_token_with_no_snapshots_is_reported_not_dropped(self):
        S.watch_add(self.conn, "1001", outcome="Yes")
        row = S.moves(self.conn, days=7)[0]
        self.assertEqual(row["samples"], 0)
        self.assertIsNone(row["change_pp"])

    def test_market_cache_expires(self):
        market = Gamma(transport=fake_transport).market_by_slug("fed-cut-september")
        S.cache_market(self.conn, market)
        self.assertIsNotNone(S.cached_market(self.conn, "fed-cut-september"))
        self.conn.execute("UPDATE markets SET fetched_at = '2020-01-01T00:00:00+00:00'")
        self.assertIsNone(S.cached_market(self.conn, "fed-cut-september"))


class TestConfig(unittest.TestCase):
    def tearDown(self):
        for name in ("POLYMKT_ADDRESS", "POLYMKT_API_KEY", "POLYMKT_API_SECRET",
                     "POLYMKT_API_PASSPHRASE"):
            os.environ.pop(name, None)

    def test_address_validation(self):
        self.assertTrue(C.is_address("0x" + "a" * 40))
        self.assertFalse(C.is_address("0xnope"))
        self.assertFalse(C.is_address("a" * 42))

    def test_bad_address_in_env_is_ignored_not_trusted(self):
        os.environ["POLYMKT_ADDRESS"] = "definitely-not-an-address"
        self.assertIsNone(C.address())

    def test_partial_credentials_are_treated_as_absent(self):
        os.environ["POLYMKT_API_KEY"] = "00000000-0000-4000-8000-000000000000"
        self.assertIsNone(C.api_credentials())
        self.assertIn("incomplete", C.credential_status())

    def test_status_line_never_prints_a_secret(self):
        key = "00000000-0000-4000-8000-000000000000"
        os.environ["POLYMKT_API_KEY"] = key
        os.environ["POLYMKT_API_SECRET"] = "s3cret-value-here"
        os.environ["POLYMKT_API_PASSPHRASE"] = "pass-value-here"
        status = C.credential_status()
        self.assertNotIn("s3cret-value-here", status)
        self.assertNotIn("pass-value-here", status)
        self.assertNotIn(key, status, "the full key must never be printed")
        self.assertIn("…", status, "but enough to identify which key is loaded")


class TestCli(StoreBase):
    """Smoke tests: every command runs offline and returns a sane exit code."""

    def run_cli(self, *argv):
        return main(list(argv))

    def test_demo_runs_end_to_end(self):
        self.assertEqual(self.run_cli("demo"), 0)

    def test_offline_commands_succeed(self):
        for argv in (("--offline", "markets", "--limit", "2"),
                     ("--offline", "events"),
                     ("--offline", "search", "fed"),
                     ("--offline", "market", "fed-cut-september", "--live"),
                     ("--offline", "book", "1001"),
                     ("--offline", "history", "1001"),
                     ("--offline", "doctor"),
                     ("endpoints",),
                     ("whoami",)):
            with self.subTest(argv=argv):
                self.assertEqual(self.run_cli(*argv), 0)

    def test_watch_snap_moves_round_trip(self):
        self.assertEqual(self.run_cli("--offline", "watch", "add",
                                      "fed-cut-september", "--outcome", "Yes"), 0)
        self.assertEqual(self.run_cli("--offline", "snap"), 0)
        self.assertEqual(self.run_cli("--offline", "moves"), 0)
        self.assertEqual(len(S.watch_list(self.conn)), 1)

    def test_watch_add_with_an_unknown_outcome_fails_loudly(self):
        self.assertEqual(self.run_cli("--offline", "watch", "add",
                                      "fed-cut-september", "--outcome", "Perhaps"), 1)

    def test_snap_with_an_empty_watchlist_is_an_error_not_a_silent_success(self):
        self.assertEqual(self.run_cli("--offline", "snap"), 1)

    def test_unknown_market_exits_nonzero(self):
        self.assertEqual(self.run_cli("--offline", "market", "no-such-slug"), 1)

    def test_positions_without_an_address_or_env_var_fails(self):
        os.environ.pop("POLYMKT_ADDRESS", None)
        self.assertEqual(self.run_cli("--offline", "positions"), 1)

    def test_positions_uses_the_configured_address(self):
        os.environ["POLYMKT_ADDRESS"] = "0x" + "a" * 40
        try:
            self.assertEqual(self.run_cli("--offline", "positions"), 0)
        finally:
            os.environ.pop("POLYMKT_ADDRESS", None)

    def test_a_network_failure_exits_two_not_a_traceback(self):
        def dead(method, url, headers, body):
            raise TransportError("blocked by egress proxy")

        with mock.patch("polymkt.cli.Gamma",
                        lambda **kw: Gamma(transport=dead)):
            self.assertEqual(self.run_cli("markets"), 2)


if __name__ == "__main__":
    unittest.main()
