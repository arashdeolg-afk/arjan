"""Write-side: record what you made, where it went, and what it earned."""

from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timezone

VALID_FORMATS = {"short", "long", "image", "carousel"}
VALID_COST_CATEGORIES = {"tools", "ads", "inventory", "fees", "other"}


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def slugify(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s or "untitled"


def _unique_slug(conn: sqlite3.Connection, base: str) -> str:
    """Titles repeat across a series; slugs must not."""
    slug, n = base, 2
    while conn.execute("SELECT 1 FROM content WHERE slug = ?", (slug,)).fetchone():
        slug = f"{base}-{n}"
        n += 1
    return slug


def add_content(
    conn: sqlite3.Connection,
    title: str,
    *,
    fmt: str = "short",
    topic: str | None = None,
    hook_type: str | None = None,
    series: str | None = None,
    duration_s: float | None = None,
    cost_usd: float = 0.0,
    minutes: float = 0.0,
    pipeline: str | None = None,
    notes: str | None = None,
    produced_at: str | None = None,
) -> int:
    if fmt not in VALID_FORMATS:
        raise ValueError(f"format must be one of {sorted(VALID_FORMATS)}, got {fmt!r}")
    slug = _unique_slug(conn, slugify(title))
    cur = conn.execute(
        """INSERT INTO content
           (slug, title, format, topic, hook_type, series, duration_s,
            produced_at, cost_usd, minutes, pipeline, notes)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (slug, title, fmt, topic, hook_type, series, duration_s,
         produced_at or now(), cost_usd, minutes, pipeline, notes),
    )
    conn.commit()
    return int(cur.lastrowid)


def resolve_content(conn: sqlite3.Connection, ref: str | int) -> int:
    """Accept an id or a slug, so the CLI stays forgiving."""
    row = conn.execute(
        "SELECT id FROM content WHERE id = ? OR slug = ?", (ref, str(ref))
    ).fetchone()
    if not row:
        raise LookupError(f"no content matching {ref!r}")
    return int(row["id"])


def add_post(
    conn: sqlite3.Connection,
    content_ref: str | int,
    platform: str,
    *,
    url: str | None = None,
    external_id: str | None = None,
    published_at: str | None = None,
) -> int:
    cid = resolve_content(conn, content_ref)
    cur = conn.execute(
        """INSERT INTO posts (content_id, platform, url, external_id, published_at)
           VALUES (?,?,?,?,?)
           ON CONFLICT(content_id, platform) DO UPDATE SET
             url = COALESCE(excluded.url, posts.url),
             external_id = COALESCE(excluded.external_id, posts.external_id)""",
        (cid, platform.lower(), url, external_id, published_at or now()),
    )
    conn.commit()
    if cur.lastrowid:
        return int(cur.lastrowid)
    row = conn.execute(
        "SELECT id FROM posts WHERE content_id = ? AND platform = ?", (cid, platform.lower())
    ).fetchone()
    return int(row["id"])


def add_metrics_for_post(
    conn: sqlite3.Connection,
    post_id: int,
    *,
    views: int = 0,
    likes: int = 0,
    comments: int = 0,
    shares: int = 0,
    followers_gained: int = 0,
    watch_time_s: float = 0.0,
    clicks: int = 0,
    captured_at: str | None = None,
    commit: bool = True,
) -> int:
    """Append a snapshot against a post that has already been resolved.

    Bulk importers hold the post id already and would otherwise pay a
    lookup — and a commit — per row. `commit=False` lets a whole export
    land as one transaction.
    """
    cur = conn.execute(
        """INSERT INTO metrics
           (post_id, captured_at, views, likes, comments, shares,
            followers_gained, watch_time_s, clicks)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (post_id, captured_at or now(), views, likes, comments, shares,
         followers_gained, watch_time_s, clicks),
    )
    if commit:
        conn.commit()
    return int(cur.lastrowid)


def add_metrics(
    conn: sqlite3.Connection,
    content_ref: str | int,
    platform: str,
    *,
    views: int = 0,
    likes: int = 0,
    comments: int = 0,
    shares: int = 0,
    followers_gained: int = 0,
    watch_time_s: float = 0.0,
    clicks: int = 0,
    captured_at: str | None = None,
) -> int:
    cid = resolve_content(conn, content_ref)
    row = conn.execute(
        "SELECT id FROM posts WHERE content_id = ? AND platform = ?", (cid, platform.lower())
    ).fetchone()
    if not row:
        raise LookupError(
            f"content {content_ref!r} was never posted to {platform!r} — run `post` first"
        )
    return add_metrics_for_post(
        conn, int(row["id"]), views=views, likes=likes, comments=comments,
        shares=shares, followers_gained=followers_gained,
        watch_time_s=watch_time_s, clicks=clicks, captured_at=captured_at,
    )


def add_revenue(
    conn: sqlite3.Connection,
    stream: str,
    amount_usd: float,
    *,
    platform: str | None = None,
    content_ref: str | int | None = None,
    occurred_at: str | None = None,
    notes: str | None = None,
) -> int:
    cid = resolve_content(conn, content_ref) if content_ref is not None else None
    cur = conn.execute(
        """INSERT INTO revenue (stream, amount_usd, occurred_at, platform, content_id, notes)
           VALUES (?,?,?,?,?,?)""",
        (stream, amount_usd, occurred_at or now(), platform, cid, notes),
    )
    conn.commit()
    return int(cur.lastrowid)


def add_cost(
    conn: sqlite3.Connection,
    category: str,
    amount_usd: float,
    *,
    recurring: bool = False,
    occurred_at: str | None = None,
    notes: str | None = None,
) -> int:
    if category not in VALID_COST_CATEGORIES:
        raise ValueError(f"category must be one of {sorted(VALID_COST_CATEGORIES)}")
    cur = conn.execute(
        """INSERT INTO costs (category, amount_usd, occurred_at, recurring, notes)
           VALUES (?,?,?,?,?)""",
        (category, amount_usd, occurred_at or now(), 1 if recurring else 0, notes),
    )
    conn.commit()
    return int(cur.lastrowid)
