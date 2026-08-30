"""Page handlers.

Each function takes a `Request` and returns HTML. Anything that mutates state
goes through the service layer, and anything privileged calls `user.require()`
first — authorization is checked at the point of action, not merely hidden in
the navigation, because a hidden link is not a permission check.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from ..analytics import MIN_TRADES, analyze, by_symbol
from ..auth import (
    AuthError, PermissionDenied, Role, active_sessions, change_own_password,
    create_api_token, create_user, delete_user, generate_password, list_api_tokens,
    list_users, reset_password, revoke_api_token, set_role, set_status,
)
from ..backtest import Backtester
from ..clock import market_status
from ..db import audit, audit_trail, get_setting, set_setting, stats
from ..engine.fees import round_trip_cost_bps
from ..instruments import AssetClass, DEFAULT_WATCHLIST, catalog, resolve, search
from ..strategies import available as available_strategies, get as get_strategy
from ..types import OrderType, Side, TimeInForce
from .server import HttpError, Request, Response
from .templates import (
    alert, badge, card, esc, layout, money, pnl_class, signed, stat, table,
)


# --------------------------------------------------------------- helpers


def shell(request: Request, title: str, body: str, active: str = "/",
          **kwargs) -> Response:
    """Wrap page content in the application shell."""
    platform = request.app.platform
    user = request.user
    summary = None
    if user and request.account_id:
        try:
            summary = platform.service.broker(request.account_id).summary()
        except Exception:                                  # noqa: BLE001
            summary = None
    return Response.html(layout(
        title=title, body=body, user=user, active=active,
        csrf=request.app.csrf_token(request.session_token),
        ticker_symbols=platform.service.watchlist(user.id) if user else [],
        summary=summary, feed=platform.service.feed_health(), **kwargs))


def _quote_or_none(request: Request, symbol: str):
    try:
        return request.app.platform.service.quote(symbol)
    except Exception:                                      # noqa: BLE001
        return None


def _flash(request: Request) -> str:
    """Render a pending one-shot message, or an ?ok=/?error= query parameter.

    The one-shot store is checked first because that is where anything
    sensitive lives — a new password or API token must never ride in a URL,
    which would put it in the access log and the browser's history.
    """
    from . import flash
    if pending := flash.take(request.session_token):
        kind, message = pending
        return alert(message[:600], kind)
    if msg := request.query.get("error"):
        return alert(msg[:400], "error")
    if msg := request.query.get("ok"):
        return alert(msg[:400], "ok")
    if msg := request.query.get("warn"):
        return alert(msg[:400], "warn")
    return ""


# ------------------------------------------------------------- dashboard


def dashboard(request: Request) -> Response:
    platform = request.app.platform
    service = platform.service
    broker = service.broker(request.account_id)
    service.refresh(request.account_id)
    summary = broker.summary()
    positions = broker.portfolio.position_rows()

    call_banner = ""
    if summary.get("margin_call"):
        call_banner = alert(
            "MARGIN CALL — account equity is below the maintenance requirement. "
            "Positions will be liquidated largest-first until it is cured.",
            "error")
    halted = ""
    if summary.get("trading_halted"):
        halted = alert(f"Trading is halted on this account: "
                       f"{summary.get('halt_reason') or 'contact an administrator'}",
                       "warn")

    stats_row = f"""
    <div class="grid cols-4 mb-1">
      {stat("Account equity", money(summary['equity']),
            sub=f"started at {money(summary['start_of_day_equity'])} today",
            value_id="stat-equity")}
      {stat("Day P&L", signed(summary['day_pnl']),
            value_class=pnl_class(summary['day_pnl']), value_id="stat-day-pnl",
            sub=f"{signed(summary['return_pct'], 2)}% since inception")}
      {stat("Unrealized", signed(summary['unrealized_pnl']),
            value_class=pnl_class(summary['unrealized_pnl']),
            value_id="stat-unrealized",
            sub=f"realized {signed(summary['realized_pnl'])}")}
      {stat("Buying power", money(summary['buying_power']), value_id="stat-bp",
            sub=f"margin used {money(summary['margin_used'])}")}
    </div>"""

    pos_rows = [[
        f'<a href="/terminal?symbol={esc(p["symbol"])}"><strong>{esc(p["symbol"])}</strong></a> '
        + badge(p["side"], "up" if p["side"] == "long" else "down"),
        p["qty_fmt"], money(p["avg_price"], 4), money(p["last"], 4),
        money(p["market_value"]),
        f'<span class="{pnl_class(p["unrealized_pnl"])}">{signed(p["unrealized_pnl"])}</span>',
        f'<span class="{pnl_class(p["unrealized_pct"])}">{signed(p["unrealized_pct"], 2)}%</span>',
        f'<button class="btn btn-sm btn-danger" data-close="{esc(p["symbol"])}">Close</button>',
    ] for p in positions]

    positions_card = card(
        "Open positions",
        table(["Symbol", "Qty", "Avg price", "Last", "Value", "Unrealized",
               "Return", ""], pos_rows,
              empty="No open positions. Use the Terminal to place a trade.",
              body_id="positions-body", numeric={1, 2, 3, 4, 5, 6}),
        actions=('<a class="btn btn-sm" href="/terminal">Trade</a>'
                 '<form method="post" action="/actions/flatten" class="m-0">'
                 f'<input type="hidden" name="csrf_token" value="{esc(request.app.csrf_token(request.session_token))}">'
                 '<button class="btn btn-sm btn-danger" type="submit" '
                 'data-confirm="Close every open position at the market?">'
                 'Flatten all</button></form>'),
        flush=True, subtitle=f"{len(positions)} open")

    working = broker.open_orders()
    order_rows = [[
        f"<strong>{esc(o.symbol)}</strong>",
        badge(o.side.value, "up" if o.side is Side.BUY else "down"),
        esc(o.order_type.value),
        resolve(o.symbol).fmt_qty(o.qty),
        money(o.limit_price or o.stop_price, 4) if (o.limit_price or o.stop_price) else "mkt",
        badge(o.status.value),
        f'<button class="btn btn-sm btn-danger" data-cancel="{esc(o.id)}">Cancel</button>',
    ] for o in working]
    orders_card = card(
        "Working orders",
        table(["Symbol", "Side", "Type", "Qty", "Price", "Status", ""],
              order_rows, empty="No working orders.", body_id="orders-body",
              numeric={3, 4}),
        flush=True, subtitle=f"{len(working)} live")

    equity_card = card(
        "Equity curve",
        '<div id="equity-host" class="h-spark"></div>',
        subtitle="account value over time")

    perf = analyze(broker.equity_curve, broker.fills)
    verdict = card("Performance read", f"""
        <p class="mb-head">{esc(perf.verdict())}</p>
        <div class="kv"><span class="k">Closed trades</span>
          <span class="v">{perf.trades}</span></div>
        <div class="kv"><span class="k">Median trade</span>
          <span class="v {pnl_class(perf.median_trade_pnl)}">
          {signed(perf.median_trade_pnl)}</span></div>
        <div class="kv"><span class="k">Mean trade</span>
          <span class="v {pnl_class(perf.mean_trade_pnl)}">
          {signed(perf.mean_trade_pnl)}</span></div>
        <div class="kv"><span class="k">Win rate</span>
          <span class="v">{money(perf.win_rate_pct, 1)}%</span></div>
        <div class="kv"><span class="k">Max drawdown</span>
          <span class="v down">{money(perf.max_drawdown_pct, 2)}%</span></div>
        <div class="kv"><span class="k">Fees paid</span>
          <span class="v">{money(perf.total_fees)}</span></div>
        <p class="mt-only-lg"><a href="/analytics">Full performance report →</a></p>
        """)

    body = (_flash(request) + call_banner + halted + stats_row
            + f'<div class="split"><div>{equity_card}{positions_card}{orders_card}</div>'
            + f'<div>{verdict}{_market_clock_card()}</div></div>')
    return shell(request, "Dashboard", body, "/")


def _market_clock_card() -> str:
    rows = []
    for ac, label in [("equity", "US equities"), ("crypto", "Crypto"),
                      ("fx", "Forex")]:
        st = market_status(ac)
        kind = {"OPEN": "up", "PRE-MARKET": "warn", "AFTER-HOURS": "warn",
                "CLOSED": "neutral"}[st.label]
        when = ""
        if st.opens_at:
            when = f'<span class="faint">opens {st.opens_at:%a %H:%M} UTC</span>'
        elif st.closes_at:
            when = f'<span class="faint">closes {st.closes_at:%H:%M} UTC</span>'
        rows.append(f'<div class="kv"><span class="k">{esc(label)}</span>'
                    f'<span class="v">{badge(st.label, kind)} {when}</span></div>')
    return card("Market hours", "".join(rows))


# --------------------------------------------------------------- terminal


def terminal(request: Request) -> Response:
    platform = request.app.platform
    service = platform.service
    symbol = resolve(request.query.get("symbol", "AAPL")).symbol
    inst = resolve(symbol)
    interval = request.query.get("interval", "1d")
    if interval not in ("5m", "15m", "1h", "1d", "1w"):
        interval = "1d"

    quote = _quote_or_none(request, symbol)
    broker = service.broker(request.account_id)
    service.refresh(request.account_id, [symbol])
    position = broker.portfolio.position(symbol)
    csrf = request.app.csrf_token(request.session_token)

    if quote is None:
        price_block = alert(f"No market data available for {symbol} right now.",
                            "warn")
        last = position.avg_price or 0.0
    else:
        last = quote.last
        chg = quote.change_pct
        stale = "+stale" in (quote.source or "")
        price_block = f"""
        <div class="row gap-lg baseline">
          <div>
            <div class="price-hero"
                 class="mono">{money(last, inst.price_precision)}</div>
            <div class="mono {pnl_class(chg)} fs-xl">
              {signed(quote.last - quote.prev_close, inst.price_precision)}
              ({signed(chg, 2)}%)</div>
          </div>
          <div class="muted-box fs-md">
            <div class="kv"><span class="k">Open</span><span class="v">
              {money(quote.open, inst.price_precision)}</span></div>
            <div class="kv"><span class="k">Day range</span><span class="v">
              {money(quote.low, inst.price_precision)} – {money(quote.high, inst.price_precision)}</span></div>
            <div class="kv"><span class="k">Volume</span><span class="v">
              {money(quote.volume, 0)}</span></div>
          </div>
          <div class="muted-box fs-md">
            <div class="kv"><span class="k">Source</span><span class="v">
              {esc(quote.source)}</span></div>
            <div class="kv"><span class="k">Quote age</span><span class="v">
              {money(quote.age_s(), 0)}s</span></div>
            <div class="kv"><span class="k">Round-trip cost</span><span class="v">
              {money(round_trip_cost_bps(inst, 10_000), 1)} bps</span></div>
          </div>
        </div>
        {alert("This price is stale — the live feed is unreachable and this is the "
               "last value received.", "warn") if stale else ""}"""

    pos_block = ""
    if not position.is_flat:
        upl = position.unrealized_pnl(last)
        pos_block = card("Your position", f"""
          <div class="kv"><span class="k">Side</span><span class="v">
            {badge('long' if position.is_long else 'short',
                   'up' if position.is_long else 'down')}</span></div>
          <div class="kv"><span class="k">Quantity</span><span class="v">
            {inst.fmt_qty(abs(position.qty))}</span></div>
          <div class="kv"><span class="k">Average price</span><span class="v">
            {money(position.avg_price, inst.price_precision)}</span></div>
          <div class="kv"><span class="k">Unrealized</span>
            <span class="v {pnl_class(upl)}">{signed(upl)}</span></div>
          <div class="kv"><span class="k">Realized</span>
            <span class="v {pnl_class(position.realized_pnl)}">
            {signed(position.realized_pnl)}</span></div>
          <button class="btn btn-sm btn-danger btn-block mt-md"
                  data-close="{esc(symbol)}">Close position</button>""")

    can_trade = request.user.can("trade.submit")
    ticket = _order_ticket(symbol, inst, last, csrf) if can_trade else card(
        "Order ticket",
        alert("Your account has view-only access and cannot place orders.", "info"))

    intervals = "".join(
        f'<button data-interval="{i}" class="{"active" if i == interval else ""}">'
        f'{i}</button>' for i in ("5m", "15m", "1h", "1d", "1w"))
    chart = card(
        f"{symbol} · {inst.name}",
        f'<div id="chart-host" data-symbol="{esc(symbol)}" '
        f'data-interval="{esc(interval)}" class="h-chart"></div>',
        actions=f'<div class="chart-controls">{intervals}</div>',
        subtitle=f"{inst.asset_class.value} · tick {inst.tick_size} · "
                 f"{'up to ' + str(int(inst.max_leverage)) + ':1 leverage' if inst.is_leveraged else 'cash only'}")

    search_form = f"""
    <form method="get" action="/terminal" class="row mb-1">
      <input type="text" name="symbol" value="{esc(symbol)}" placeholder="Symbol" class="w-lg" list="symbol-list" autocomplete="off">
      <datalist id="symbol-list">
        {''.join(f'<option value="{esc(i.symbol)}">{esc(i.name)}</option>'
                 for i in catalog()[:120])}
      </datalist>
      <button class="btn" type="submit">Load</button>
      <span class="faint fs-base">
        Stocks, crypto (BTCUSD) and forex (EURUSD) all work here.</span>
    </form>"""

    body = (_flash(request) + search_form + price_block
            + f'<div class="split mt-1"><div>{chart}'
            + _recent_fills_card(broker, symbol) + '</div>'
            + f'<div>{ticket}{pos_block}</div></div>')
    return shell(request, f"{symbol} Terminal", body, "/terminal")


def _order_ticket(symbol: str, inst, last: float, csrf: str) -> str:
    default_qty = 1 if inst.asset_class is AssetClass.EQUITY else (
        inst.min_qty * 10 if inst.asset_class is AssetClass.FX else 0.01)
    return card("Order ticket", f"""
    <form id="order-ticket" data-symbol="{esc(symbol)}">
      <input type="hidden" name="csrf_token" value="{esc(csrf)}">
      <input type="hidden" name="symbol" value="{esc(symbol)}">
      <input type="hidden" name="side" id="ticket-side" value="buy">
      <div class="seg mb-sm">
        <button type="button" data-side="buy" class="active buy-active">Buy</button>
        <button type="button" data-side="sell">Sell</button>
      </div>
      <div class="field">
        <label for="ticket-type">Order type</label>
        <select id="ticket-type" name="order_type">
          <option value="market">Market</option>
          <option value="limit">Limit</option>
          <option value="stop">Stop</option>
          <option value="stop_limit">Stop limit</option>
          <option value="trailing_stop">Trailing stop</option>
        </select>
      </div>
      <div class="field">
        <label for="ticket-qty">Quantity
          <span class="faint">(min {inst.fmt_qty(inst.min_qty)})</span></label>
        <div class="row gap-xs">
          <input id="ticket-qty" name="qty" type="text" inputmode="decimal"
                 value="{default_qty}" class="flex-1">
          <button class="btn btn-sm" type="button" id="ticket-max">Max</button>
        </div>
      </div>
      <div class="field" id="row-limit" hidden>
        <label for="ticket-limit">Limit price</label>
        <input id="ticket-limit" name="limit_price" type="text" inputmode="decimal"
               value="{money(last, inst.price_precision)}">
      </div>
      <div class="field" id="row-stop" hidden>
        <label for="ticket-stop">Stop price</label>
        <input id="ticket-stop" name="stop_price" type="text" inputmode="decimal"
               value="{money(last * 0.97, inst.price_precision)}">
      </div>
      <div class="field-row">
        <div class="field">
          <label for="ticket-tif">Time in force</label>
          <select id="ticket-tif" name="tif">
            <option value="day">Day</option>
            <option value="gtc">Good till cancelled</option>
            <option value="ioc">Immediate or cancel</option>
            <option value="fok">Fill or kill</option>
          </select>
        </div>
        <div class="field">
          <label for="ticket-trail">Trail %</label>
          <input id="ticket-trail" name="trail_pct" type="text"
                 inputmode="decimal" placeholder="—">
        </div>
      </div>
      <div class="field-row">
        <div class="field">
          <label for="ticket-tp">Take profit</label>
          <input id="ticket-tp" name="take_profit" type="text"
                 inputmode="decimal" placeholder="optional">
        </div>
        <div class="field">
          <label for="ticket-sl">Stop loss</label>
          <input id="ticket-sl" name="stop_loss" type="text"
                 inputmode="decimal" placeholder="optional">
        </div>
      </div>
      <div class="check">
        <input type="checkbox" id="ticket-ext" name="allow_extended" value="1">
        <label for="ticket-ext">Allow extended hours</label>
      </div>
      <div class="check">
        <input type="checkbox" id="ticket-reduce" name="reduce_only" value="1">
        <label for="ticket-reduce">Reduce only</label>
      </div>
      <div id="ticket-estimate" class="muted-box my-md"></div>
      <button class="btn btn-primary btn-block" type="submit" id="ticket-submit">
        Place order</button>
      <p class="hint center-note">
        Simulated execution. Fills include modelled spread, slippage and fees.</p>
    </form>""")


def _recent_fills_card(broker, symbol: str | None = None) -> str:
    rows = [r for r in broker.blotter(200)
            if symbol is None or r["symbol"] == symbol][:12]
    body = table(
        ["Time", "Side", "Qty", "Price", "Fee", "Liq.", "Slip"],
        [[esc(r["ts"][:16].replace("T", " ")),
          badge(r["side"], "up" if r["side"] == "buy" else "down"),
          r["qty_fmt"], r["price_fmt"], money(r["fee"], 4),
          esc(r["liquidity"]), f'{money(r["slippage_bps"], 2)} bps']
         for r in rows],
        empty="No executions yet.", numeric={2, 3, 4, 6})
    return card("Recent executions", body, flush=True)


# ------------------------------------------------------ positions / orders


def positions_page(request: Request) -> Response:
    service = request.app.platform.service
    service.refresh(request.account_id)
    broker = service.broker(request.account_id)
    rows = broker.portfolio.position_rows()
    summary = broker.summary()

    detail = f"""
    <div class="grid cols-4 mb-1">
      {stat("Market value", money(summary['market_value']))}
      {stat("Margin used", money(summary['margin_used']),
            sub=f"maintenance {money(summary['maintenance_margin'])}")}
      {stat("Excess liquidity", money(summary['excess_liquidity']),
            value_class=pnl_class(summary['excess_liquidity']),
            sub="cushion above the maintenance requirement")}
      {stat("Margin utilization", f"{money(summary['margin_utilization'] * 100, 1)}%",
            sub="of equity committed")}
    </div>"""

    body = _flash(request) + detail + card(
        "Positions",
        table(["Symbol", "Class", "Side", "Qty", "Avg", "Last", "Value",
               "Unrealized", "Return", "Realized", "Lots", ""],
              [[f'<a href="/terminal?symbol={esc(p["symbol"])}">{esc(p["symbol"])}</a>',
                esc(p["asset_class"]),
                badge(p["side"], "up" if p["side"] == "long" else "down"),
                p["qty_fmt"], money(p["avg_price"], 4), money(p["last"], 4),
                money(p["market_value"]),
                f'<span class="{pnl_class(p["unrealized_pnl"])}">{signed(p["unrealized_pnl"])}</span>',
                f'<span class="{pnl_class(p["unrealized_pct"])}">{signed(p["unrealized_pct"], 2)}%</span>',
                f'<span class="{pnl_class(p["realized_pnl"])}">{signed(p["realized_pnl"])}</span>',
                str(p["lots"]),
                f'<button class="btn btn-sm btn-danger" data-close="{esc(p["symbol"])}">Close</button>']
               for p in rows],
              empty="No open positions.", body_id="positions-body",
              numeric={3, 4, 5, 6, 7, 8, 9, 10}),
        flush=True)
    return shell(request, "Positions", body, "/positions")


def orders_page(request: Request) -> Response:
    service = request.app.platform.service
    service.refresh(request.account_id)
    broker = service.broker(request.account_id)
    history = broker.order_history(300)

    rows = []
    for o in history:
        price = o.limit_price or o.stop_price
        kind = {"filled": "up", "rejected": "down", "canceled": "neutral",
                "expired": "neutral"}.get(o.status.value, "accent")
        action = (f'<button class="btn btn-sm btn-danger" data-cancel="{esc(o.id)}">'
                  f'Cancel</button>' if o.is_open else "")
        rows.append([
            f'<span class="mono faint">{esc(o.id)}</span>',
            f'<a href="/terminal?symbol={esc(o.symbol)}">{esc(o.symbol)}</a>',
            badge(o.side.value, "up" if o.side is Side.BUY else "down"),
            esc(o.order_type.value), esc(o.tif.value),
            resolve(o.symbol).fmt_qty(o.qty),
            money(price, 4) if price else "mkt",
            resolve(o.symbol).fmt_qty(o.filled_qty),
            money(o.avg_fill_price, 4) if o.filled_qty else "—",
            badge(o.status.value, kind),
            f'<span class="faint fs-sm">{esc(o.reject_reason or "")}</span>',
            action,
        ])

    body = _flash(request) + card(
        "Order history",
        table(["ID", "Symbol", "Side", "Type", "TIF", "Qty", "Price", "Filled",
               "Avg fill", "Status", "Note", ""], rows,
              empty="No orders yet.", numeric={5, 6, 7, 8}),
        subtitle=f"{len(history)} orders", flush=True)
    return shell(request, "Orders", body, "/orders")


def blotter_page(request: Request) -> Response:
    broker = request.app.platform.service.broker(request.account_id)
    rows = broker.blotter(500)
    total_fees = sum(r["fee"] for r in rows)
    total_notional = sum(r["notional"] for r in rows)

    head = f"""
    <div class="grid cols-4 mb-1">
      {stat("Executions", f"{len(rows):,}")}
      {stat("Traded notional", money(total_notional))}
      {stat("Fees paid", money(total_fees),
            sub=f"{money(total_fees / total_notional * 10000, 2) if total_notional else 0} bps of notional")}
      {stat("Maker share",
            f"{money(sum(1 for r in rows if r['liquidity'] == 'maker') / len(rows) * 100, 1) if rows else 0}%",
            sub="passive fills earn the spread")}
    </div>"""

    body = _flash(request) + head + card(
        "Execution blotter",
        table(["Time", "Order", "Symbol", "Side", "Qty", "Price", "Notional",
               "Fee", "Liquidity", "Slippage"],
              [[esc(r["ts"][:19].replace("T", " ")),
                f'<span class="mono faint">{esc(r["order_id"])}</span>',
                esc(r["symbol"]),
                badge(r["side"], "up" if r["side"] == "buy" else "down"),
                r["qty_fmt"], r["price_fmt"], money(r["notional"]),
                money(r["fee"], 4), esc(r["liquidity"]),
                f'{money(r["slippage_bps"], 2)} bps']
               for r in rows],
              empty="No executions yet.", numeric={4, 5, 6, 7, 9}),
        subtitle="append-only record of every fill", flush=True)
    return shell(request, "Blotter", body, "/blotter")


# --------------------------------------------------------------- analytics


def analytics_page(request: Request) -> Response:
    broker = request.app.platform.service.broker(request.account_id)
    perf = analyze(broker.equity_curve, broker.fills,
                   strategies={o.id: o.strategy for o in broker.orders.values()
                               if o.strategy})
    caveats = "".join(alert(c, "warn") for c in perf.caveats)

    def row(k: str, v: str, cls: str = "") -> str:
        return (f'<div class="kv"><span class="k">{esc(k)}</span>'
                f'<span class="v {cls}">{v}</span></div>')

    returns = card("Returns", "".join([
        row("Starting equity", money(perf.starting_equity)),
        row("Ending equity", money(perf.ending_equity)),
        row("Total return", signed(perf.total_return_pct, 2, "%"),
            pnl_class(perf.total_return_pct)),
        row("CAGR", signed(perf.cagr_pct, 2, "%") if perf.cagr_pct is not None
            else '<span class="faint">needs 30 days</span>',
            pnl_class(perf.cagr_pct or 0)),
        row("Volatility (ann.)", f"{money(perf.volatility_pct, 2)}%"
            if perf.volatility_pct else "—"),
        row("Days tracked", str(perf.days)),
    ]))

    risk = card("Risk", "".join([
        row("Sharpe ratio", money(perf.sharpe_ratio, 2)),
        row("Sortino ratio", money(perf.sortino_ratio, 2)
            if perf.sortino_ratio != float("inf") else "∞"),
        row("Calmar ratio", money(perf.calmar_ratio, 2)
            if perf.calmar_ratio is not None else "—"),
        row("Max drawdown", f"{money(perf.max_drawdown_pct, 2)}%", "down"),
        row("Drawdown depth", money(perf.max_drawdown_abs), "down"),
        row("Days underwater", str(perf.drawdown_days)),
        row("VaR 95% (daily)", f"{money(perf.var_95_pct, 2)}%", "down"),
        row("CVaR 95% (daily)", f"{money(perf.cvar_95_pct, 2)}%", "down"),
    ]))

    trades = card("Trades", "".join([
        row("Closed trades", str(perf.trades)),
        row("Win rate", f"{money(perf.win_rate_pct, 1)}%"),
        row("Profit factor", money(perf.profit_factor, 2)
            if perf.profit_factor != float("inf") else "∞"),
        row("<strong>Median trade</strong>", signed(perf.median_trade_pnl),
            pnl_class(perf.median_trade_pnl)),
        row("Mean trade", signed(perf.mean_trade_pnl),
            pnl_class(perf.mean_trade_pnl)),
        row("Median win", signed(perf.median_win), "up"),
        row("Median loss", signed(perf.median_loss), "down"),
        row("Largest win", signed(perf.largest_win), "up"),
        row("Largest loss", signed(perf.largest_loss), "down"),
        row("Median hold", f"{money(perf.median_hold_hours, 1)}h"),
        row("Day trades", str(perf.day_trades)),
    ]))

    costs = card("Costs", "".join([
        row("Gross P&L", signed(perf.gross_pnl), pnl_class(perf.gross_pnl)),
        row("Fees paid", money(perf.total_fees), "down"),
        row("Net P&L", signed(perf.net_pnl), pnl_class(perf.net_pnl)),
        row("Fees as % of gross", f"{money(perf.fees_pct_of_gross, 1)}%"),
    ]) + '<p class="hint mt-md">Costs are the difference '
         'between a paper result and a funded one. A strategy whose fees exceed '
         'a third of gross profit is trading too often for its edge.</p>')

    attribution = by_symbol(broker.fills)
    attr_card = card(
        "Per-symbol attribution",
        table(["Symbol", "Class", "Trades", "Net P&L", "Median", "Win rate", "Fees"],
              [[esc(a["symbol"]), esc(a["asset_class"]), str(a["trades"]),
                f'<span class="{pnl_class(a["net_pnl"])}">{signed(a["net_pnl"])}</span>',
                f'<span class="{pnl_class(a["median_pnl"])}">{signed(a["median_pnl"])}</span>'
                + (' <span class="badge badge-warn">low n</span>'
                   if a["low_confidence"] else ""),
                f'{money(a["win_rate_pct"], 1)}%', money(a["fees"])]
               for a in attribution],
              empty="No closed trades to attribute yet.",
              numeric={2, 3, 4, 5, 6}),
        subtitle=f"ranked on median, not total — fewer than {MIN_TRADES} trades is flagged",
        flush=True)

    body = (_flash(request)
            + alert(perf.verdict(), "warn" if perf.low_confidence else "info")
            + caveats
            + card("Equity curve", '<div id="equity-host" class="h-equity"></div>')
            + f'<div class="grid cols-2">{returns}{risk}</div>'
            + f'<div class="grid cols-2">{trades}{costs}</div>'
            + attr_card)
    return shell(request, "Performance", body, "/analytics")


# --------------------------------------------------------------- backtest


def backtest_page(request: Request) -> Response:
    request.user.require("run.backtest")
    service = request.app.platform.service
    csrf = request.app.csrf_token(request.session_token)
    strategies = available_strategies()

    symbol = resolve(request.get("symbol", "AAPL")).symbol
    strategy_name = request.get("strategy", "sma-crossover")
    interval = request.get("interval", "1d")
    limit = max(60, min(1000, request.get_int("limit", 400)))
    cash = max(1000.0, request.get_float("cash", 100_000.0))

    result_html = ""
    if request.method == "POST":
        try:
            cls = get_strategy(strategy_name)
            params = {}
            for key, spec in cls.params_schema.items():
                raw = request.get(f"param_{key}", "")
                if raw == "":
                    continue
                if spec.get("type") == "int":
                    params[key] = int(float(raw))
                elif spec.get("type") == "float":
                    params[key] = float(raw)
                elif spec.get("type") == "bool":
                    params[key] = raw.lower() in ("1", "true", "on", "yes")
                else:
                    params[key] = raw
            bars = service.bars(symbol, interval, limit)
            result = Backtester(starting_cash=cash).run(cls(**params), bars,
                                                        symbol=symbol)
            result_html = _backtest_result(result)
        except Exception as e:                             # noqa: BLE001
            result_html = alert(f"Backtest failed: {e}", "error")

    options = "".join(
        f'<option value="{esc(s["name"])}" '
        f'{"selected" if s["name"] == strategy_name else ""}>{esc(s["name"])}</option>'
        for s in strategies)
    selected = next((s for s in strategies if s["name"] == strategy_name),
                    strategies[0])
    param_fields = "".join(
        f'<div class="field"><label for="p_{esc(k)}">{esc(spec.get("label", k))}</label>'
        f'<input id="p_{esc(k)}" name="param_{esc(k)}" type="text" '
        f'value="{esc(spec.get("default", ""))}"></div>'
        for k, spec in selected["params"].items())

    form = card("Run a backtest", f"""
    <form method="post" action="/backtest">
      <input type="hidden" name="csrf_token" value="{esc(csrf)}">
      <div class="field-row">
        <div class="field"><label for="bt-symbol">Symbol</label>
          <input id="bt-symbol" name="symbol" value="{esc(symbol)}"></div>
        <div class="field"><label for="bt-strategy">Strategy</label>
          <select id="bt-strategy" name="strategy"
                  data-autosubmit>{options}</select></div>
      </div>
      <div class="field-row">
        <div class="field"><label for="bt-interval">Interval</label>
          <select id="bt-interval" name="interval">
            {''.join(f'<option {"selected" if i == interval else ""}>{i}</option>'
                     for i in ("1d", "1h", "15m", "1w"))}
          </select></div>
        <div class="field"><label for="bt-limit">Bars</label>
          <input id="bt-limit" name="limit" value="{limit}"></div>
      </div>
      <div class="field"><label for="bt-cash">Starting cash</label>
        <input id="bt-cash" name="cash" value="{int(cash)}"></div>
      <p class="hint mt-note">{esc(selected["description"])}</p>
      {param_fields}
      <button class="btn btn-primary btn-block" type="submit">Run backtest</button>
    </form>""")

    note = card("How this backtest works", """
      <p class="fs-note">Orders are matched by the <strong>same engine
      that fills live paper trades</strong> — the same spread model, slippage,
      commissions and regulatory fees.</p>
      <p class="fs-note">A signal computed from a bar's close is filled
      at the <strong>next</strong> bar's open, never the same bar. Stops that
      gap fill at the gap, not the stop price.</p>
      <p class="note-flat">Every run is compared against
      buy-and-hold. A strategy that cannot beat holding the asset has not earned
      the risk it takes.</p>""")

    body = (_flash(request) + f'<div class="split"><div>{result_html}</div>'
            f'<div>{form}{note}</div></div>')
    return shell(request, "Backtest", body, "/backtest")


def _backtest_result(result) -> str:
    p = result.performance
    alpha = result.alpha_pct or 0.0
    head = f"""
    <div class="grid cols-4 mb-1">
      {stat("Total return", signed(result.total_return_pct, 2, "%"),
            value_class=pnl_class(result.total_return_pct),
            sub=f"{money(result.starting_equity)} → {money(result.ending_equity)}")}
      {stat("Buy & hold", signed(result.benchmark_return_pct, 2, "%"),
            value_class=pnl_class(result.benchmark_return_pct),
            sub="the benchmark to beat")}
      {stat("Alpha", signed(alpha, 2, "%"), value_class=pnl_class(alpha),
            sub="excess over holding")}
      {stat("Max drawdown", f"{money(p.max_drawdown_pct, 2)}%",
            value_class="down", sub=f"{p.drawdown_days} days underwater")}
    </div>"""

    def kv(k, v, cls=""):
        return (f'<div class="kv"><span class="k">{esc(k)}</span>'
                f'<span class="v {cls}">{v}</span></div>')

    detail = f"""<div class="grid cols-2">
      {card("Trade statistics", "".join([
        kv("Closed trades", str(p.trades)),
        kv("Win rate", f"{money(p.win_rate_pct, 1)}%"),
        kv("Profit factor", money(p.profit_factor, 2)
           if p.profit_factor != float("inf") else "∞"),
        kv("Median trade", signed(p.median_trade_pnl), pnl_class(p.median_trade_pnl)),
        kv("Mean trade", signed(p.mean_trade_pnl), pnl_class(p.mean_trade_pnl)),
        kv("Median hold", f"{money(p.median_hold_hours, 1)}h"),
        kv("Sharpe", money(p.sharpe_ratio, 2)),
        kv("Sortino", money(p.sortino_ratio, 2)
           if p.sortino_ratio != float("inf") else "∞"),
      ]))}
      {card("Execution reality", "".join([
        kv("Orders placed", str(len(result.orders))),
        kv("Fills", str(len(result.fills))),
        kv("Fees paid", money(p.total_fees), "down"),
        kv("Fees as % of gross", f"{money(p.fees_pct_of_gross, 1)}%"),
        kv("Gross P&L", signed(p.gross_pnl), pnl_class(p.gross_pnl)),
        kv("Net P&L", signed(p.net_pnl), pnl_class(p.net_pnl)),
        kv("Bars tested", str(result.bars)),
        kv("Period", f'{result.start:%Y-%m-%d} → {result.end:%Y-%m-%d}'),
      ]))}
    </div>"""

    caveats = "".join(alert(c, "warn") for c in p.caveats)
    log_html = ""
    if result.log:
        log_html = card("Strategy log", '<div class="scroll-y"><pre class="mono" '
                        ' class="log-pre">'
                        + esc("\n".join(result.log[-80:])) + "</pre></div>")

    return (f'<h1>{esc(result.strategy)} on {esc(result.symbol)}</h1>'
            + alert(p.verdict(), "warn" if p.low_confidence else "info")
            + caveats + head + detail + log_html)


# ----------------------------------------------------------------- markets


def markets_page(request: Request) -> Response:
    service = request.app.platform.service
    ac = request.query.get("class", "equity")
    if ac not in ("equity", "crypto", "fx"):
        ac = "equity"
    query = request.query.get("q", "").strip()

    instruments = search(query, 60) if query else catalog(ac)[:60]
    symbols = [i.symbol for i in instruments]
    quotes = service.quotes(symbols)

    rows = []
    for inst in instruments:
        q = quotes.get(inst.symbol)
        if q:
            price = money(q.last, inst.price_precision)
            chg = f'<span class="{pnl_class(q.change_pct)}">{signed(q.change_pct, 2)}%</span>'
            vol = money(q.volume, 0)
        else:
            price = chg = vol = '<span class="faint">—</span>'
        rows.append([
            f'<a href="/terminal?symbol={esc(inst.symbol)}"><strong>{esc(inst.symbol)}</strong></a>',
            esc(inst.name), badge(inst.asset_class.value, "accent"),
            price, chg, vol,
            f"{int(inst.max_leverage)}:1" if inst.is_leveraged else "cash",
            f"{money(round_trip_cost_bps(inst, 10_000), 1)} bps",
        ])

    tabs = "".join(
        f'<a class="btn btn-sm {"btn-primary" if ac == c and not query else ""}" '
        f'href="/markets?class={c}">{label}</a>'
        for c, label in [("equity", "Stocks"), ("crypto", "Crypto"), ("fx", "Forex")])

    body = _flash(request) + card(
        "Instruments",
        table(["Symbol", "Name", "Class", "Last", "Change", "Volume",
               "Leverage", "Round trip"], rows,
              empty="No instruments match that search.", numeric={3, 4, 5, 7}),
        actions=f"""<form method="get" action="/markets" class="row gap-xs">
            <input type="text" name="q" value="{esc(query)}" placeholder="Search" class="w-md">
            <button class="btn btn-sm" type="submit">Search</button></form>{tabs}""",
        flush=True)
    return shell(request, "Markets", body, "/markets")


# ----------------------------------------------------------------- profile


def profile_page(request: Request) -> Response:
    platform = request.app.platform
    conn = platform.conn()
    user = request.user
    csrf = request.app.csrf_token(request.session_token)
    service = platform.service

    watch = service.watchlist(user.id)
    tokens = list_api_tokens(conn, user.id)
    broker = service.broker(request.account_id)
    limits = broker.risk.limits

    profile = card("Your account", f"""
      <div class="kv"><span class="k">Username</span>
        <span class="v">{esc(user.username)}</span></div>
      <div class="kv"><span class="k">Display name</span>
        <span class="v">{esc(user.display_name)}</span></div>
      <div class="kv"><span class="k">Email</span>
        <span class="v">{esc(user.email or "—")}</span></div>
      <div class="kv"><span class="k">Role</span>
        <span class="v">{badge(user.role.value, "accent")}</span></div>
      <div class="kv"><span class="k">Member since</span>
        <span class="v">{esc(user.created_at[:10])}</span></div>
      <div class="kv"><span class="k">Last sign-in</span>
        <span class="v">{esc((user.last_login_at or "—")[:19].replace("T", " "))}</span></div>""")

    password = card("Change password", f"""
      <form method="post" action="/profile/password">
        <input type="hidden" name="csrf_token" value="{esc(csrf)}">
        <div class="field"><label for="cur">Current password</label>
          <input id="cur" name="current" type="password" required
                 autocomplete="current-password"></div>
        <div class="field"><label for="new">New password</label>
          <input id="new" name="new_password" type="password" required
                 minlength="12" autocomplete="new-password">
          <div class="hint">At least 12 characters, mixing three character
            classes. Changing it signs out every other session.</div></div>
        <button class="btn btn-primary" type="submit">Update password</button>
      </form>""")

    watchlist = card("Watchlist", f"""
      <form method="post" action="/profile/watchlist">
        <input type="hidden" name="csrf_token" value="{esc(csrf)}">
        <div class="field">
          <label for="wl">Symbols (comma separated)</label>
          <textarea id="wl" name="symbols" rows="3">{esc(", ".join(watch))}</textarea>
          <div class="hint">Shown in the ticker at the top of every page.</div>
        </div>
        <button class="btn" type="submit">Save watchlist</button>
      </form>""")

    token_rows = [[esc(t["name"]), f'<span class="mono">{esc(t["prefix"])}…</span>',
                   esc(t["scopes"]), esc(t["created_at"][:10]),
                   esc((t["last_used_at"] or "never")[:10]),
                   badge("revoked", "down") if t["revoked"] else badge("active", "up"),
                   (f'<form method="post" action="/profile/tokens/{t["id"]}/revoke" '
                    f' class="m-0"><input type="hidden" name="csrf_token" '
                    f'value="{esc(csrf)}"><button class="btn btn-sm btn-danger">'
                    f'Revoke</button></form>') if not t["revoked"] else ""]
                  for t in tokens]
    api_card = card("API tokens", table(
        ["Name", "Prefix", "Scopes", "Created", "Last used", "Status", ""],
        token_rows, empty="No API tokens yet.") + f"""
      <form method="post" action="/profile/tokens" class="row mt-xl">
        <input type="hidden" name="csrf_token" value="{esc(csrf)}">
        <input type="text" name="name" placeholder="Token name" required class="w-xl">
        <select name="scopes" class="w-sm">
          <option value="read">read</option>
          <option value="read,trade">read, trade</option>
        </select>
        <button class="btn" type="submit">Create token</button>
      </form>
      <p class="hint">The token is shown once, at creation. Store it somewhere
      safe — it cannot be recovered.</p>""")

    risk_card = card("Your risk limits", f"""
      <form method="post" action="/profile/risk">
        <input type="hidden" name="csrf_token" value="{esc(csrf)}">
        <div class="field-row">
          <div class="field"><label for="r1">Max order notional</label>
            <input id="r1" name="max_order_notional"
                   value="{int(limits.max_order_notional)}"></div>
          <div class="field"><label for="r2">Max position notional</label>
            <input id="r2" name="max_position_notional"
                   value="{int(limits.max_position_notional)}"></div>
        </div>
        <div class="field-row">
          <div class="field"><label for="r3">Daily loss limit</label>
            <input id="r3" name="daily_loss_limit"
                   value="{int(limits.daily_loss_limit)}">
            <div class="hint">0 disables it.</div></div>
          <div class="field"><label for="r4">Fat-finger collar %</label>
            <input id="r4" name="fat_finger_pct"
                   value="{money(limits.fat_finger_pct, 0)}"></div>
        </div>
        <div class="check">
          <input type="checkbox" id="r5" name="allow_shorting" value="1"
                 {"checked" if limits.allow_shorting else ""}>
          <label for="r5">Allow short selling</label></div>
        <div class="check">
          <input type="checkbox" id="r6" name="allow_margin" value="1"
                 {"checked" if limits.allow_margin else ""}>
          <label for="r6">Allow margin</label></div>
        <div class="check">
          <input type="checkbox" id="r7" name="enforce_pdt" value="1"
                 {"checked" if limits.enforce_pdt else ""}>
          <label for="r7">Enforce the pattern day trader rule</label></div>
        <button class="btn btn-primary" type="submit">Save risk limits</button>
      </form>
      <p class="hint">Setting your own limits before the session is the point.
      Raising them mid-drawdown is how a bad day becomes a bad month.</p>""")

    reset_card = card("Reset paper account", f"""
      <p class="fs-note">Deletes every order, fill and position on this
      account and restores the opening balance. This cannot be undone.</p>
      <form method="post" action="/profile/reset"
            data-confirm="Delete all trading history and reset the balance?">
        <input type="hidden" name="csrf_token" value="{esc(csrf)}">
        <button class="btn btn-danger" type="submit">Reset account</button>
      </form>""")

    body = (_flash(request)
            + f'<div class="grid cols-2">{profile}{password}</div>'
            + f'<div class="grid cols-2">{watchlist}{risk_card}</div>'
            + api_card + reset_card)
    return shell(request, "Profile", body, "/profile")
