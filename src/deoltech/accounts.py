"""Account service: the bridge between the database and the live engine.

A `PaperBroker` holds its state in memory because the matching loop needs it
there. The database holds the record of truth across restarts. This module owns
the relationship between the two:

* One broker instance per account, cached, created on first use.
* **Write-through persistence** — every order, fill, position change and cash
  movement is written as it happens, so a crash loses at most the tick in
  flight.
* A single shared market data feed across all accounts, so fifty users watching
  AAPL cost one request, not fifty.

Positions and cash are persisted directly rather than reconstructed by
replaying the fill log. Replay is tempting (the fill log is append-only and
authoritative) but it would re-derive every historical FX conversion at today's
rate, so any non-USD-quoted instrument would drift a little further from the
truth on each restart.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import asdict
from datetime import datetime, timezone

from .db import audit, now_iso, transaction
from .engine.broker import EquityPoint, PaperBroker
from .engine.fees import FeeSchedule
from .engine.risk import RiskLimits
from .engine.slippage import SlippageModel
from .feeds import Feed, build_feed
from .instruments import DEFAULT_WATCHLIST, resolve
from .portfolio import CashEntry, Portfolio
from .types import (
    Fill, Liquidity, Lot, Order, OrderStatus, OrderType, Position, Side,
    TimeInForce, parse_iso, utcnow,
)


class AccountError(Exception):
    """A problem with an account operation, safe to show a user."""


# ------------------------------------------------------------------- accounts


def create_account(conn: sqlite3.Connection, user_id: int, name: str = "Main", *,
                   starting_cash: float = 100_000.0, base_ccy: str = "USD",
                   actor_name: str = "") -> int:
    if starting_cash <= 0:
        raise AccountError("Starting cash must be greater than zero.")
    if starting_cash > 100_000_000:
        raise AccountError("Starting cash is capped at 100,000,000.")
    existing = conn.execute(
        "SELECT id FROM accounts WHERE user_id = ? AND name = ?",
        (user_id, name)).fetchone()
    if existing:
        raise AccountError(f"You already have an account named {name!r}.")
    with transaction(conn):
        cur = conn.execute(
            """INSERT INTO accounts (user_id, name, base_ccy, starting_cash,
                                     status, created_at, cash_json)
               VALUES (?, ?, ?, ?, 'active', ?, ?)""",
            (user_id, name.strip()[:60], base_ccy, starting_cash, now_iso(),
             json.dumps({base_ccy: starting_cash})))
        account_id = cur.lastrowid
        conn.execute(
            """INSERT INTO cash_ledger (account_id, ts, kind, amount, ccy,
                                        balance_after, note)
               VALUES (?, ?, 'deposit', ?, ?, ?, 'opening balance')""",
            (account_id, now_iso(), starting_cash, base_ccy, starting_cash))
    audit(conn, "account.create", actor_id=user_id, actor_name=actor_name,
          target=f"account:{account_id}",
          detail=f"{name} opening {starting_cash:,.2f} {base_ccy}")
    return account_id


def list_accounts(conn: sqlite3.Connection, user_id: int | None = None) -> list[dict]:
    sql = """SELECT a.*, u.username,
                    (SELECT COUNT(*) FROM orders o WHERE o.account_id = a.id) AS orders,
                    (SELECT COUNT(*) FROM fills f WHERE f.account_id = a.id) AS fills
             FROM accounts a JOIN users u ON u.id = a.user_id"""
    args: tuple = ()
    if user_id is not None:
        sql += " WHERE a.user_id = ?"
        args = (user_id,)
    sql += " ORDER BY a.created_at"
    return [dict(r) for r in conn.execute(sql, args)]


def get_account(conn: sqlite3.Connection, account_id: int) -> dict:
    row = conn.execute("""SELECT a.*, u.username FROM accounts a
                          JOIN users u ON u.id = a.user_id WHERE a.id = ?""",
                       (account_id,)).fetchone()
    if not row:
        raise AccountError("No such account.")
    return dict(row)


def default_account(conn: sqlite3.Connection, user_id: int,
                    username: str = "") -> int:
    """The user's first account, created on demand."""
    row = conn.execute(
        "SELECT id FROM accounts WHERE user_id = ? ORDER BY id LIMIT 1",
        (user_id,)).fetchone()
    if row:
        return row["id"]
    return create_account(conn, user_id, "Main", actor_name=username)


def reset_account(conn: sqlite3.Connection, account_id: int,
                  actor_name: str = "") -> None:
    """Wipe an account back to its opening balance.

    Destructive and deliberate: paper trading is for practice, and a record
    full of abandoned experiments teaches nothing. Everything is deleted, not
    archived — the audit entry is the only trace kept.
    """
    acct = get_account(conn, account_id)
    with transaction(conn):
        for table in ("fills", "orders", "positions", "cash_ledger", "equity_curve"):
            conn.execute(f"DELETE FROM {table} WHERE account_id = ?", (account_id,))
        conn.execute(
            """UPDATE accounts SET cash_json = ?, realized_pnl = 0, fees_paid = 0,
                                   volume_30d = 0, status = 'active'
               WHERE id = ?""",
            (json.dumps({acct["base_ccy"]: acct["starting_cash"]}), account_id))
        conn.execute(
            """INSERT INTO cash_ledger (account_id, ts, kind, amount, ccy,
                                        balance_after, note)
               VALUES (?, ?, 'deposit', ?, ?, ?, 'account reset')""",
            (account_id, now_iso(), acct["starting_cash"], acct["base_ccy"],
             acct["starting_cash"]))
    audit(conn, "account.reset", actor_name=actor_name,
          target=f"account:{account_id}",
          detail="all orders, fills and positions deleted", severity="warning")


# ---------------------------------------------------------------- persistence


def _load_portfolio(conn: sqlite3.Connection, account_id: int) -> Portfolio:
    acct = get_account(conn, account_id)
    p = Portfolio(account_id=str(account_id), base_ccy=acct["base_ccy"],
                  starting_cash=acct["starting_cash"])
    try:
        cash = json.loads(acct["cash_json"] or "{}")
    except json.JSONDecodeError:
        cash = {}
    p.cash = cash or {acct["base_ccy"]: acct["starting_cash"]}
    p.realized_pnl = acct["realized_pnl"]
    p.fees_paid = acct["fees_paid"]
    p.volume_30d = acct["volume_30d"]

    for row in conn.execute("SELECT * FROM positions WHERE account_id = ?",
                            (account_id,)):
        if abs(row["qty"]) < 1e-12:
            continue
        pos = Position(
            symbol=row["symbol"], qty=row["qty"], avg_price=row["avg_price"],
            realized_pnl=row["realized_pnl"], fees_paid=row["fees_paid"],
            opened_at=parse_iso(row["opened_at"]) if row["opened_at"] else None,
            last_price=row["avg_price"],
        )
        try:
            pos.lots = [Lot(qty=l["qty"], price=l["price"], ts=parse_iso(l["ts"]))
                        for l in json.loads(row["lots_json"] or "[]")]
        except (json.JSONDecodeError, KeyError):
            pos.lots = [Lot(qty=abs(pos.qty), price=pos.avg_price,
                            ts=pos.opened_at or utcnow())]
        p.positions[pos.symbol] = pos
        p.prices[pos.symbol] = row["avg_price"]

    # The opening deposit is synthesized by Portfolio.__post_init__; replace the
    # journal with what actually happened so `_net_deposits` stays truthful.
    p.ledger = [
        CashEntry(ts=parse_iso(r["ts"]), kind=r["kind"], amount=r["amount"],
                  ccy=r["ccy"], balance_after=r["balance_after"],
                  ref=r["ref"] or "", note=r["note"] or "")
        for r in conn.execute(
            "SELECT * FROM cash_ledger WHERE account_id = ? ORDER BY id",
            (account_id,))
    ] or p.ledger
    return p


def _load_orders(conn: sqlite3.Connection, account_id: int, broker: PaperBroker) -> None:
    """Restore orders. Only open ones go back into the working book."""
    for r in conn.execute(
            """SELECT * FROM orders WHERE account_id = ?
               ORDER BY created_at DESC LIMIT 2000""", (account_id,)):
        try:
            order = Order(
                symbol=r["symbol"], side=Side(r["side"]), qty=r["qty"],
                order_type=OrderType(r["order_type"]),
                limit_price=r["limit_price"], stop_price=r["stop_price"],
                tif=TimeInForce(r["tif"]),
                expires_at=None, parent_id=r["parent_id"],
                oco_group=r["oco_group"], strategy=r["strategy"], tag=r["tag"],
                client_order_id=r["client_order_id"] or r["id"],
            )
        except (ValueError, TypeError):
            continue     # a row we can no longer interpret must not break login
        order.id = r["id"]
        order.status = OrderStatus(r["status"])
        order.filled_qty = r["filled_qty"]
        order.avg_fill_price = r["avg_fill_price"]
        order.fees_paid = r["fees_paid"]
        order.reject_reason = r["reject_reason"]
        order.created_at = parse_iso(r["created_at"])
        order.updated_at = parse_iso(r["updated_at"])
        order.triggered = order.status is OrderStatus.PARTIALLY_FILLED
        broker.orders[order.id] = order
        if order.status.is_open:
            broker.working[order.id] = order
            if order.oco_group:
                broker._oco[order.oco_group].add(order.id)

    for r in conn.execute(
            """SELECT * FROM fills WHERE account_id = ? ORDER BY ts LIMIT 5000""",
            (account_id,)):
        broker.fills.append(Fill(
            order_id=r["order_id"], symbol=r["symbol"], side=Side(r["side"]),
            qty=r["qty"], price=r["price"], ts=parse_iso(r["ts"]),
            fee=r["fee"], liquidity=Liquidity(r["liquidity"]),
            slippage_bps=r["slippage_bps"], reference_price=r["reference_price"]))

    broker.equity_curve = [
        EquityPoint(parse_iso(r["ts"]), r["equity"], r["cash"],
                    r["unrealized"], r["realized"])
        for r in conn.execute(
            """SELECT * FROM equity_curve WHERE account_id = ?
               ORDER BY ts LIMIT 5000""", (account_id,))]


def save_order(conn: sqlite3.Connection, account_id: int, order: Order) -> None:
    row = order.to_row()
    with transaction(conn):
        conn.execute(
            """INSERT INTO orders (id, account_id, client_order_id, symbol, side,
                    qty, order_type, limit_price, stop_price, tif, status,
                    filled_qty, avg_fill_price, fees_paid, reject_reason,
                    strategy, tag, parent_id, oco_group, created_at, updated_at)
               VALUES (:id, :account_id, :client_order_id, :symbol, :side, :qty,
                    :order_type, :limit_price, :stop_price, :tif, :status,
                    :filled_qty, :avg_fill_price, :fees_paid, :reject_reason,
                    :strategy, :tag, :parent_id, :oco_group, :created_at,
                    :updated_at)
               ON CONFLICT(id) DO UPDATE SET
                    status = excluded.status,
                    filled_qty = excluded.filled_qty,
                    avg_fill_price = excluded.avg_fill_price,
                    fees_paid = excluded.fees_paid,
                    reject_reason = excluded.reject_reason,
                    limit_price = excluded.limit_price,
                    stop_price = excluded.stop_price,
                    updated_at = excluded.updated_at""",
            {**row, "account_id": account_id})


def save_fill(conn: sqlite3.Connection, account_id: int, fill: Fill) -> None:
    with transaction(conn):
        conn.execute(
            """INSERT INTO fills (account_id, order_id, symbol, side, qty, price,
                                  fee, liquidity, slippage_bps, reference_price, ts)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (account_id, fill.order_id, fill.symbol, fill.side.value, fill.qty,
             fill.price, fill.fee, fill.liquidity.value, fill.slippage_bps,
             fill.reference_price, fill.ts.isoformat()))


def save_portfolio(conn: sqlite3.Connection, account_id: int,
                   portfolio: Portfolio, ledger_from: int = 0) -> int:
    """Persist positions, cash and any new ledger lines. Returns the new mark."""
    with transaction(conn):
        conn.execute(
            """UPDATE accounts SET cash_json = ?, realized_pnl = ?, fees_paid = ?,
                                   volume_30d = ? WHERE id = ?""",
            (json.dumps(portfolio.cash), portfolio.realized_pnl,
             portfolio.fees_paid, portfolio.volume_30d, account_id))

        for pos in portfolio.positions.values():
            if pos.is_flat:
                conn.execute(
                    "DELETE FROM positions WHERE account_id = ? AND symbol = ?",
                    (account_id, pos.symbol))
                continue
            conn.execute(
                """INSERT INTO positions (account_id, symbol, qty, avg_price,
                        realized_pnl, fees_paid, opened_at, updated_at, lots_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(account_id, symbol) DO UPDATE SET
                        qty = excluded.qty, avg_price = excluded.avg_price,
                        realized_pnl = excluded.realized_pnl,
                        fees_paid = excluded.fees_paid,
                        opened_at = excluded.opened_at,
                        updated_at = excluded.updated_at,
                        lots_json = excluded.lots_json""",
                (account_id, pos.symbol, pos.qty, pos.avg_price, pos.realized_pnl,
                 pos.fees_paid,
                 pos.opened_at.isoformat() if pos.opened_at else None, now_iso(),
                 json.dumps([{"qty": l.qty, "price": l.price,
                              "ts": l.ts.isoformat()} for l in pos.lots])))

        for entry in portfolio.ledger[ledger_from:]:
            conn.execute(
                """INSERT INTO cash_ledger (account_id, ts, kind, amount, ccy,
                                            balance_after, ref, note)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (account_id, entry.ts.isoformat(), entry.kind, entry.amount,
                 entry.ccy, entry.balance_after, entry.ref, entry.note))
    return len(portfolio.ledger)


def save_equity_point(conn: sqlite3.Connection, account_id: int,
                      point: EquityPoint) -> None:
    with transaction(conn):
        conn.execute(
            """INSERT INTO equity_curve (account_id, ts, equity, cash,
                                         unrealized, realized)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (account_id, point.ts.isoformat(), point.equity, point.cash,
             point.unrealized, point.realized))


# -------------------------------------------------------------------- service


class AccountService:
    """Owns the live brokers and the shared market data feed."""

    def __init__(self, conn_factory, *, feed: Feed | None = None,
                 feed_mode: str = "auto", finviz_token: str = "",
                 quote_ttl_s: float = 5.0):
        self._conn_factory = conn_factory
        self.feed = feed or build_feed(feed_mode, finviz_token=finviz_token,
                                       cache_ttl_s=quote_ttl_s)
        self.feed_mode = feed_mode
        self._brokers: dict[int, PaperBroker] = {}
        self._ledger_marks: dict[int, int] = {}
        self._lock = threading.RLock()

    # ------------------------------------------------------------- brokers

    def broker(self, account_id: int) -> PaperBroker:
        with self._lock:
            if account_id in self._brokers:
                return self._brokers[account_id]
            conn = self._conn_factory()
            acct = get_account(conn, account_id)
            portfolio = _load_portfolio(conn, account_id)

            risk = RiskLimits(**{**_safe_json(acct["risk_json"])})
            fees = FeeSchedule(**{**_safe_json(acct["fees_json"])})
            if acct["status"] == "halted":
                risk.trading_halted = True
                risk.halt_reason = "halted by an administrator"

            broker = PaperBroker(portfolio, feed=self.feed, fee_schedule=fees,
                                 risk_limits=risk, slippage=SlippageModel())
            _load_orders(conn, account_id, broker)
            self._brokers[account_id] = broker
            self._ledger_marks[account_id] = len(portfolio.ledger)
            return broker

    def evict(self, account_id: int) -> None:
        """Drop a cached broker so the next request reloads it from disk."""
        with self._lock:
            self._brokers.pop(account_id, None)
            self._ledger_marks.pop(account_id, None)

    def persist(self, account_id: int, orders: list[Order] | None = None,
                fills: list[Fill] | None = None) -> None:
        conn = self._conn_factory()
        broker = self._brokers.get(account_id)
        if broker is None:
            return
        for order in orders or []:
            save_order(conn, account_id, order)
        for fill in fills or []:
            save_fill(conn, account_id, fill)
        mark = self._ledger_marks.get(account_id, 0)
        self._ledger_marks[account_id] = save_portfolio(
            conn, account_id, broker.portfolio, mark)
        if broker.equity_curve:
            save_equity_point(conn, account_id, broker.equity_curve[-1])

    # -------------------------------------------------------------- trading

    def submit(self, account_id: int, order: Order) -> Order:
        broker = self.broker(account_id)
        before = len(broker.fills)
        placed = broker.submit(order)
        new_fills = broker.fills[before:]
        # Bracket children are created during submit; persist them all.
        touched = [placed] + [o for o in broker.orders.values()
                              if o.parent_id == placed.id]
        self.persist(account_id, touched, new_fills)
        return placed

    def cancel(self, account_id: int, order_id: str) -> bool:
        broker = self.broker(account_id)
        ok = broker.cancel(order_id)
        if ok:
            order = broker.orders.get(order_id)
            self.persist(account_id, [order] if order else [])
        return ok

    def refresh(self, account_id: int, symbols: list[str] | None = None) -> list[Fill]:
        """Pull quotes, advance working orders, persist anything that changed."""
        broker = self.broker(account_id)
        before_orders = {o.id: o.status for o in broker.orders.values()}
        fills = broker.refresh(symbols)
        changed = [o for o in broker.orders.values()
                   if before_orders.get(o.id) != o.status]
        self.persist(account_id, changed, fills)
        return fills

    def close_position(self, account_id: int, symbol: str,
                       qty: float | None = None) -> Order | None:
        broker = self.broker(account_id)
        before = len(broker.fills)
        order = broker.close_position(symbol, qty)
        if order:
            self.persist(account_id, [order], broker.fills[before:])
        return order

    def flatten_all(self, account_id: int) -> list[Order]:
        broker = self.broker(account_id)
        before = len(broker.fills)
        orders = broker.flatten_all()
        self.persist(account_id, list(broker.orders.values()),
                     broker.fills[before:])
        return orders

    # --------------------------------------------------------------- market

    def quotes(self, symbols: list[str]) -> dict:
        if not symbols:
            return {}
        try:
            return self.feed.get_quotes(symbols)
        except Exception:
            return {}

    def quote(self, symbol: str):
        return self.feed.get_quote(symbol)

    def bars(self, symbol: str, interval: str = "1d", limit: int = 200):
        return self.feed.get_bars(symbol, interval, limit)

    def feed_health(self) -> dict:
        h = self.feed.health()
        inner = getattr(self.feed, "inner", None)
        degraded = bool(getattr(inner, "degraded", False))
        return {
            "name": h.name, "ok": h.ok, "breaker": h.breaker,
            "requests": h.requests, "errors": h.errors,
            "error_rate": round(h.error_rate, 4),
            "last_success": h.last_success.isoformat() if h.last_success else None,
            "last_error": h.last_error,
            "mode": self.feed_mode,
            "degraded": degraded,
            "source": getattr(inner, "last_used", "") or h.name,
        }

    # ------------------------------------------------------------ watchlist

    def watchlist(self, user_id: int) -> list[str]:
        conn = self._conn_factory()
        rows = conn.execute(
            "SELECT symbol FROM watchlist WHERE user_id = ? ORDER BY sort_order, symbol",
            (user_id,)).fetchall()
        if rows:
            return [r["symbol"] for r in rows]
        default = [s for group in DEFAULT_WATCHLIST.values() for s in group]
        self.set_watchlist(user_id, default)
        return default

    def set_watchlist(self, user_id: int, symbols: list[str]) -> list[str]:
        clean, seen = [], set()
        for s in symbols[:100]:
            sym = resolve(s).symbol
            if sym not in seen:
                seen.add(sym)
                clean.append(sym)
        conn = self._conn_factory()
        with transaction(conn):
            conn.execute("DELETE FROM watchlist WHERE user_id = ?", (user_id,))
            conn.executemany(
                "INSERT INTO watchlist (user_id, symbol, sort_order) VALUES (?, ?, ?)",
                [(user_id, s, i) for i, s in enumerate(clean)])
        return clean

    # ------------------------------------------------------------- admin ops

    def halt_account(self, account_id: int, reason: str, actor_name: str = "") -> None:
        broker = self.broker(account_id)
        broker.halt(reason)
        conn = self._conn_factory()
        with transaction(conn):
            conn.execute("UPDATE accounts SET status = 'halted' WHERE id = ?",
                         (account_id,))
        self.persist(account_id, list(broker.orders.values()))
        audit(conn, "account.halt", actor_name=actor_name,
              target=f"account:{account_id}", detail=reason, severity="critical")

    def resume_account(self, account_id: int, actor_name: str = "") -> None:
        broker = self.broker(account_id)
        broker.resume()
        conn = self._conn_factory()
        with transaction(conn):
            conn.execute("UPDATE accounts SET status = 'active' WHERE id = ?",
                         (account_id,))
        audit(conn, "account.resume", actor_name=actor_name,
              target=f"account:{account_id}", severity="warning")

    def update_risk(self, account_id: int, changes: dict,
                    actor_name: str = "") -> RiskLimits:
        broker = self.broker(account_id)
        applied = {}
        for key, value in changes.items():
            if not hasattr(broker.risk.limits, key):
                continue
            current = getattr(broker.risk.limits, key)
            try:
                cast = type(current)(value) if not isinstance(current, bool) \
                    else str(value).lower() in ("1", "true", "yes", "on")
            except (TypeError, ValueError):
                continue
            setattr(broker.risk.limits, key, cast)
            applied[key] = cast
        conn = self._conn_factory()
        stored = {k: v for k, v in asdict(broker.risk.limits).items()
                  if not isinstance(v, (list, tuple)) or k == "allowed_asset_classes"}
        stored["allowed_asset_classes"] = tuple(
            broker.risk.limits.allowed_asset_classes)
        with transaction(conn):
            conn.execute("UPDATE accounts SET risk_json = ? WHERE id = ?",
                         (json.dumps(stored, default=list), account_id))
        audit(conn, "account.risk", actor_name=actor_name,
              target=f"account:{account_id}",
              detail=", ".join(f"{k}={v}" for k, v in applied.items()),
              severity="warning")
        return broker.risk.limits


def _safe_json(text: str | None) -> dict:
    try:
        data = json.loads(text or "{}")
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}
