"""SQLite storage. Stdlib only — no install step, no service to run."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

DEFAULT_DB = Path(__file__).resolve().parents[2] / "data" / "revops.db"

SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- A creative asset. One row per thing you made, regardless of how
-- many platforms it later gets posted to.
CREATE TABLE IF NOT EXISTS content (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    slug              TEXT NOT NULL UNIQUE,
    title             TEXT NOT NULL,
    format            TEXT NOT NULL DEFAULT 'short',   -- short | long | image | carousel
    topic             TEXT,                            -- niche/subject, e.g. 'anime-comedy'
    hook_type         TEXT,                            -- opening device, e.g. 'cold-open-punchline'
    series            TEXT,                            -- recurring franchise this belongs to
    duration_s        REAL,
    produced_at       TEXT NOT NULL,                   -- ISO8601
    -- What it cost you to make. Both matter: credits are cash,
    -- minutes are the scarcer resource at 1-2 hrs/day.
    cost_usd          REAL NOT NULL DEFAULT 0.0,
    minutes           REAL NOT NULL DEFAULT 0.0,
    pipeline          TEXT,                            -- which skill/tool chain produced it
    notes             TEXT
);

-- One publication of a piece of content to one platform.
CREATE TABLE IF NOT EXISTS posts (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    content_id        INTEGER NOT NULL REFERENCES content(id) ON DELETE CASCADE,
    platform          TEXT NOT NULL,                   -- youtube | tiktok | instagram | x | reddit | ...
    url               TEXT,
    external_id       TEXT,
    published_at      TEXT NOT NULL,
    UNIQUE (content_id, platform)
);

-- Performance snapshots. Append-only; never overwrite history,
-- because velocity (views in first 24h) predicts more than totals.
CREATE TABLE IF NOT EXISTS metrics (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id           INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
    captured_at       TEXT NOT NULL,
    views             INTEGER NOT NULL DEFAULT 0,
    likes             INTEGER NOT NULL DEFAULT 0,
    comments          INTEGER NOT NULL DEFAULT 0,
    shares            INTEGER NOT NULL DEFAULT 0,
    followers_gained  INTEGER NOT NULL DEFAULT 0,
    watch_time_s      REAL NOT NULL DEFAULT 0.0,
    clicks            INTEGER NOT NULL DEFAULT 0       -- link/bio clicks: the monetization bridge
);

-- Money in. Attribute to content/platform when you can; leave null when you can't.
CREATE TABLE IF NOT EXISTS revenue (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    stream            TEXT NOT NULL,                   -- see monetization.STREAMS
    amount_usd        REAL NOT NULL,
    occurred_at       TEXT NOT NULL,
    platform          TEXT,
    content_id        INTEGER REFERENCES content(id) ON DELETE SET NULL,
    notes             TEXT
);

-- Money out that isn't tied to one video (subs, ads, tools).
-- Per-video cost lives on the content row.
CREATE TABLE IF NOT EXISTS costs (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    category          TEXT NOT NULL,                   -- tools | ads | inventory | fees | other
    amount_usd        REAL NOT NULL,
    occurred_at       TEXT NOT NULL,
    recurring         INTEGER NOT NULL DEFAULT 0,      -- 1 = monthly subscription
    notes             TEXT
);

-- Deliberate tests, so you learn instead of just posting.
CREATE TABLE IF NOT EXISTS experiments (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    name              TEXT NOT NULL UNIQUE,
    hypothesis        TEXT NOT NULL,
    metric            TEXT NOT NULL,                   -- what decides it
    started_at        TEXT NOT NULL,
    ended_at          TEXT,
    status            TEXT NOT NULL DEFAULT 'running', -- running | won | lost | inconclusive
    result            TEXT
);

CREATE INDEX IF NOT EXISTS idx_posts_content   ON posts(content_id);
CREATE INDEX IF NOT EXISTS idx_posts_platform  ON posts(platform);
CREATE INDEX IF NOT EXISTS idx_metrics_post    ON metrics(post_id, captured_at);
CREATE INDEX IF NOT EXISTS idx_revenue_when    ON revenue(occurred_at);
CREATE INDEX IF NOT EXISTS idx_revenue_stream  ON revenue(stream);
CREATE INDEX IF NOT EXISTS idx_costs_when      ON costs(occurred_at);
"""


def db_path() -> Path:
    """Honour REVOPS_DB so tests and experiments don't touch real data."""
    env = os.environ.get("REVOPS_DB")
    return Path(env) if env else DEFAULT_DB


def connect(path: Path | str | None = None) -> sqlite3.Connection:
    target = Path(path) if path else db_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(target)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn
