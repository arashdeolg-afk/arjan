"""Recording storage. SQLite, stdlib only."""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

from .book import Snapshot

DEFAULT_DB = Path(__file__).resolve().parents[2] / "data" / "pmpaper.db"

SCHEMA = """
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    label       TEXT NOT NULL,
    started_at  TEXT NOT NULL,
    config      TEXT
);

-- Raw market observations. Append-only: this is the evidence, and a
-- backtest is only as honest as the tape it ran on.
CREATE TABLE IF NOT EXISTS snapshots (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id       INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    market_id    TEXT,
    ts           REAL NOT NULL,
    window_start REAL NOT NULL,
    window_end   REAL NOT NULL,
    strike       REAL NOT NULL,
    spot         REAL NOT NULL,
    yes_bid      REAL NOT NULL,
    yes_ask      REAL NOT NULL,
    yes_bid_size REAL NOT NULL DEFAULT 0,
    yes_ask_size REAL NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS trades (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id     INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    strategy   TEXT NOT NULL,
    ts         REAL NOT NULL,
    side       TEXT NOT NULL,
    price      REAL NOT NULL,
    size       REAL NOT NULL,
    fee        REAL NOT NULL,
    slippage   REAL NOT NULL,
    pnl        REAL NOT NULL,
    win        INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_snap_run ON snapshots(run_id, ts);
CREATE INDEX IF NOT EXISTS idx_trade_run ON trades(run_id, strategy);
"""


def db_path() -> Path:
    env = os.environ.get("PMPAPER_DB")
    return Path(env) if env else DEFAULT_DB


def connect(path: Path | str | None = None) -> sqlite3.Connection:
    target = Path(path) if path else db_path()
    if str(target) != ":memory:":
        target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(target)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def new_run(conn: sqlite3.Connection, label: str, config: dict | None = None) -> int:
    from datetime import datetime, timezone
    cur = conn.execute(
        "INSERT INTO runs (label, started_at, config) VALUES (?,?,?)",
        (label, datetime.now(timezone.utc).isoformat(timespec="seconds"),
         json.dumps(config or {})),
    )
    conn.commit()
    return int(cur.lastrowid)


def save_snapshots(conn: sqlite3.Connection, run_id: int,
                   snaps: list[Snapshot], market_id: str | None = None) -> int:
    conn.executemany(
        """INSERT INTO snapshots (run_id, market_id, ts, window_start, window_end,
                                  strike, spot, yes_bid, yes_ask,
                                  yes_bid_size, yes_ask_size)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        [(run_id, market_id, s.ts, s.window_start, s.window_end, s.strike,
          s.spot, s.yes_bid, s.yes_ask, s.yes_bid_size, s.yes_ask_size)
         for s in snaps],
    )
    conn.commit()
    return len(snaps)


def load_snapshots(conn: sqlite3.Connection, run_id: int) -> list[Snapshot]:
    rows = conn.execute(
        "SELECT * FROM snapshots WHERE run_id = ? ORDER BY ts, id", (run_id,)
    )
    return [Snapshot(ts=r["ts"], window_start=r["window_start"],
                     window_end=r["window_end"], strike=r["strike"], spot=r["spot"],
                     yes_bid=r["yes_bid"], yes_ask=r["yes_ask"],
                     yes_bid_size=r["yes_bid_size"], yes_ask_size=r["yes_ask_size"])
            for r in rows]


def list_runs(conn: sqlite3.Connection) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT r.*, (SELECT COUNT(*) FROM snapshots s WHERE s.run_id = r.id) AS snaps "
        "FROM runs r ORDER BY r.id DESC")]
