"""Pre-trade risk.

Every order passes through here before it can reach the book. The checks are
ordered cheapest-first, and each one returns a machine-readable code alongside
its human explanation so the UI can show a trader *why* they were stopped
rather than a generic rejection.

These are the controls a real desk runs, and they exist for reasons a paper
trader should learn before a funded one does:

* **Buying power and margin** — you cannot buy what you cannot fund, and
  leverage differs per asset class.
* **Fat-finger collars** — a limit 40% away from the market is almost always a
  typo or a misplaced decimal, not an opinion.
* **Position concentration** — one name at 90% of the account is not a strategy.
* **Pattern day trader** — under $25,000 of equity, US rules cap you at three
  day trades in five business days. Learning this in a simulator is much
  cheaper than learning it from a broker's restriction notice.
* **Daily loss limit and kill switch** — the control that ends a bad day at a
  number chosen in the morning rather than one chosen at 3pm while losing.
* **Short availability** — not everything can be borrowed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from ..clock import Session, session_for
from ..instruments import Instrument, resolve
from ..portfolio import Portfolio
from ..types import AssetClass, Order, OrderType, Side


@dataclass(frozen=True, slots=True)
class RiskDecision:
    ok: bool
    code: str = "ok"
    reason: str = ""

    def __bool__(self) -> bool:
        return self.ok


APPROVED = RiskDecision(True)


def deny(code: str, reason: str) -> RiskDecision:
    return RiskDecision(False, code, reason)


@dataclass
class RiskLimits:
    """One account's risk configuration. Admin-editable."""

    max_order_notional: float = 1_000_000.0
    max_position_notional: float = 500_000.0
    # Concentration is measured as the MARGIN a position requires divided by
    # equity — not notional divided by equity. On a leveraged instrument those
    # differ by the leverage factor: a perfectly ordinary 100k EUR/USD position
    # is 1,085% of a $10k account by notional and 22% by margin. Measuring
    # notional would make retail FX and crypto uniformly un-tradeable while
    # waving through an over-leveraged equity position. 1.0 = "you may commit
    # all your buying power to one instrument", the broker default; tighten it
    # for a managed account.
    max_position_pct_equity: float = 1.0
    max_open_orders: int = 200
    max_leverage_override: float = 0.0         # 0 = use the instrument's own
    fat_finger_pct: float = 25.0               # limit/stop distance from last
    daily_loss_limit: float = 0.0              # 0 = disabled; else account ccy
    daily_loss_limit_pct: float = 0.0          # 0 = disabled; else % of equity
    allow_shorting: bool = True
    allow_margin: bool = True
    enforce_pdt: bool = True
    pdt_equity_threshold: float = 25_000.0
    pdt_max_day_trades: int = 3
    allow_extended_hours: bool = True
    trading_halted: bool = False               # the kill switch
    halt_reason: str = ""
    allowed_asset_classes: tuple[str, ...] = ("equity", "crypto", "fx")


@dataclass
class RiskState:
    """What the checks need to know about the account beyond the portfolio."""

    open_orders: int = 0
    day_trades_5d: int = 0
    realized_today: float = 0.0
    start_of_day_equity: float = 0.0


class RiskEngine:
    def __init__(self, limits: RiskLimits | None = None):
        self.limits = limits or RiskLimits()

    def check(self, order: Order, portfolio: Portfolio, state: RiskState,
              last_price: float, now: datetime | None = None) -> RiskDecision:
        lim = self.limits
        inst = resolve(order.symbol)
        now = now or datetime.now(tz=__import__("datetime").timezone.utc)

        # --- 0. Kill switch. Nothing gets past a halted account. ------------
        if lim.trading_halted:
            return deny("halted",
                        lim.halt_reason or "trading is halted on this account")

        if inst.asset_class.value not in lim.allowed_asset_classes:
            return deny("asset_class_blocked",
                        f"{inst.asset_class.value} trading is not enabled on this account")

        # --- 1. Contract validity ------------------------------------------
        valid, why = inst.valid_qty(order.qty)
        if not valid:
            return deny("invalid_qty", why)

        if state.open_orders >= lim.max_open_orders:
            return deny("too_many_orders",
                        f"open order limit reached ({lim.max_open_orders})")

        if last_price <= 0:
            return deny("no_market_data",
                        f"no current price for {order.symbol}; cannot risk-check the order")

        # --- 2. Session ------------------------------------------------------
        session = session_for(inst.asset_class.value, now)
        if session is Session.CLOSED and order.tif.value in ("ioc", "fok"):
            return deny("market_closed",
                        f"{order.symbol} market is closed; an immediate-or-cancel "
                        f"order cannot execute")
        if (session in (Session.PREMARKET, Session.AFTERHOURS)
                and order.allow_extended and not lim.allow_extended_hours):
            return deny("extended_hours_blocked",
                        "extended-hours trading is not enabled on this account")

        # --- 3. Fat-finger collar -------------------------------------------
        for label, price in (("limit", order.limit_price), ("stop", order.stop_price)):
            if price is None or price <= 0:
                continue
            drift = abs(price - last_price) / last_price * 100.0
            if drift > lim.fat_finger_pct:
                return deny("price_collar",
                            f"{label} price {inst.fmt_price(price)} is {drift:.1f}% away "
                            f"from the last trade of {inst.fmt_price(last_price)} "
                            f"(limit {lim.fat_finger_pct:.0f}%)")

        # --- 4. Sizing --------------------------------------------------------
        rate = portfolio.fx_rate(inst.quote_ccy)
        notional = inst.notional(order.qty, order.limit_price or last_price) * rate
        if notional > lim.max_order_notional:
            return deny("order_too_large",
                        f"order notional {notional:,.0f} exceeds the per-order limit "
                        f"of {lim.max_order_notional:,.0f}")

        pos = portfolio.positions.get(order.symbol.upper())
        current_qty = pos.qty if pos else 0.0
        signed = order.side.sign * order.qty
        resulting_qty = current_qty + signed
        reduces = abs(resulting_qty) < abs(current_qty) or (
            current_qty != 0 and (current_qty > 0) != (signed > 0))

        # --- 5. reduce_only ---------------------------------------------------
        if order.reduce_only:
            if current_qty == 0:
                return deny("reduce_only_no_position",
                            "reduce-only order with no open position to reduce")
            if (current_qty > 0) == (signed > 0):
                return deny("reduce_only_wrong_side",
                            "reduce-only order would increase the position")

        # --- 6. Shorting ------------------------------------------------------
        if resulting_qty < -1e-12 and current_qty <= 0:
            if not lim.allow_shorting:
                return deny("shorting_disabled",
                            "short selling is not enabled on this account")
            if not inst.shortable:
                return deny("not_shortable", f"{order.symbol} cannot be borrowed to short")

        # --- 7. Concentration ---------------------------------------------------
        equity = portfolio.equity()
        resulting_notional = inst.notional(abs(resulting_qty), last_price) * rate
        effective_leverage = lim.max_leverage_override or inst.max_leverage
        if not lim.allow_margin:
            effective_leverage = 1.0
        resulting_margin = resulting_notional / max(1.0, effective_leverage)
        if not reduces:
            if resulting_notional > lim.max_position_notional:
                return deny("position_too_large",
                            f"resulting position of {resulting_notional:,.0f} exceeds "
                            f"the per-symbol limit of {lim.max_position_notional:,.0f}")
            if equity > 0 and lim.max_position_pct_equity > 0:
                pct = resulting_margin / equity
                if pct > lim.max_position_pct_equity:
                    return deny("concentration",
                                f"position would commit {pct * 100:.0f}% of account "
                                f"equity as margin (limit "
                                f"{lim.max_position_pct_equity * 100:.0f}%)")

        # --- 8. Buying power ------------------------------------------------
        if not reduces:
            leverage = lim.max_leverage_override or inst.max_leverage
            if not lim.allow_margin:
                leverage = 1.0
            required = notional / max(1.0, leverage)
            available = portfolio.available_funds()
            if required > available + 1e-6:
                return deny("insufficient_buying_power",
                            f"needs {required:,.2f} of margin, account has "
                            f"{max(0.0, available):,.2f} available "
                            f"({leverage:g}:1 on {order.symbol})")

        # --- 9. Existing margin call ------------------------------------------
        if portfolio.margin_call() and not reduces:
            return deny("margin_call",
                        "account is in a margin call; only risk-reducing orders "
                        "are accepted until it is cured")

        # --- 10. Pattern day trader -------------------------------------------
        if (lim.enforce_pdt and inst.asset_class is AssetClass.EQUITY
                and equity < lim.pdt_equity_threshold
                and state.day_trades_5d >= lim.pdt_max_day_trades and reduces):
            return deny("pdt_restriction",
                        f"pattern day trader rule: {state.day_trades_5d} day trades in "
                        f"5 business days with equity under "
                        f"{lim.pdt_equity_threshold:,.0f}")

        # --- 11. Daily loss limit ---------------------------------------------
        if not reduces:
            loss = state.start_of_day_equity - equity
            if lim.daily_loss_limit > 0 and loss >= lim.daily_loss_limit:
                return deny("daily_loss_limit",
                            f"daily loss of {loss:,.2f} has reached the limit of "
                            f"{lim.daily_loss_limit:,.2f}; new risk is blocked "
                            f"until tomorrow")
            if (lim.daily_loss_limit_pct > 0 and state.start_of_day_equity > 0
                    and loss / state.start_of_day_equity * 100.0
                    >= lim.daily_loss_limit_pct):
                return deny("daily_loss_limit",
                            f"daily loss of {loss / state.start_of_day_equity * 100:.1f}% "
                            f"has reached the {lim.daily_loss_limit_pct:.1f}% limit")

        return APPROVED

    # ------------------------------------------------------------------ sizing

    def max_qty(self, symbol: str, side: Side, portfolio: Portfolio,
                price: float) -> float:
        """Largest quantity this account could put on right now.

        Powers the "Max" button on an order ticket. Returns the *binding*
        constraint's answer — whichever of buying power, per-order notional,
        per-position notional or concentration bites first.
        """
        lim = self.limits
        inst = resolve(symbol)
        if price <= 0:
            return 0.0
        rate = portfolio.fx_rate(inst.quote_ccy)
        unit = price * inst.multiplier * rate
        if unit <= 0:
            return 0.0

        leverage = lim.max_leverage_override or inst.max_leverage
        if not lim.allow_margin:
            leverage = 1.0
        equity = portfolio.equity()

        caps = [
            max(0.0, portfolio.available_funds()) * leverage / unit,
            lim.max_order_notional / unit,
            lim.max_position_notional / unit,
        ]
        if equity > 0 and lim.max_position_pct_equity > 0:
            # Margin-based, matching `check`: the cap is on committed margin,
            # so on a 50:1 pair it permits 50x the notional it would on cash.
            caps.append(equity * lim.max_position_pct_equity * leverage / unit)

        pos = portfolio.positions.get(symbol.upper())
        if pos and not pos.is_flat and (pos.qty > 0) == (side is Side.BUY):
            # Adding to an existing position: the caps apply to the total.
            caps = [c - abs(pos.qty) for c in caps]

        return max(0.0, inst.round_qty(min(caps)))
