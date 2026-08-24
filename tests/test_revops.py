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
