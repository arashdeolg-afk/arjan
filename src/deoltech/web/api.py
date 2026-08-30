"""JSON API.

Serves the live-updating parts of the UI and doubles as a programmable
interface: every endpoint accepts either a session cookie or a
`Authorization: Bearer dt_...` token, so a script can drive the same platform
the browser does, under the same permission checks.

Responses are deliberately plain — no envelope, no HATEOAS, just the object the
caller asked for — and errors return `{"error": "..."}` with a real status code.
"""

from __future__ import annotations

from datetime import datetime, timezone

from ..analytics import analyze, by_symbol
from ..clock import market_status
from ..engine.book import build_book
from ..engine.fees import compute_fees
from ..engine.matching import MatchContext
from ..feeds.base import FeedError
from ..instruments import catalog, resolve, search
from ..strategies import available as available_strategies
from ..types import Liquidity, Order, OrderType, Side, TimeInForce
from .server import HttpError, Request, Response

MAX_SYMBOLS_PER_REQUEST = 60


def _quote_dict(q, inst) -> dict:
    return {
        "symbol": q.symbol, "last": q.last, "bid": q.bid, "ask": q.ask,
        "open": q.open, "high": q.high, "low": q.low, "volume": q.volume,
        "prev_close": q.prev_close, "change": round(q.last - q.prev_close, 8),
        "change_pct": round(q.change_pct, 4), "ts": q.ts.isoformat(),
        "age_s": round(q.age_s(), 1), "source": q.source,
        "stale": "+stale" in (q.source or ""),
        "asset_class": inst.asset_class.value,
        "price_precision": inst.price_precision,
        "name": inst.name,
    }


def quotes(request: Request) -> Response:
    request.user.require("view.market")
    raw = request.query.get("symbols", "")
    symbols = [resolve(s).symbol for s in raw.split(",") if s.strip()]
    if not symbols:
        symbols = request.app.platform.service.watchlist(request.user.id)
    symbols = symbols[:MAX_SYMBOLS_PER_REQUEST]

    service = request.app.platform.service
    got = service.quotes(symbols)
    return Response.json({
        "quotes": {s: _quote_dict(q, resolve(s)) for s, q in got.items()},
        "missing": [s for s in symbols if s not in got],
        "feed": service.feed_health(),
        "ts": datetime.now(timezone.utc).isoformat(),
    })


def quote_one(request: Request) -> Response:
    request.user.require("view.market")
    symbol = resolve(request.params["symbol"]).symbol
    inst = resolve(symbol)
    try:
        q = request.app.platform.service.quote(symbol)
    except FeedError as e:
        raise HttpError(503, f"No market data for {symbol}: {e}")
    book = build_book(inst, q)
    data = _quote_dict(q, inst)
    data["book"] = {
        "bid": book.bid, "ask": book.ask, "bid_size": book.bid_size,
        "ask_size": book.ask_size, "spread_bps": round(book.spread_bps, 3),
        "synthetic": book.synthetic, "session": book.session.value,
    }
    data["market"] = market_status(inst.asset_class.value).label
    return Response.json(data)


def bars(request: Request) -> Response:
    request.user.require("view.market")
    symbol = resolve(request.query.get("symbol", "AAPL")).symbol
    interval = request.query.get("interval", "1d")
    if interval not in ("1m", "5m", "15m", "30m", "1h", "4h", "1d", "1w"):
        interval = "1d"
    limit = max(10, min(1000, int(request.query.get("limit", "200") or 200)))
    try:
        series = request.app.platform.service.bars(symbol, interval, limit)
    except FeedError as e:
        raise HttpError(503, f"No price history for {symbol}: {e}")
    return Response.json({
        "symbol": symbol, "interval": interval,
        "bars": [{"ts": b.ts.isoformat(), "open": b.open, "high": b.high,
                  "low": b.low, "close": b.close, "volume": b.volume}
                 for b in series],
    })


def account(request: Request) -> Response:
    request.user.require("view.account")
    service = request.app.platform.service
    service.refresh(request.account_id)
    broker = service.broker(request.account_id)
    return Response.json({
        "summary": broker.summary(),
        "positions": broker.portfolio.position_rows(),
        "orders": [{
            "id": o.id, "symbol": o.symbol, "side": o.side.value,
            "order_type": o.order_type.value, "qty": o.qty,
            "qty_fmt": resolve(o.symbol).fmt_qty(o.qty),
            "filled_qty": o.filled_qty, "limit_price": o.limit_price,
            "stop_price": o.stop_price, "status": o.status.value,
            "tif": o.tif.value, "created_at": o.created_at.isoformat(),
        } for o in broker.open_orders()],
    })


def equity_curve(request: Request) -> Response:
    request.user.require("view.account")
    broker = request.app.platform.service.broker(request.account_id)
    points = broker.equity_curve[-600:]
    return Response.json({
        "points": [{"ts": p.ts.isoformat(), "equity": round(p.equity, 2),
                    "cash": round(p.cash, 2),
                    "unrealized": round(p.unrealized, 2),
                    "realized": round(p.realized, 2)} for p in points],
    })


def blotter(request: Request) -> Response:
    request.user.require("view.blotter")
    broker = request.app.platform.service.broker(request.account_id)
    limit = max(1, min(1000, int(request.query.get("limit", "200") or 200)))
    return Response.json({"fills": broker.blotter(limit)})


def performance(request: Request) -> Response:
    request.user.require("view.analytics")
    broker = request.app.platform.service.broker(request.account_id)
    perf = analyze(broker.equity_curve, broker.fills)
    return Response.json({
        "performance": perf.to_dict(),
        "by_symbol": by_symbol(broker.fills),
    })


# ------------------------------------------------------------------- trading


def _build_order(request: Request) -> Order:
    """Turn form or JSON input into a validated Order. Raises HttpError(400)."""
    symbol = resolve(request.get("symbol", "")).symbol
    if not request.get("symbol", "").strip():
        raise HttpError(400, "A symbol is required.")
    inst = resolve(symbol)

    side_raw = request.get("side", "buy").lower()
    if side_raw not in ("buy", "sell"):
        raise HttpError(400, "Side must be 'buy' or 'sell'.")

    qty = request.get_float("qty", 0.0)
    if qty <= 0:
        raise HttpError(400, "Quantity must be greater than zero.")
    # Validate what the user typed, not what rounding turned it into: rounding
    # 0.5 shares down to 0 first would report "must be positive" for what is
    # really "this instrument does not trade in fractions".
    valid, why = inst.valid_qty(qty)
    if not valid:
        raise HttpError(400, f"{symbol}: {why}.")
    qty = inst.round_qty(qty)

    type_raw = request.get("order_type", "market").lower()
    try:
        order_type = OrderType(type_raw)
    except ValueError:
        raise HttpError(400, f"Unknown order type {type_raw!r}.")

    tif_raw = request.get("tif", "day").lower()
    try:
        tif = TimeInForce(tif_raw)
    except ValueError:
        raise HttpError(400, f"Unknown time in force {tif_raw!r}.")

    def optional_price(field: str) -> float | None:
        raw = request.get(field, "").strip()
        if not raw:
            return None
        value = request.get_float(field, 0.0)
        if value <= 0:
            raise HttpError(400, f"{field.replace('_', ' ')} must be positive.")
        return inst.round_price(value)

    limit_price = optional_price("limit_price")
    stop_price = optional_price("stop_price")
    take_profit = optional_price("take_profit")
    stop_loss = optional_price("stop_loss")
    trail_raw = request.get("trail_pct", "").strip()
    trail_pct = request.get_float("trail_pct", 0.0) if trail_raw else None

    if order_type in (OrderType.LIMIT, OrderType.STOP_LIMIT) and limit_price is None:
        raise HttpError(400, "A limit price is required for that order type.")
    if order_type in (OrderType.STOP, OrderType.STOP_LIMIT) and stop_price is None:
        raise HttpError(400, "A stop price is required for that order type.")
    if order_type is OrderType.TRAILING_STOP and not trail_pct:
        raise HttpError(400, "A trail percentage is required for a trailing stop.")

    try:
        return Order(
            symbol=symbol, side=Side(side_raw), qty=qty, order_type=order_type,
            limit_price=limit_price, stop_price=stop_price, trail_pct=trail_pct,
            tif=tif, take_profit=take_profit, stop_loss=stop_loss,
            post_only=request.get_bool("post_only"),
            reduce_only=request.get_bool("reduce_only"),
            allow_extended=request.get_bool("allow_extended"),
            tag=request.get("tag", "")[:60] or None,
        )
    except ValueError as e:
        raise HttpError(400, str(e))


def submit_order(request: Request) -> Response:
    request.user.require("trade.submit")
    order = _build_order(request)
    service = request.app.platform.service
    placed = service.submit(request.account_id, order)

    # Bracket children go through the same risk checks as any other order, so a
    # take-profit or stop-loss CAN be rejected — most often by the fat-finger
    # collar. That must never be silent: a filled entry whose stop-loss was
    # refused is an unprotected position, and the trader has to know now.
    broker = service.broker(request.account_id)
    children = [o for o in broker.orders.values() if o.parent_id == placed.id]
    warnings = [
        f"{(o.tag or 'protective order').split(':')[-1].replace('-', ' ')} "
        f"was rejected: {o.reject_reason}"
        for o in children if o.status.value == "rejected"
    ]
    if warnings and placed.filled_qty > 0:
        warnings.append("This position is NOT protected. Place the exit order "
                        "manually.")

    return Response.json({
        "id": placed.id, "symbol": placed.symbol, "side": placed.side.value,
        "status": placed.status.value, "qty": placed.qty,
        "filled_qty": placed.filled_qty,
        "avg_fill_price": placed.avg_fill_price,
        "fees_paid": round(placed.fees_paid, 4),
        "reject_reason": placed.reject_reason,
        "order_type": placed.order_type.value, "tif": placed.tif.value,
        "children": [{"id": o.id, "type": o.order_type.value,
                      "status": o.status.value, "tag": o.tag,
                      "price": o.limit_price or o.stop_price,
                      "reject_reason": o.reject_reason} for o in children],
        "warnings": warnings,
    })


def cancel_order(request: Request) -> Response:
    request.user.require("trade.cancel")
    ok = request.app.platform.service.cancel(request.account_id,
                                             request.params["order_id"])
    if not ok:
        raise HttpError(404, "That order is not working — it may already have "
                             "filled or been cancelled.")
    return Response.json({"cancelled": True, "id": request.params["order_id"]})


def close_position(request: Request) -> Response:
    request.user.require("trade.submit")
    symbol = resolve(request.params["symbol"]).symbol
    order = request.app.platform.service.close_position(request.account_id, symbol)
    if order is None:
        raise HttpError(404, f"No open position in {symbol}.")
    return Response.json({
        "id": order.id, "symbol": order.symbol, "status": order.status.value,
        "filled_qty": order.filled_qty, "avg_fill_price": order.avg_fill_price,
        "reject_reason": order.reject_reason,
    })


def preview(request: Request) -> Response:
    """Cost and risk of an order BEFORE it is placed.

    Shows the estimated fill including the spread it must cross, the fees, the
    margin it consumes, and the pre-trade risk verdict. Surfacing this before
    the click is the difference between learning what a trade costs and finding
    out afterwards.
    """
    request.user.require("view.account")
    order = _build_order(request)
    inst = resolve(order.symbol)
    service = request.app.platform.service
    broker = service.broker(request.account_id)

    try:
        q = service.quote(order.symbol)
    except FeedError as e:
        raise HttpError(503, f"No market data for {order.symbol}: {e}")

    ctx = MatchContext.build(inst, q)
    if order.order_type is OrderType.LIMIT and order.limit_price:
        est = order.limit_price
        liquidity = (Liquidity.TAKER if ctx.book.is_marketable(order.side, est)
                     else Liquidity.MAKER)
    else:
        est = ctx.book.touch(order.side)
        liquidity = Liquidity.TAKER
        est = broker.matcher.slippage.apply(
            inst, order.side, order.qty, est, q, order.id).price

    rate = broker.portfolio.fx_rate(inst.quote_ccy)
    fees = compute_fees(inst, order.side, order.qty, est,
                        schedule=broker.fees, liquidity=liquidity,
                        volume_30d=broker.portfolio.volume_30d,
                        quote_to_account=rate)
    notional = inst.notional(order.qty, est) * rate
    margin = inst.initial_margin(order.qty, est) * rate
    decision = broker.risk.check(order, broker.portfolio, broker.risk_state(),
                                 q.last)

    return Response.json({
        "symbol": order.symbol, "side": order.side.value, "qty": order.qty,
        "estimated_price": est, "price_precision": inst.price_precision,
        "reference_mid": round(ctx.book.mid, 8),
        "spread_bps": round(ctx.book.spread_bps, 3),
        "spread_is_modelled": ctx.book.synthetic,
        "slippage_bps": round(abs(est - ctx.book.mid) / ctx.book.mid * 10_000, 3)
                        if ctx.book.mid else 0.0,
        "notional": round(notional, 2),
        "fees": round(fees.total, 4),
        "fee_breakdown": dict(fees.items()),
        "liquidity": liquidity.value,
        "margin_required": round(margin, 2),
        "buying_power_after": round(
            max(0.0, broker.portfolio.available_funds() - margin), 2),
        "allowed": decision.ok,
        "reason": decision.reason,
        "code": decision.code,
        "session": ctx.session.value,
    })


def max_qty(request: Request) -> Response:
    request.user.require("view.account")
    symbol = resolve(request.query.get("symbol", "AAPL")).symbol
    side = Side(request.query.get("side", "buy").lower()
                if request.query.get("side", "buy").lower() in ("buy", "sell")
                else "buy")
    service = request.app.platform.service
    broker = service.broker(request.account_id)
    try:
        price = service.quote(symbol).last
    except FeedError:
        price = broker.portfolio.price_of(symbol)
    qty = broker.risk.max_qty(symbol, side, broker.portfolio, price)
    return Response.json({"symbol": symbol, "side": side.value, "max_qty": qty,
                          "price": price})


def instruments(request: Request) -> Response:
    request.user.require("view.market")
    query = request.query.get("q", "").strip()
    items = search(query, 50) if query else catalog(
        request.query.get("class") or None)[:200]
    return Response.json({"instruments": [{
        "symbol": i.symbol, "name": i.name, "asset_class": i.asset_class.value,
        "tick_size": i.tick_size, "min_qty": i.min_qty,
        "max_leverage": i.max_leverage, "shortable": i.shortable,
        "quote_ccy": i.quote_ccy, "price_precision": i.price_precision,
    } for i in items]})


def strategies(request: Request) -> Response:
    request.user.require("run.backtest")
    return Response.json({"strategies": available_strategies()})


def watchlist(request: Request) -> Response:
    service = request.app.platform.service
    if request.method == "POST":
        request.user.require("watchlist.edit")
        raw = request.get("symbols", "")
        symbols = [s for s in raw.replace("\n", ",").split(",") if s.strip()]
        return Response.json({"watchlist": service.set_watchlist(
            request.user.id, symbols)})
    return Response.json({"watchlist": service.watchlist(request.user.id)})


def health(request: Request) -> Response:
    """Unauthenticated liveness probe, for load balancers and uptime checks.

    Reports whether the process is serving and whether market data is live, and
    nothing else — a health endpoint that leaks user counts or version strings
    is a reconnaissance endpoint.
    """
    platform = request.app.platform
    try:
        feed = platform.service.feed_health()
        # Report what is actually being served. An instance running the
        # simulator is not "live" market data, and a health endpoint that says
        # otherwise is the first place a misconfiguration hides.
        if feed["mode"] == "synthetic":
            market = "simulated"
        elif feed["degraded"]:
            market = "degraded"
        elif feed["ok"]:
            market = "live"
        else:
            market = "down"
        return Response.json({
            "status": "ok",
            "market_data": market,
            "time": datetime.now(timezone.utc).isoformat(),
        })
    except Exception:                                      # noqa: BLE001
        return Response.json({"status": "degraded"}, 503)
