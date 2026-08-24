"""Seed realistic example data so the system can be evaluated before
you have real numbers of your own.

View counts follow a power law on purpose: most posts land flat and a
few break out. Any tool that behaves sensibly on tidy uniform data and
falls apart on this shape is the wrong tool.
"""

from __future__ import annotations

import random
import sqlite3
from datetime import datetime, timedelta, timezone

from . import ledger as L

TOPICS = ["anime-comedy", "anime-comedy", "anime-comedy", "ai-tutorial", "ai-tutorial", "cat-chaos"]
HOOKS = ["cold-open-punchline", "cold-open-punchline", "question-hook", "slow-build"]
PLATFORMS = ["tiktok", "youtube", "instagram", "x"]

# Rough reach multipliers by platform, and how "hot" each hook tends to run.
PLATFORM_REACH = {"tiktok": 1.0, "youtube": 0.55, "instagram": 0.40, "x": 0.12}
HOOK_LIFT = {"cold-open-punchline": 2.4, "question-hook": 1.0, "slow-build": 0.45}
TOPIC_LIFT = {"anime-comedy": 1.6, "ai-tutorial": 0.8, "cat-chaos": 1.1}


def seed(conn: sqlite3.Connection, n: int = 34, seed_value: int = 7) -> None:
    rng = random.Random(seed_value)
    start = datetime.now(timezone.utc) - timedelta(days=60)

    conn.execute("DELETE FROM revenue")
    conn.execute("DELETE FROM costs")
    conn.execute("DELETE FROM metrics")
    conn.execute("DELETE FROM posts")
    conn.execute("DELETE FROM content")
    conn.commit()

    for i in range(n):
        made = start + timedelta(days=i * 60 / n, hours=rng.randint(0, 9))
        topic = rng.choice(TOPICS)
        hook = rng.choice(HOOKS)
        cid = L.add_content(
            conn, f"Episode {i + 1}: {topic.replace('-', ' ').title()}",
            topic=topic, hook_type=hook, series="daily-short",
            duration_s=rng.uniform(14, 45),
            cost_usd=round(rng.uniform(0.60, 2.40), 2),
            minutes=rng.uniform(18, 55),
            pipeline="gemini-anime-clip-chain",
            produced_at=made.isoformat(timespec="seconds"),
        )

        # Power law: lognormal base reach, occasional breakout.
        base = rng.lognormvariate(7.4, 1.25) * HOOK_LIFT[hook] * TOPIC_LIFT[topic]
        if rng.random() < 0.08:
            base *= rng.uniform(8, 30)

        for plat in PLATFORMS:
            if rng.random() < 0.18:
                continue  # not every piece goes everywhere
            L.add_post(conn, cid, plat, published_at=made.isoformat(timespec="seconds"))
            views = max(0, int(base * PLATFORM_REACH[plat] * rng.uniform(0.6, 1.4)))
            eng = rng.uniform(0.03, 0.11)
            clicks = int(views * rng.uniform(0.001, 0.006))
            L.add_metrics(
                conn, cid, plat,
                views=views,
                likes=int(views * eng),
                comments=int(views * eng * 0.08),
                shares=int(views * eng * 0.15),
                followers_gained=int(views * rng.uniform(0.002, 0.010)),
                clicks=clicks,
                captured_at=(made + timedelta(days=7)).isoformat(timespec="seconds"),
            )
            if clicks and rng.random() < 0.45:
                L.add_revenue(
                    conn, "affiliate", round(clicks * rng.uniform(0.04, 0.16), 2),
                    platform=plat, content_ref=cid,
                    occurred_at=(made + timedelta(days=8)).isoformat(timespec="seconds"),
                )

    # A couple of client spots — the point the docs argue for.
    for wk, amt in ((3, 300.0), (7, 750.0)):
        L.add_revenue(
            conn, "client_ugc", amt, notes="AI ad spot",
            occurred_at=(start + timedelta(weeks=wk)).isoformat(timespec="seconds"),
        )
    L.add_cost(conn, "tools", 40.0, recurring=True, notes="generation credits",
               occurred_at=(start + timedelta(days=30)).isoformat(timespec="seconds"))
    L.add_cost(conn, "ads", 60.0, notes="test spend",
               occurred_at=(start + timedelta(days=40)).isoformat(timespec="seconds"))
    conn.commit()
