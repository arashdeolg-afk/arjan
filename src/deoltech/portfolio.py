"""Positions, cash, and margin.

The accounting rules here are the ones that decide whether a P&L number means
anything:

**FIFO tax lots.** Realized P&L is computed by consuming the oldest lot first,
not by subtracting an average. Averages hide the shape of a position: a trader
who scaled into a loser and then sold their oldest, cheapest shares has a very
different result from one who sold their newest, and only lot accounting shows
it. It is also what a tax authority expects.

**Shorts are real.** Selling short credits the proceeds to cash and creates a
negative position. P&L accrues in the opposite direction and the borrow is
charged daily. A system that models a short as "a long with a minus sign"
misses the margin requirement, the borrow cost, and the unbounded loss.

**Position P&L is denominated in the instrument's quote currency**, then
converted to the account currency. A long USD/JPY earns yen. Skipping that
conversion overstates the result by a factor of ~147, and it is the single
most common bug in multi-asset paper platforms.

**Cash is rounded to the minor unit on every write.** Floats accumulate dust;
a balance that reads $10,000.000000000002 destroys confidence in everything
else on the screen.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime

from .instruments import Instrument, resolve
from .types import (
    AssetClass, Fill, Lot, Position, Side, iso, utcnow,
)

# Currencies whose minor unit is the whole number (no cents).
ZERO_DECIMAL_CCY = frozenset({"JPY", "KRW", "HUF", "CLP", "ISK", "VND"})


def round_money(amount: float, ccy: str = "USD") -> float:
    places = 0 if ccy.upper() in ZERO_DECIMAL_CCY else 2
    return round(amount, places)


@dataclass
class CashEntry:
    """One line of the cash ledger. Append-only; the balance is their sum."""

    ts: datetime
    kind: str            # deposit | withdrawal | trade | fee | swap | borrow | adjustment
    amount: float        # signed, in `ccy`
    ccy: str = "USD"
    balance_after: float = 0.0
    ref: str = ""        # order id, fill id, or a human note
    note: str = ""


@dataclass
class Portfolio:
    """One paper account's holdings, cash and margin state."""

    account_id: str = "default"
    base_ccy: str = "USD"
    starting_cash: float = 100_000.0
    cash: dict[str, float] = field(default_factory=dict)
    positions: dict[str, Position] = field(default_factory=dict)
    ledger: list[CashEntry] = field(default_factory=list)
    realized_pnl: float = 0.0
    fees_paid: float = 0.0
    prices: dict[str, float] = field(default_factory=dict)
    # Rolling 30-day traded notional, for crypto fee tiering.
    volume_30d: float = 0.0

    def __post_init__(self) -> None:
        if not self.cash:
            self.cash = {self.base_ccy: round_money(self.starting_cash, self.base_ccy)}
            self.ledger.append(CashEntry(
                ts=utcnow(), kind="deposit", amount=self.starting_cash,
                ccy=self.base_ccy, balance_after=self.starting_cash,
                note="opening balance"))

    # ------------------------------------------------------------------ cash

    def balance(self, ccy: str | None = None) -> float:
        return self.cash.get(ccy or self.base_ccy, 0.0)

    def credit(self, amount: float, kind: str = "adjustment", *,
               ccy: str | None = None, ref: str = "", note: str = "",
               ts: datetime | None = None) -> float:
        """Move cash and journal it. Every balance change goes through here."""
        c = (ccy or self.base_ccy).upper()
        new = round_money(self.cash.get(c, 0.0) + amount, c)
        self.cash[c] = new
        self.ledger.append(CashEntry(
            ts=ts or utcnow(), kind=kind, amount=round_money(amount, c), ccy=c,
            balance_after=new, ref=ref, note=note))
        return new

    def fx_rate(self, ccy: str) -> float:
        """Units of the account currency per one unit of `ccy`.

        Resolved from live prices where possible: JPY comes from USD/JPY,
        EUR from EUR/USD. Falls back to 1.0, which is right for the USD-quoted
        instruments that make up most of the platform.
        """
        c = ccy.upper()
        if c == self.base_ccy:
            return 1.0
        direct = self.prices.get(f"{c}{self.base_ccy}")
        if direct and direct > 0:
            return direct
        inverse = self.prices.get(f"{self.base_ccy}{c}")
        if inverse and inverse > 0:
            return 1.0 / inverse
        return 1.0

    def to_account(self, amount: float, ccy: str) -> float:
        return amount * self.fx_rate(ccy)

    # ------------------------------------------------------------- positions

    def position(self, symbol: str) -> Position:
        sym = symbol.upper()
        if sym not in self.positions:
            self.positions[sym] = Position(symbol=sym)
        return self.positions[sym]

    def open_positions(self) -> list[Position]:
        return [p for p in self.positions.values() if not p.is_flat]

    def mark(self, prices: dict[str, float]) -> None:
        """Update marks. Everything downstream reads from these."""
        for sym, px in prices.items():
            if px and px > 0:
                s = sym.upper()
                self.prices[s] = px
                if s in self.positions:
                    self.positions[s].last_price = px

    def price_of(self, symbol: str) -> float:
        sym = symbol.upper()
        px = self.prices.get(sym, 0.0)
        if px > 0:
            return px
        pos = self.positions.get(sym)
        return pos.last_price if pos else 0.0

    # ----------------------------------------------------------------- fills

    def apply_fill(self, fill: Fill, inst: Instrument | None = None) -> float:
        """Book one execution. Returns the realized P&L it produced.

        Handles the four cases that matter — open, add, reduce (with FIFO lot
        consumption), and flip through zero — plus cash and fees.
        """
        inst = inst or resolve(fill.symbol)
        pos = self.position(fill.symbol)
        signed = fill.side.sign * fill.qty
        realized_quote = 0.0

        if pos.is_flat or (pos.qty > 0) == (signed > 0):
            # Opening or adding. Weighted-average cost moves; nothing realizes.
            total = abs(pos.qty) + abs(signed)
            if total > 0:
                pos.avg_price = ((abs(pos.qty) * pos.avg_price
                                  + abs(signed) * fill.price) / total)
            pos.qty += signed
            pos.lots.append(Lot(qty=abs(signed), price=fill.price, ts=fill.ts,
                                fee=fill.fee))
            if pos.opened_at is None:
                pos.opened_at = fill.ts
        else:
            # Reducing, closing, or flipping. Consume lots oldest-first.
            closing = min(abs(signed), abs(pos.qty))
            realized_quote = self._consume_lots(pos, closing, fill.price)
            pos.qty += signed
            if abs(pos.qty) < 1e-12:
                pos.qty = 0.0
                pos.avg_price = 0.0
                pos.lots.clear()
                pos.opened_at = None
            elif (pos.qty > 0) != (signed < 0):
                # Flipped through zero: the remainder opens a fresh position.
                remainder = abs(signed) - closing
                pos.avg_price = fill.price
                pos.lots = [Lot(qty=remainder, price=fill.price, ts=fill.ts)]
                pos.opened_at = fill.ts
            else:
                # Partial reduce. The average cost must be recomputed from the
                # lots that SURVIVED, not left at the pre-sale average: after
                # selling the cheap FIFO lot, what remains is more expensive,
                # and a stale average would misstate unrealized P&L from here
                # until the position closes.
                rem = sum(lot.qty for lot in pos.lots)
                if rem > 1e-12:
                    pos.avg_price = sum(lot.qty * lot.price
                                        for lot in pos.lots) / rem

        rate = self.fx_rate(inst.quote_ccy)
        realized_account = realized_quote * rate * inst.multiplier
        pos.realized_pnl += realized_account
        pos.last_price = fill.price
        self.prices[fill.symbol.upper()] = fill.price
        self.realized_pnl += realized_account

        # Cash: the trade's principal (in quote currency, converted) and fees
        # (already in account currency, per the fee engine's contract).
        principal = -fill.side.sign * inst.notional(fill.qty, fill.price) * rate
        self.credit(principal, "trade", ref=fill.order_id,
                    note=f"{fill.side.value} {inst.fmt_qty(fill.qty)} "
                         f"{fill.symbol} @ {inst.fmt_price(fill.price)}", ts=fill.ts)
        if fill.fee:
            pos.fees_paid += fill.fee
            self.fees_paid += fill.fee
            self.credit(-fill.fee, "fee", ref=fill.order_id,
                        note=f"{fill.symbol} execution fee", ts=fill.ts)

        self.volume_30d += inst.notional(fill.qty, fill.price) * rate
        return realized_account

    def _consume_lots(self, pos: Position, qty: float, price: float) -> float:
        """FIFO. Returns realized P&L in the instrument's quote currency."""
        remaining = qty
        realized = 0.0
        direction = 1.0 if pos.qty > 0 else -1.0
        while remaining > 1e-12 and pos.lots:
            lot = pos.lots[0]
            take = min(remaining, lot.qty)
            # Long: profit when the exit is above the lot. Short: the reverse.
            realized += (price - lot.price) * take * direction
            lot.qty -= take
            remaining -= take
            if lot.qty <= 1e-12:
                pos.lots.pop(0)
        if remaining > 1e-12:
            # Lots and quantity disagreed — fall back to average cost so the
            # books still balance rather than silently dropping the P&L.
            realized += (price - pos.avg_price) * remaining * direction
        return realized

    def accrue(self, amount: float, kind: str, symbol: str = "",
               ts: datetime | None = None) -> None:
        """Charge financing (swap, borrow). Positive is a cost."""
        if abs(amount) < 1e-9:
            return
        self.fees_paid += amount
        if symbol:
            self.position(symbol).fees_paid += amount
        self.credit(-amount, kind, ref=symbol, note=f"{kind} on {symbol}", ts=ts)

    # ---------------------------------------------------------------- valuation

    def market_value(self) -> float:
        """Total position value in the account currency (shorts are negative)."""
        total = 0.0
        for pos in self.open_positions():
            inst = resolve(pos.symbol)
            px = self.price_of(pos.symbol) or pos.avg_price
            total += pos.qty * px * inst.multiplier * self.fx_rate(inst.quote_ccy)
        return total

    def unrealized_pnl(self) -> float:
        total = 0.0
        for pos in self.open_positions():
            inst = resolve(pos.symbol)
            px = self.price_of(pos.symbol)
            if px <= 0:
                continue
            total += ((px - pos.avg_price) * pos.qty * inst.multiplier
                      * self.fx_rate(inst.quote_ccy))
        return total

    def cash_total(self) -> float:
        return sum(self.to_account(amt, ccy) for ccy, amt in self.cash.items())

    def equity(self) -> float:
        """Net liquidation value: cash plus the market value of everything held."""
        return round_money(self.cash_total() + self.market_value(), self.base_ccy)

    # ------------------------------------------------------------------ margin

    def margin_used(self) -> float:
        """Initial margin currently posted against open positions."""
        total = 0.0
        for pos in self.open_positions():
            inst = resolve(pos.symbol)
            px = self.price_of(pos.symbol) or pos.avg_price
            total += (inst.initial_margin(abs(pos.qty), px)
                      * self.fx_rate(inst.quote_ccy))
        return total

    def maintenance_margin(self) -> float:
        """Equity must stay above this or the account is called."""
        total = 0.0
        for pos in self.open_positions():
            inst = resolve(pos.symbol)
            px = self.price_of(pos.symbol) or pos.avg_price
            rate = inst.maintenance_margin
            if rate <= 0:
                # A cash instrument still ties up its full value.
                rate = 1.0 / max(1.0, inst.max_leverage)
            total += inst.notional(abs(pos.qty), px) * rate * self.fx_rate(inst.quote_ccy)
        return total

    def available_funds(self) -> float:
        """Equity not already committed as initial margin."""
        return self.equity() - self.margin_used()

    def excess_liquidity(self) -> float:
        """Cushion above the maintenance requirement. Negative means a call."""
        return self.equity() - self.maintenance_margin()

    def buying_power(self, symbol: str | None = None) -> float:
        """Notional this account can still put on, in the account currency.

        Leverage is per-instrument: the same $10,000 supports $20,000 of AAPL
        (Reg-T 2:1), $500,000 of EUR/USD (50:1), and $10,000 of spot BTC.
        Quoting one number for all three would be wrong for at least two.
        """
        funds = max(0.0, self.available_funds())
        if symbol is None:
            return funds
        return funds * max(1.0, resolve(symbol).max_leverage)

    def margin_call(self) -> bool:
        return self.excess_liquidity() < 0 and bool(self.open_positions())

    def margin_utilization(self) -> float:
        eq = self.equity()
        return (self.maintenance_margin() / eq) if eq > 0 else 0.0

    def liquidation_order(self) -> list[Position]:
        """Which positions a broker would close first in a call.

        Biggest maintenance requirement first: it restores the most cushion per
        position closed, which is how a real risk desk unwinds an account.
        """
        scored = []
        for pos in self.open_positions():
            inst = resolve(pos.symbol)
            px = self.price_of(pos.symbol) or pos.avg_price
            req = inst.notional(abs(pos.qty), px) * max(
                inst.maintenance_margin, 1.0 / max(1.0, inst.max_leverage))
            scored.append((req * self.fx_rate(inst.quote_ccy), pos))
        return [p for _, p in sorted(scored, key=lambda t: -t[0])]

    # ---------------------------------------------------------------- summary

    def snapshot(self) -> dict:
        eq = self.equity()
        return {
            "account_id": self.account_id,
            "ts": iso(utcnow()),
            "cash": round_money(self.cash_total(), self.base_ccy),
            "market_value": round_money(self.market_value(), self.base_ccy),
            "equity": eq,
            "realized_pnl": round_money(self.realized_pnl, self.base_ccy),
            "unrealized_pnl": round_money(self.unrealized_pnl(), self.base_ccy),
            "total_pnl": round_money(
                eq - self.starting_cash - self._net_deposits(), self.base_ccy),
            "return_pct": ((eq / self.starting_cash - 1.0) * 100.0
                           if self.starting_cash > 0 else 0.0),
            "fees_paid": round_money(self.fees_paid, self.base_ccy),
            "margin_used": round_money(self.margin_used(), self.base_ccy),
            "maintenance_margin": round_money(self.maintenance_margin(), self.base_ccy),
            "available_funds": round_money(self.available_funds(), self.base_ccy),
            "excess_liquidity": round_money(self.excess_liquidity(), self.base_ccy),
            "buying_power": round_money(self.buying_power("AAPL"), self.base_ccy),
            "margin_call": self.margin_call(),
            "margin_utilization": round(self.margin_utilization(), 4),
            "open_positions": len(self.open_positions()),
        }

    def _net_deposits(self) -> float:
        """Deposits and withdrawals after the opening balance.

        Without this, funding an account reads as profit — which would make the
        headline return number meaningless.
        """
        return sum(e.amount for e in self.ledger[1:]
                   if e.kind in ("deposit", "withdrawal"))

    def position_rows(self) -> list[dict]:
        rows = []
        for pos in sorted(self.open_positions(), key=lambda p: p.symbol):
            inst = resolve(pos.symbol)
            px = self.price_of(pos.symbol) or pos.avg_price
            rate = self.fx_rate(inst.quote_ccy)
            unreal = (px - pos.avg_price) * pos.qty * inst.multiplier * rate
            rows.append({
                "symbol": pos.symbol,
                "asset_class": inst.asset_class.value,
                "qty": pos.qty,
                "qty_fmt": inst.fmt_qty(abs(pos.qty)),
                "side": "long" if pos.is_long else "short",
                "avg_price": pos.avg_price,
                "last": px,
                "market_value": round_money(pos.qty * px * inst.multiplier * rate,
                                            self.base_ccy),
                "unrealized_pnl": round_money(unreal, self.base_ccy),
                "unrealized_pct": pos.unrealized_pct(px),
                "realized_pnl": round_money(pos.realized_pnl, self.base_ccy),
                "fees": round_money(pos.fees_paid, self.base_ccy),
                "lots": len(pos.lots),
                "opened_at": iso(pos.opened_at) if pos.opened_at else None,
            })
        return rows
