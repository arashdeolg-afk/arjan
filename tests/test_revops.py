"""Tests. Run: python3 -m unittest discover -s tests -v"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from revops import analytics as A            # noqa: E402
from revops import ledger as L               # noqa: E402
from revops import monetization as M         # noqa: E402
from revops.db import connect                # noqa: E402


class Base(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["REVOPS_DB"] = str(Path(self.tmp.name) / "t.db")
        self.conn = connect()

    def tearDown(self) -> None:
        self.conn.close()
        os.environ.pop("REVOPS_DB", None)
        self.tmp.cleanup()

    def make(self, title, views=0, platform="tiktok", **kw):
        cid = L.add_content(self.conn, title, **kw)
        L.add_post(self.conn, cid, platform)
        L.add_metrics(self.conn, cid, platform, views=views)
        return cid


class TestLedger(Base):
    def test_slug_collision_gets_suffix(self):
        L.add_content(self.conn, "Same Title")
        L.add_content(self.conn, "Same Title")
        slugs = [r[0] for r in self.conn.execute("SELECT slug FROM content ORDER BY id")]
        self.assertEqual(slugs, ["same-title", "same-title-2"])

    def test_reposting_same_platform_upserts(self):
        cid = L.add_content(self.conn, "x")
        a = L.add_post(self.conn, cid, "tiktok", url="one")
        b = L.add_post(self.conn, cid, "tiktok", url="two")
        self.assertEqual(a, b)
        n = self.conn.execute("SELECT COUNT(*) FROM posts").fetchone()[0]
        self.assertEqual(n, 1)

    def test_content_resolvable_by_slug_or_id(self):
        cid = L.add_content(self.conn, "Findable Thing")
        self.assertEqual(L.resolve_content(self.conn, cid), cid)
        self.assertEqual(L.resolve_content(self.conn, "findable-thing"), cid)
        with self.assertRaises(LookupError):
            L.resolve_content(self.conn, "nope")

    def test_metrics_require_a_post_first(self):
        cid = L.add_content(self.conn, "unposted")
        with self.assertRaises(LookupError):
            L.add_metrics(self.conn, cid, "tiktok", views=5)

    def test_rejects_bad_enums(self):
        with self.assertRaises(ValueError):
            L.add_content(self.conn, "x", fmt="hologram")
        with self.assertRaises(ValueError):
            L.add_cost(self.conn, "bribes", 10)


class TestAnalytics(Base):
    def test_uses_latest_metrics_snapshot_not_the_sum(self):
        """Snapshots are cumulative totals. Summing them would double-count."""
        cid = self.make("growing", views=100)
        L.add_metrics(self.conn, cid, "tiktok", views=500,
                      captured_at="2099-01-01T00:00:00+00:00")
        rows = A.content_rows(self.conn)
        self.assertEqual(rows[0]["views"], 500)

    def test_ranking_resists_a_single_viral_outlier(self):
        """The core guarantee: one breakout must not promote a losing format.

        'lucky' has the biggest single video and the higher mean; 'steady'
        wins on median. Median must decide the ranking.
        """
        for v in (100, 100, 100, 900_000):
            self.make(f"lucky-{v}-{id(v)}", views=v, topic="lucky")
        for v in (5_000, 5_500, 6_000, 5_200):
            self.make(f"steady-{v}", views=v, topic="steady")

        ranked = A.by_dimension(self.conn, "topic")
        by_key = {r["topic"]: r for r in ranked}
        self.assertGreater(by_key["lucky"]["mean_views"], by_key["steady"]["mean_views"])
        self.assertGreater(by_key["steady"]["median_views"], by_key["lucky"]["median_views"])
        self.assertEqual(ranked[0]["topic"], "steady")

    def test_low_sample_marked_unconfident(self):
        self.make("only-one", views=10, topic="thin")
        for i in range(A.MIN_SAMPLE):
            self.make(f"plenty-{i}", views=10, topic="thick")
        flags = {r["topic"]: r["confident"] for r in A.by_dimension(self.conn, "topic")}
        self.assertFalse(flags["thin"])
        self.assertTrue(flags["thick"])

    def test_confident_rows_outrank_unconfident_ones(self):
        self.make("fluke", views=10_000_000, topic="thin")
        for i in range(A.MIN_SAMPLE):
            self.make(f"real-{i}", views=1_000, topic="thick")
        self.assertEqual(A.by_dimension(self.conn, "topic")[0]["topic"], "thick")

    def test_pnl_nets_production_and_overhead(self):
        cid = L.add_content(self.conn, "p", cost_usd=10.0, minutes=60.0)
        L.add_revenue(self.conn, "client_ugc", 300.0, content_ref=cid)
        L.add_cost(self.conn, "tools", 40.0)
        p = A.pnl(self.conn, 30)
        self.assertAlmostEqual(p["revenue"], 300.0)
        self.assertAlmostEqual(p["cost"], 50.0)
        self.assertAlmostEqual(p["profit"], 250.0)
        self.assertAlmostEqual(p["effective_hourly"], 250.0)

    def test_platform_rpm_and_ctr(self):
        cid = L.add_content(self.conn, "m")
        L.add_post(self.conn, cid, "tiktok")
        L.add_metrics(self.conn, cid, "tiktok", views=10_000, clicks=50)
        L.add_revenue(self.conn, "affiliate", 20.0, platform="tiktok")
        r = A.platform_efficiency(self.conn)[0]
        self.assertAlmostEqual(r["rpm"], 2.0)       # $20 / 10k views * 1000
        self.assertAlmostEqual(r["ctr"], 0.005)

    def test_empty_db_does_not_explode(self):
        self.assertEqual(A.content_rows(self.conn), [])
        self.assertEqual(A.pnl(self.conn, 30)["revenue"], 0)
        self.assertEqual(A.platform_efficiency(self.conn), [])
        self.assertIn("Only 0 published", A.recommendations(self.conn)[0])

    def test_recommends_monetizing_unmonetized_reach(self):
        for i in range(5):
            self.make(f"v{i}", views=50_000)
        recs = " ".join(A.recommendations(self.conn))
        self.assertIn("No revenue recorded", recs)


class TestMonetization(Base):
    def test_affiliate_unlocks_immediately_gated_streams_do_not(self):
        self.make("first", views=10)
        state = {s["key"]: s for s in M.readiness(self.conn)}
        self.assertTrue(state["affiliate"]["ready"])
        self.assertFalse(state["merch"]["ready"])
        self.assertTrue(state["merch"]["blockers"])

    def test_client_work_unlocks_on_portfolio_not_followers(self):
        for i in range(10):
            self.make(f"piece-{i}", views=5)
        state = {s["key"]: s for s in M.readiness(self.conn)}
        self.assertTrue(state["client_ugc"]["ready"],
                        "client work should gate on portfolio size only")

    def test_active_streams_reported_with_totals(self):
        self.make("c", views=1)
        L.add_revenue(self.conn, "affiliate", 12.50)
        aff = {s["key"]: s for s in M.readiness(self.conn)}["affiliate"]
        self.assertTrue(aff["active"])
        self.assertAlmostEqual(aff["earned_to_date"], 12.50)

    def test_unlocked_but_unused_sorts_before_active(self):
        for i in range(12):
            self.make(f"p{i}", views=100)
        L.add_revenue(self.conn, "affiliate", 5.0)
        order = [s["key"] for s in M.readiness(self.conn)]
        self.assertLess(order.index("client_ugc"), order.index("affiliate"))


class TestDemoAndDashboard(Base):
    def test_demo_seed_produces_analysable_data(self):
        from revops.demo import seed
        seed(self.conn)
        rows = A.content_rows(self.conn)
        self.assertGreater(len(rows), 20)
        self.assertGreater(A.pnl(self.conn, 90)["revenue"], 0)
        self.assertTrue(A.recommendations(self.conn, 90))

    def test_dashboard_renders_valid_standalone_html(self):
        from revops.dashboard import render
        from revops.demo import seed
        seed(self.conn)
        out = render(self.conn, days=90, path=str(Path(self.tmp.name) / "d.html"))
        doc = out.read_text()
        self.assertTrue(doc.startswith("<!doctype html>"))
        self.assertIn("</html>", doc)
        self.assertNotIn("http://", doc)      # must be self-contained
        self.assertNotIn("<script", doc)

    def test_dashboard_handles_empty_database(self):
        from revops.dashboard import render
        out = render(self.conn, days=30, path=str(Path(self.tmp.name) / "e.html"))
        self.assertIn("No revenue recorded yet", out.read_text())


if __name__ == "__main__":
    unittest.main()


class TestSprint(Base):
    def setUp(self):
        super().setUp()
        from revops import sprint as S
        self.S = S

    def add(self, name, **kw):
        return self.S.add_lead(self.conn, name, **kw)

    def test_stage_never_regresses(self):
        """A lead that replied must keep counting as replied forever.

        Otherwise re-logging an earlier step would quietly delete evidence
        from the funnel and inflate the apparent conversion rate.
        """
        lid = self.add("A")
        self.S.set_stage(self.conn, lid, "replied")
        self.S.set_stage(self.conn, lid, "contacted")
        row = self.conn.execute("SELECT stage FROM leads WHERE id=?", (lid,)).fetchone()
        self.assertEqual(row["stage"], "replied")

    def test_lost_leads_still_count_toward_earlier_stages(self):
        lid = self.add("B")
        self.S.set_stage(self.conn, lid, "replied")
        self.S.set_stage(self.conn, lid, "lost")
        counts = {f["stage"]: f["count"] for f in self.S.funnel(self.conn)}
        self.assertEqual(counts["contacted"], 1)
        self.assertEqual(counts["replied"], 1)
        self.assertEqual(counts["won"], 0)

    def test_winning_records_revenue_automatically(self):
        lid = self.add("C")
        self.S.set_stage(self.conn, lid, "won", amount=250.0)
        total = self.conn.execute(
            "SELECT SUM(amount_usd) AS s FROM revenue WHERE stream='client_ugc'"
        ).fetchone()["s"]
        self.assertAlmostEqual(total, 250.0)
        self.assertAlmostEqual(A.pnl(self.conn, 30)["revenue"], 250.0)

    def test_rates_lean_on_prior_until_enough_data(self):
        """One lucky close must not read as a 100% conversion rate."""
        lid = self.add("D")
        self.S.set_stage(self.conn, lid, "won", amount=200.0)
        r = self.S.rates(self.conn)[("contacted", "replied")]
        self.assertFalse(r["trusted"])
        self.assertLess(r["rate"], 0.6, "single observation should be pulled toward prior")

    def test_rates_shift_toward_observed_with_volume(self):
        for i in range(40):
            lid = self.add(f"L{i}")
            self.S.set_stage(self.conn, lid, "contacted")
            if i % 2 == 0:
                self.S.set_stage(self.conn, lid, "replied")
        r = self.S.rates(self.conn)[("contacted", "replied")]
        self.assertTrue(r["trusted"])
        self.assertGreater(r["rate"], 0.40)   # observed 50%, prior 25%

    def test_status_computes_required_daily_volume(self):
        self.S.start_sprint(self.conn, goal_usd=600, price_usd=200, days=7)
        st = self.S.status(self.conn)
        self.assertAlmostEqual(st["wins_needed"], 3.0)
        self.assertGreater(st["contacts_needed"], 20)
        self.assertGreater(st["per_day"], 1)
        self.assertAlmostEqual(st["remaining"], 600.0)

    def test_status_tracks_progress_against_goal(self):
        self.S.start_sprint(self.conn, goal_usd=600, price_usd=200)
        lid = self.add("Paying")
        self.S.set_stage(self.conn, lid, "won", amount=250.0)
        st = self.S.status(self.conn)
        self.assertAlmostEqual(st["earned"], 250.0)
        self.assertAlmostEqual(st["remaining"], 350.0)

    def test_followups_exclude_closed_and_over_touched(self):
        old = "2000-01-01T00:00:00+00:00"
        live = self.add("Live")
        self.S.set_stage(self.conn, live, "contacted")
        won = self.add("Won")
        self.S.set_stage(self.conn, won, "won", amount=100.0)
        for lid in (live, won):
            self.conn.execute("UPDATE leads SET last_touch_at=? WHERE id=?", (old, lid))
        self.conn.commit()
        names = [r["name"] for r in self.S.followups(self.conn)]
        self.assertIn("Live", names)
        self.assertNotIn("Won", names)

    def test_followups_stop_after_three_attempts(self):
        lid = self.add("Chased")
        self.S.set_stage(self.conn, lid, "contacted")
        for _ in range(3):
            self.S.log_touch(self.conn, lid, "followup")
        self.conn.execute("UPDATE leads SET last_touch_at=? WHERE id=?",
                          ("2000-01-01T00:00:00+00:00", lid))
        self.conn.commit()
        self.assertEqual(self.S.followups(self.conn), [])

    def test_segment_breakdown_ranks_by_revenue(self):
        good = self.add("G", segment="indie-game")
        self.S.set_stage(self.conn, good, "won", amount=300.0)
        bad = self.add("B2", segment="vtuber")
        self.S.set_stage(self.conn, bad, "contacted")
        self.assertEqual(self.S.by_segment(self.conn)[0]["segment"], "indie-game")

    def test_resolve_lead_by_name_or_handle(self):
        lid = self.add("Studio X", handle="@studiox")
        self.assertEqual(self.S.resolve_lead(self.conn, "Studio X"), lid)
        self.assertEqual(self.S.resolve_lead(self.conn, "@studiox"), lid)
        with self.assertRaises(LookupError):
            self.S.resolve_lead(self.conn, "@nobody")

    def test_rejects_unknown_stage(self):
        lid = self.add("E")
        with self.assertRaises(ValueError):
            self.S.set_stage(self.conn, lid, "vibing")
