"""Read-side: turn the ledger into decisions.

Design note: view counts are power-law distributed. One viral hit will
drag any mean upward and make a dead format look alive. Everything here
ranks on MEDIAN and reports the hit rate separately, so a single lucky
video can never masquerade as a repeatable pattern.
"""

from __future__ import annotations

import sqlite3
import statistics
from datetime import datetime, timedelta, timezone

# Below this many samples, a difference in medians is noise, not signal.
MIN_SAMPLE = 3

# Latest snapshot per post, resolving ties deterministically by id.
LATEST_METRICS = """
SELECT m.* FROM metrics m
WHERE m.id = (
    SELECT m2.id FROM metrics m2
    WHERE m2.post_id = m.post_id
    ORDER BY m2.captured_at DESC, m2.id DESC
    LIMIT 1
)
"""


def _cutoff(days: int | None) -> str:
    if not days:
        return "0000-01-01T00:00:00+00:00"
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")


def content_rows(conn: sqlite3.Connection, days: int | None = None) -> list[dict]:
    """One row per piece of content with its totals rolled up across platforms."""
    since = _cutoff(days)
    sql = f"""
    WITH latest AS ({LATEST_METRICS})
    SELECT
        c.id, c.slug, c.title, c.format, c.topic, c.hook_type, c.series,
        c.produced_at, c.cost_usd, c.minutes, c.pipeline,
        COUNT(DISTINCT p.id)                        AS platforms,
        COALESCE(SUM(l.views), 0)                   AS views,
        COALESCE(SUM(l.likes), 0)                   AS likes,
        COALESCE(SUM(l.comments), 0)                AS comments,
        COALESCE(SUM(l.shares), 0)                  AS shares,
        COALESCE(SUM(l.followers_gained), 0)        AS followers,
        COALESCE(SUM(l.clicks), 0)                  AS clicks,
        COALESCE((SELECT SUM(r.amount_usd) FROM revenue r
                  WHERE r.content_id = c.id), 0)    AS revenue
    FROM content c
    LEFT JOIN posts p   ON p.content_id = c.id
    LEFT JOIN latest l  ON l.post_id = p.id
    WHERE c.produced_at >= ?
    GROUP BY c.id
    ORDER BY c.produced_at DESC
    """
    return [dict(r) for r in conn.execute(sql, (since,))]


def by_dimension(
    conn: sqlite3.Connection, dimension: str, days: int | None = None
) -> list[dict]:
    """Rank topics / hooks / formats / series by median reach.

    Returns entries sorted best-first, each carrying enough context to
    judge whether the ranking is trustworthy.
    """
    allowed = {"topic", "hook_type", "format", "series", "pipeline"}
    if dimension not in allowed:
        raise ValueError(f"dimension must be one of {sorted(allowed)}")

    buckets: dict[str, list[dict]] = {}
    for row in content_rows(conn, days):
        key = row.get(dimension) or "(unset)"
        buckets.setdefault(key, []).append(row)

    out = []
    for key, rows in buckets.items():
        views = sorted(r["views"] for r in rows)
        revenue = sum(r["revenue"] for r in rows)
        cost = sum(r["cost_usd"] for r in rows)
        minutes = sum(r["minutes"] for r in rows)
        median = statistics.median(views) if views else 0
        # A "hit" is 3x the median of everything you've made — the bar
        # that actually distinguishes a winner from a normal upload.
        out.append({
            dimension: key,
            "n": len(rows),
            "median_views": median,
            "mean_views": statistics.mean(views) if views else 0,
            "best_views": max(views) if views else 0,
            "total_views": sum(views),
            "revenue": revenue,
            "cost": cost,
            "minutes": minutes,
            "revenue_per_hour": (revenue / (minutes / 60)) if minutes else 0.0,
            "roi": ((revenue - cost) / cost) if cost > 0 else None,
            "confident": len(rows) >= MIN_SAMPLE,
        })
    out.sort(key=lambda r: (r["confident"], r["median_views"]), reverse=True)
    return out


def platform_efficiency(conn: sqlite3.Connection, days: int | None = None) -> list[dict]:
    """Which platforms are worth the upload effort."""
    since = _cutoff(days)
    sql = f"""
    WITH latest AS ({LATEST_METRICS})
    SELECT
        p.platform,
        COUNT(DISTINCT p.id)                 AS posts,
        COALESCE(SUM(l.views), 0)            AS views,
        COALESCE(SUM(l.likes + l.comments + l.shares), 0) AS engagements,
        COALESCE(SUM(l.followers_gained), 0) AS followers,
        COALESCE(SUM(l.clicks), 0)           AS clicks
    FROM posts p
    LEFT JOIN latest l ON l.post_id = p.id
    WHERE p.published_at >= ?
    GROUP BY p.platform
    """
    rows = [dict(r) for r in conn.execute(sql, (since,))]

    rev_by_platform = {
        r["platform"]: r["amt"]
        for r in conn.execute(
            "SELECT platform, SUM(amount_usd) AS amt FROM revenue "
            "WHERE occurred_at >= ? AND platform IS NOT NULL GROUP BY platform",
            (since,),
        )
    }
    for r in rows:
        views = r["views"]
        r["revenue"] = rev_by_platform.get(r["platform"], 0.0)
        r["views_per_post"] = views / r["posts"] if r["posts"] else 0
        r["engagement_rate"] = (r["engagements"] / views) if views else 0.0
        r["ctr"] = (r["clicks"] / views) if views else 0.0
        # RPM = dollars per 1,000 views. The number that decides whether
        # ad revenue is a business or a rounding error.
        r["rpm"] = (r["revenue"] / views * 1000) if views else 0.0
    rows.sort(key=lambda r: r["revenue"], reverse=True)
    return rows


def pnl(conn: sqlite3.Connection, days: int | None = 30) -> dict:
    """Did this make money over the window, and from where."""
    since = _cutoff(days)
    streams = {
        r["stream"]: r["amt"]
        for r in conn.execute(
            "SELECT stream, SUM(amount_usd) AS amt FROM revenue "
            "WHERE occurred_at >= ? GROUP BY stream ORDER BY amt DESC",
            (since,),
        )
    }
    overhead = {
        r["category"]: r["amt"]
        for r in conn.execute(
            "SELECT category, SUM(amount_usd) AS amt FROM costs "
            "WHERE occurred_at >= ? GROUP BY category",
            (since,),
        )
    }
    prod = conn.execute(
        "SELECT COALESCE(SUM(cost_usd),0) AS c, COALESCE(SUM(minutes),0) AS m, "
        "COUNT(*) AS n FROM content WHERE produced_at >= ?",
        (since,),
    ).fetchone()

    revenue = sum(streams.values())
    cost = sum(overhead.values()) + prod["c"]
    hours = prod["m"] / 60
    return {
        "days": days,
        "revenue": revenue,
        "revenue_by_stream": streams,
        "cost": cost,
        "cost_by_category": overhead,
        "production_cost": prod["c"],
        "production_minutes": prod["m"],
        "content_made": prod["n"],
        "profit": revenue - cost,
        "hours": hours,
        "effective_hourly": ((revenue - cost) / hours) if hours else 0.0,
        "cost_per_content": (prod["c"] / prod["n"]) if prod["n"] else 0.0,
    }


def top_and_bottom(conn: sqlite3.Connection, days: int | None = None, k: int = 5) -> dict:
    rows = [r for r in content_rows(conn, days) if r["platforms"]]
    rows.sort(key=lambda r: r["views"], reverse=True)
    return {"top": rows[:k], "bottom": rows[-k:][::-1] if len(rows) > k else []}


def recommendations(conn: sqlite3.Connection, days: int | None = 90) -> list[str]:
    """Plain-language next actions derived only from what the data supports."""
    recs: list[str] = []
    rows = content_rows(conn, days)
    posted = [r for r in rows if r["platforms"]]

    if len(posted) < MIN_SAMPLE:
        recs.append(
            f"Only {len(posted)} published pieces logged. Volume is the prerequisite for "
            "signal — get to ~20 before trusting any ranking here."
        )
        return recs

    for dim, label in (("topic", "topic"), ("hook_type", "hook")):
        ranked = [r for r in by_dimension(conn, dim, days) if r["confident"]
                  and r[dim] != "(unset)"]
        if len(ranked) >= 2:
            best, worst = ranked[0], ranked[-1]
            if best["median_views"] > worst["median_views"] * 1.5:
                recs.append(
                    f"Make more {label} '{best[dim]}' (median {best['median_views']:,.0f} views, "
                    f"n={best['n']}) and less '{worst[dim]}' "
                    f"(median {worst['median_views']:,.0f}, n={worst['n']})."
                )

    plats = [p for p in platform_efficiency(conn, days) if p["posts"] >= MIN_SAMPLE]
    if len(plats) >= 2:
        by_reach = sorted(plats, key=lambda p: p["views_per_post"], reverse=True)
        top, bottom = by_reach[0], by_reach[-1]
        if bottom["views_per_post"] * 4 < top["views_per_post"]:
            recs.append(
                f"{top['platform']} returns {top['views_per_post']:,.0f} views/post vs "
                f"{bottom['platform']} at {bottom['views_per_post']:,.0f}. Cut or automate "
                f"{bottom['platform']} uploads and reinvest that time."
            )

    money = pnl(conn, days)
    if money["revenue"] == 0:
        recs.append(
            "No revenue recorded yet. Reach without a monetization layer earns nothing — "
            "attach the first stream (see docs/PLAYBOOK.md, Phase 1)."
        )
    elif money["profit"] < 0:
        recs.append(
            f"Running at a loss of ${abs(money['profit']):,.2f} over {days}d. "
            f"Production is ${money['cost_per_content']:,.2f}/piece — cut cost per piece "
            "or raise revenue per view before scaling volume."
        )

    total_clicks = sum(r["clicks"] for r in posted)
    total_views = sum(r["views"] for r in posted)
    if total_views > 10_000 and total_clicks == 0:
        recs.append(
            f"{total_views:,} views and zero logged clicks. The bridge from audience to "
            "money is missing — every post needs one destination worth clicking."
        )
    return recs
