"""Local storage: a watchlist, and an append-only history of quotes.

The APIs tell you where a probability *is*. They are much less generous
about where it *was* — `/prices-history` is per-token and rate-limited,
and it won't tell you what your own watchlist did overnight. So snapshots
are kept here, locally, and never overwritten. The move from 41% to 58%
is the signal; the 58% on its own is just a number.

Same conventions as the rest of this repo: SQLite, stdlib only, created
on first run, and the file is gitignored because it is your data.
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

DEFAULT_DB = Path(__file__).resolve().parents[2] / "data" / "polymkt.db"

SCHEMA = """
PRAGMA journal_mode = WAL;

-- Outcome tokens you care about. One row per token, not per market:
-- 'Yes' and 'No' have separate books and are watched separately.
CREATE TABLE IF NOT EXISTS watch (
    token_id      TEXT PRIMARY KEY,
    condition_id  TEXT,
    slug          TEXT,
    question      TEXT,
    outcome       TEXT,
    added_at      TEXT NOT NULL,
    note          TEXT
);

-- Append-only price snapshots. Never updated, never deduped: two
-- snapshots a minute apart are two facts, not a correction.
CREATE TABLE IF NOT EXISTS quotes (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    token_id     TEXT NOT NULL,
    captured_at  TEXT NOT NULL,
    bid          REAL,
    ask          REAL,
    mid          REAL,
    spread       REAL,
    bid_depth    REAL,
    ask_depth    REAL
);
CREATE INDEX IF NOT EXISTS idx_quotes_token ON quotes(token_id, captured_at);

-- Metadata cache, so discovery doesn't re-hit Gamma for a slug you
-- already resolved. Cheap to throw away: `polymkt cache --clear`.
CREATE TABLE IF NOT EXISTS markets (
    condition_id  TEXT PRIMARY KEY,
    slug          TEXT,
    question      TEXT,
    payload       TEXT NOT NULL,
    fetched_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_markets_slug ON markets(slug);
"""


def db_path() -> Path:
    return Path(os.environ.get("POLYMKT_DB", str(DEFAULT_DB)))


def connect() -> sqlite3.Connection:
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ------------------------------------------------------------- watchlist


def watch_add(conn: sqlite3.Connection, token_id: str, *, condition_id: str = "",
              slug: str = "", question: str = "", outcome: str = "",
              note: str | None = None) -> None:
    conn.execute(
        """INSERT INTO watch (token_id, condition_id, slug, question, outcome, added_at, note)
           VALUES (?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(token_id) DO UPDATE SET
               condition_id = excluded.condition_id,
               slug         = excluded.slug,
               question     = excluded.question,
               outcome      = excluded.outcome,
               note         = COALESCE(excluded.note, watch.note)""",
        (token_id, condition_id, slug, question, outcome, _now(), note),
    )
    conn.commit()


def watch_remove(conn: sqlite3.Connection, token_id: str) -> bool:
    cur = conn.execute("DELETE FROM watch WHERE token_id = ?", (token_id,))
    conn.commit()
    return cur.rowcount > 0


def watch_list(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute("SELECT * FROM watch ORDER BY added_at").fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------- quotes


def record_quote(conn: sqlite3.Connection, quote: dict) -> int:
    cur = conn.execute(
        """INSERT INTO quotes (token_id, captured_at, bid, ask, mid, spread,
                               bid_depth, ask_depth)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (quote["token_id"], quote.get("captured_at") or _now(), quote.get("bid"),
         quote.get("ask"), quote.get("mid"), quote.get("spread"),
         quote.get("bid_depth"), quote.get("ask_depth")),
    )
    conn.commit()
    return int(cur.lastrowid or 0)


def latest_quote(conn: sqlite3.Connection, token_id: str) -> dict | None:
    row = conn.execute(
        "SELECT * FROM quotes WHERE token_id = ? ORDER BY captured_at DESC, id DESC LIMIT 1",
        (token_id,),
    ).fetchone()
    return dict(row) if row else None


def moves(conn: sqlite3.Connection, days: int = 7) -> list[dict]:
    """How far each watched probability has travelled in the window.

    Reports `samples` alongside the move, because two snapshots taken a
    minute apart make a 0.0pp "move" that means nothing at all. Sorted by
    absolute change: the direction is yours to interpret, the size is not.
    """
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")
    out = []
    for w in watch_list(conn):
        rows = conn.execute(
            """SELECT captured_at, mid FROM quotes
               WHERE token_id = ? AND captured_at >= ? AND mid IS NOT NULL
               ORDER BY captured_at, id""",
            (w["token_id"], since),
        ).fetchall()
        if not rows:
            out.append({**w, "samples": 0, "first": None, "last": None, "change_pp": None})
            continue
        first, last = rows[0]["mid"], rows[-1]["mid"]
        out.append({
            **w,
            "samples": len(rows),
            "first": first,
            "last": last,
            "first_at": rows[0]["captured_at"],
            "last_at": rows[-1]["captured_at"],
            "change_pp": (last - first) * 100,
        })
    out.sort(key=lambda r: abs(r["change_pp"] or 0.0), reverse=True)
    return out


# ----------------------------------------------------------------- cache


def cache_market(conn: sqlite3.Connection, market) -> None:
    conn.execute(
        """INSERT INTO markets (condition_id, slug, question, payload, fetched_at)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(condition_id) DO UPDATE SET
               slug = excluded.slug, question = excluded.question,
               payload = excluded.payload, fetched_at = excluded.fetched_at""",
        (market.condition_id, market.slug, market.question,
         json.dumps(market.raw), _now()),
    )
    conn.commit()


def cached_market(conn: sqlite3.Connection, key: str, max_age_h: float = 12.0) -> dict | None:
    """A cached payload by condition id or slug, if it is still fresh."""
    row = conn.execute(
        "SELECT * FROM markets WHERE condition_id = ? OR slug = ? LIMIT 1", (key, key),
    ).fetchone()
    if not row:
        return None
    try:
        age = datetime.now(timezone.utc) - datetime.fromisoformat(row["fetched_at"])
    except ValueError:
        return None
    if age > timedelta(hours=max_age_h):
        return None
    return json.loads(row["payload"])


def clear_cache(conn: sqlite3.Connection) -> int:
    cur = conn.execute("DELETE FROM markets")
    conn.commit()
    return cur.rowcount
