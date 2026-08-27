"""SQLite persistence for Deol Tech.

One file, created on first run, holding users, accounts, orders, fills, cash
and the audit trail. SQLite is the right choice here and not a compromise: the
workload is a single writer with many readers, the whole dataset fits on one
disk, and the operational cost of running the platform is `python -m deoltech
serve` rather than provisioning a database.

Two settings do the heavy lifting for concurrency. WAL lets readers proceed
while a write is in flight, and `busy_timeout` makes a contended write wait
rather than immediately raising "database is locked" — which is what turns a
threaded HTTP server from flaky into reliable.

Money is stored as REAL. That is a deliberate, documented trade-off for a
platform that settles no real cash; the ledger rounds to the currency's minor
unit on every write (see `portfolio.round_money`), so balances stay exact to
the cent.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_DB = Path(
    os.environ.get("DEOLTECH_DB")
    or Path(__file__).resolve().parents[2] / "data" / "deoltech.db"
)

SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------- identity

CREATE TABLE IF NOT EXISTS users (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    username            TEXT    NOT NULL UNIQUE COLLATE NOCASE,
    email               TEXT    COLLATE NOCASE,
    display_name        TEXT,
    password_hash       TEXT    NOT NULL,
    role                TEXT    NOT NULL DEFAULT 'trader',  -- admin | trader | viewer
    status              TEXT    NOT NULL DEFAULT 'active',  -- active | suspended
    created_at          TEXT    NOT NULL,
    created_by          INTEGER REFERENCES users(id) ON DELETE SET NULL,
    last_login_at       TEXT,
    last_login_ip       TEXT,
    -- Throttling state. Kept on the row so a restart cannot reset a lockout.
    failed_logins       INTEGER NOT NULL DEFAULT 0,
    locked_until        TEXT,
    must_change_password INTEGER NOT NULL DEFAULT 0,
    totp_secret         TEXT
);
CREATE INDEX IF NOT EXISTS idx_users_role ON users(role);

CREATE TABLE IF NOT EXISTS sessions (
    token_hash          TEXT    PRIMARY KEY,   -- sha256 of the cookie value
    user_id             INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at          TEXT    NOT NULL,
    expires_at          TEXT    NOT NULL,
    last_seen_at        TEXT,
    ip                  TEXT,
    user_agent          TEXT,
    revoked             INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_sessions_expiry ON sessions(expires_at);

CREATE TABLE IF NOT EXISTS api_tokens (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id             INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name                TEXT    NOT NULL,
    token_hash          TEXT    NOT NULL UNIQUE,
    prefix              TEXT    NOT NULL,      -- shown in the UI for identification
    scopes              TEXT    NOT NULL DEFAULT 'read',
    created_at          TEXT    NOT NULL,
    last_used_at        TEXT,
    expires_at          TEXT,
    revoked             INTEGER NOT NULL DEFAULT 0
);

-- ---------------------------------------------------------------- accounts

CREATE TABLE IF NOT EXISTS accounts (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id             INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name                TEXT    NOT NULL,
    base_ccy            TEXT    NOT NULL DEFAULT 'USD',
    starting_cash       REAL    NOT NULL DEFAULT 100000.0,
    status              TEXT    NOT NULL DEFAULT 'active',  -- active | halted | closed
    created_at          TEXT    NOT NULL,
    risk_json           TEXT    NOT NULL DEFAULT '{}',
    fees_json           TEXT    NOT NULL DEFAULT '{}',
    -- Live account state, written through on every mutation. Positions and
    -- cash are persisted directly rather than rebuilt by replaying fills:
    -- replay would re-derive historical FX conversions at today's rates and
    -- quietly drift on any non-USD-quoted instrument.
    cash_json           TEXT    NOT NULL DEFAULT '{}',
    realized_pnl        REAL    NOT NULL DEFAULT 0,
    fees_paid           REAL    NOT NULL DEFAULT 0,
    volume_30d          REAL    NOT NULL DEFAULT 0,
    UNIQUE (user_id, name)
);

CREATE TABLE IF NOT EXISTS cash_ledger (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id          INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    ts                  TEXT    NOT NULL,
    kind                TEXT    NOT NULL,
    amount              REAL    NOT NULL,
    ccy                 TEXT    NOT NULL DEFAULT 'USD',
    balance_after       REAL    NOT NULL,
    ref                 TEXT,
    note                TEXT
);
CREATE INDEX IF NOT EXISTS idx_ledger_account ON cash_ledger(account_id, ts);

-- ------------------------------------------------------------------ trading

CREATE TABLE IF NOT EXISTS orders (
    id                  TEXT    PRIMARY KEY,
    account_id          INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    client_order_id     TEXT,
    symbol              TEXT    NOT NULL,
    side                TEXT    NOT NULL,
    qty                 REAL    NOT NULL,
    order_type          TEXT    NOT NULL,
    limit_price         REAL,
    stop_price          REAL,
    tif                 TEXT    NOT NULL,
    status              TEXT    NOT NULL,
    filled_qty          REAL    NOT NULL DEFAULT 0,
    avg_fill_price      REAL    NOT NULL DEFAULT 0,
    fees_paid           REAL    NOT NULL DEFAULT 0,
    reject_reason       TEXT,
    strategy            TEXT,
    tag                 TEXT,
    parent_id           TEXT,
    oco_group           TEXT,
    created_at          TEXT    NOT NULL,
    updated_at          TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_orders_account ON orders(account_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(account_id, status);

-- Fills are append-only. Nothing in this system ever updates or deletes one:
-- the blotter is the audit trail for every position and balance on screen.
CREATE TABLE IF NOT EXISTS fills (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id          INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    order_id            TEXT    NOT NULL,
    symbol              TEXT    NOT NULL,
    side                TEXT    NOT NULL,
    qty                 REAL    NOT NULL,
    price               REAL    NOT NULL,
    fee                 REAL    NOT NULL DEFAULT 0,
    liquidity           TEXT    NOT NULL DEFAULT 'taker',
    slippage_bps        REAL    NOT NULL DEFAULT 0,
    reference_price     REAL    NOT NULL DEFAULT 0,
    ts                  TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_fills_account ON fills(account_id, ts DESC);
CREATE INDEX IF NOT EXISTS idx_fills_symbol ON fills(account_id, symbol);

CREATE TABLE IF NOT EXISTS positions (
    account_id          INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    symbol              TEXT    NOT NULL,
    qty                 REAL    NOT NULL DEFAULT 0,
    avg_price           REAL    NOT NULL DEFAULT 0,
    realized_pnl        REAL    NOT NULL DEFAULT 0,
    fees_paid           REAL    NOT NULL DEFAULT 0,
    opened_at           TEXT,
    updated_at          TEXT    NOT NULL,
    lots_json           TEXT    NOT NULL DEFAULT '[]',
    PRIMARY KEY (account_id, symbol)
);

CREATE TABLE IF NOT EXISTS equity_curve (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id          INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    ts                  TEXT    NOT NULL,
    equity              REAL    NOT NULL,
    cash                REAL    NOT NULL,
    unrealized          REAL    NOT NULL DEFAULT 0,
    realized            REAL    NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_curve_account ON equity_curve(account_id, ts);

CREATE TABLE IF NOT EXISTS watchlist (
    user_id             INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    symbol              TEXT    NOT NULL,
    sort_order          INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, symbol)
);

-- ------------------------------------------------------------------- admin

-- Append-only. Administrative power without a record of its use is not
-- accountability, so every privileged action lands here.
CREATE TABLE IF NOT EXISTS audit_log (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    ts                  TEXT    NOT NULL,
    actor_id            INTEGER REFERENCES users(id) ON DELETE SET NULL,
    actor_name          TEXT,
    action              TEXT    NOT NULL,
    target              TEXT,
    detail              TEXT,
    ip                  TEXT,
    severity            TEXT    NOT NULL DEFAULT 'info'   -- info | warning | critical
);
CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_log(ts DESC);
CREATE INDEX IF NOT EXISTS idx_audit_actor ON audit_log(actor_id, ts DESC);

CREATE TABLE IF NOT EXISTS settings (
    key                 TEXT PRIMARY KEY,
    value               TEXT NOT NULL,
    updated_at          TEXT NOT NULL,
    updated_by          INTEGER REFERENCES users(id) ON DELETE SET NULL
);
"""

_local = threading.local()


def db_path() -> Path:
    return Path(os.environ.get("DEOLTECH_DB") or DEFAULT_DB)


def connect(path: str | Path | None = None) -> sqlite3.Connection:
    """Open (and initialize) the database. One connection per thread."""
    target = Path(path) if path else db_path()
    key = f"conn:{target}"
    existing = getattr(_local, key, None)
    if existing is not None:
        return existing

    target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(target), timeout=30.0,
                           detect_types=sqlite3.PARSE_DECLTYPES)
    conn.row_factory = sqlite3.Row
    # Wait for a contended write instead of failing the request outright.
    conn.execute("PRAGMA busy_timeout = 30000")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    conn.commit()
    setattr(_local, key, conn)
    return conn


def close_thread_connections() -> None:
    for attr in [a for a in vars(_local) if a.startswith("conn:")]:
        try:
            getattr(_local, attr).close()
        except Exception:
            pass
        delattr(_local, attr)


@contextmanager
def transaction(conn: sqlite3.Connection):
    """All-or-nothing. A half-written order is worse than a rejected one."""
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


# ------------------------------------------------------------------ settings


def get_setting(conn: sqlite3.Connection, key: str, default=None):
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    if row is None:
        return default
    try:
        return json.loads(row["value"])
    except json.JSONDecodeError:
        return row["value"]


def set_setting(conn: sqlite3.Connection, key: str, value,
                actor_id: int | None = None) -> None:
    with transaction(conn):
        conn.execute(
            """INSERT INTO settings (key, value, updated_at, updated_by)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(key) DO UPDATE SET
                   value = excluded.value,
                   updated_at = excluded.updated_at,
                   updated_by = excluded.updated_by""",
            (key, json.dumps(value), now_iso(), actor_id))


def all_settings(conn: sqlite3.Connection) -> dict:
    return {r["key"]: get_setting(conn, r["key"])
            for r in conn.execute("SELECT key FROM settings")}


# ----------------------------------------------------------------- audit log


def audit(conn: sqlite3.Connection, action: str, *, actor_id: int | None = None,
          actor_name: str = "", target: str = "", detail: str = "",
          ip: str = "", severity: str = "info") -> None:
    with transaction(conn):
        conn.execute(
            """INSERT INTO audit_log
                   (ts, actor_id, actor_name, action, target, detail, ip, severity)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (now_iso(), actor_id, actor_name, action, target, detail, ip, severity))


def audit_trail(conn: sqlite3.Connection, limit: int = 200,
                actor_id: int | None = None,
                severity: str | None = None) -> list[dict]:
    sql = "SELECT * FROM audit_log WHERE 1=1"
    args: list = []
    if actor_id is not None:
        sql += " AND actor_id = ?"
        args.append(actor_id)
    if severity:
        sql += " AND severity = ?"
        args.append(severity)
    sql += " ORDER BY ts DESC, id DESC LIMIT ?"
    args.append(limit)
    return [dict(r) for r in conn.execute(sql, args)]


def stats(conn: sqlite3.Connection) -> dict:
    def count(table: str, where: str = "", args: tuple = ()) -> int:
        sql = f"SELECT COUNT(*) AS n FROM {table}"
        if where:
            sql += f" WHERE {where}"
        return conn.execute(sql, args).fetchone()["n"]

    return {
        "users": count("users"),
        "active_users": count("users", "status = 'active'"),
        "admins": count("users", "role = 'admin'"),
        "accounts": count("accounts"),
        "orders": count("orders"),
        "fills": count("fills"),
        "sessions": count("sessions", "revoked = 0 AND expires_at > ?", (now_iso(),)),
        "audit_entries": count("audit_log"),
        "db_path": str(db_path()),
        "db_size_bytes": db_path().stat().st_size if db_path().exists() else 0,
    }
