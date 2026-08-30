"""Command line interface. `python -m deoltech --help`

The terminal is the operator's surface: start the server, create the first
administrator, check whether Finviz is reachable, run a backtest without a
browser. Anything an administrator might need at 3am when the web UI is the
thing that is broken.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone

from . import __version__
from .accounts import AccountService, create_account, default_account, list_accounts
from .analytics import analyze
from .auth import (
    AuthError, Role, bootstrap_admin, create_user, find_user, generate_password,
    list_users, reset_password,
)
from .backtest import Backtester
from .clock import market_status
from .db import audit_trail, connect, db_path, get_setting, set_setting, stats
from .feeds import build_feed
from .instruments import catalog, resolve
from .strategies import available as available_strategies, get as get_strategy
from .types import Order, OrderType, Side

BOLD, DIM, RESET = "\033[1m", "\033[2m", "\033[0m"
GREEN, RED, YELLOW = "\033[32m", "\033[31m", "\033[33m"


def _colour(value: float, text: str) -> str:
    if not sys.stdout.isatty():
        return text
    return f"{GREEN if value > 0 else (RED if value < 0 else '')}{text}{RESET}"


def _rule(title: str = "") -> None:
    if title:
        print(f"\n{BOLD if sys.stdout.isatty() else ''}{title}"
              f"{RESET if sys.stdout.isatty() else ''}")
    print("-" * 72)


# ------------------------------------------------------------------ commands


def cmd_serve(args) -> int:
    from .web.app import run
    run(host=args.host, port=args.port, db_path=args.db, feed_mode=args.feed,
        secure_cookies=args.secure_cookies, trust_proxy=args.trust_proxy,
        debug=args.debug)
    return 0


def cmd_admin(args) -> int:
    conn = connect(args.db)
    if args.admin_action == "create":
        password = args.password or generate_password()
        try:
            user, generated = bootstrap_admin(conn, args.username, password,
                                              args.email or "")
        except AuthError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        if generated is None and args.password is None:
            print(f"User {user.username!r} already exists (role "
                  f"{user.role.value}). Use 'admin reset' to set a new password.")
            return 0
        default_account(conn, user.id, user.username)
        _rule("Administrator created")
        print(f"  username  {user.username}")
        print(f"  password  {password}")
        print(f"  role      {user.role.value}")
        print("\nStore this password now — it is hashed, not saved, and cannot "
              "be recovered.")
        return 0

    if args.admin_action == "list":
        users = list_users(conn)
        _rule(f"Users ({len(users)})")
        print(f"  {'username':<20} {'role':<8} {'status':<10} {'accts':>5} "
              f"{'sessions':>8}  last sign-in")
        for u in users:
            print(f"  {u['username']:<20} {u['role']:<8} {u['status']:<10} "
                  f"{u['accounts']:>5} {u['active_sessions']:>8}  "
                  f"{(u['last_login_at'] or 'never')[:19]}")
        return 0

    if args.admin_action == "reset":
        user = find_user(conn, args.username)
        if not user:
            print(f"error: no user named {args.username!r}", file=sys.stderr)
            return 1
        admins = [u for u in list_users(conn)
                  if u["role"] == "admin" and u["status"] == "active"]
        if not admins:
            print("error: no active administrator to authorize this",
                  file=sys.stderr)
            return 1
        actor = find_user(conn, admins[0]["username"])
        password = reset_password(conn, actor, user.id, args.password)
        _rule(f"Password reset for {user.username}")
        print(f"  {password}\n\nThey must change it at next sign-in.")
        return 0
    return 1


def cmd_quote(args) -> int:
    feed = build_feed(args.feed, finviz_token=os.environ.get("FINVIZ_AUTH_TOKEN", ""))
    symbols = [resolve(s).symbol for s in args.symbols]
    quotes = feed.get_quotes(symbols)
    _rule("Quotes")
    print(f"  {'symbol':<9} {'last':>12} {'change':>10} {'%':>8} {'volume':>15}  source")
    for sym in symbols:
        q = quotes.get(sym)
        if not q:
            print(f"  {sym:<9} {'unavailable':>12}")
            continue
        inst = resolve(sym)
        change = q.last - q.prev_close
        print(f"  {sym:<9} {inst.fmt_price(q.last):>12} "
              f"{_colour(change, f'{change:+,.{inst.price_precision}f}'):>10} "
              f"{_colour(q.change_pct, f'{q.change_pct:+.2f}%'):>8} "
              f"{q.volume:>15,.0f}  {q.source}")
    for ac in sorted({resolve(s).asset_class.value for s in symbols}):
        st = market_status(ac)
        print(f"\n  {ac:<8} market {st.label}"
              + (f" — opens {st.opens_at:%a %H:%M} UTC" if st.opens_at else ""))
    return 0


def cmd_bars(args) -> int:
    feed = build_feed(args.feed)
    symbol = resolve(args.symbol).symbol
    inst = resolve(symbol)
    bars = feed.get_bars(symbol, args.interval, args.limit)
    _rule(f"{symbol} · {args.interval} · {len(bars)} bars")
    print(f"  {'time':<20} {'open':>12} {'high':>12} {'low':>12} {'close':>12} "
          f"{'volume':>14}")
    for b in bars[-args.show:]:
        change = b.close - b.open
        print(f"  {b.ts:%Y-%m-%d %H:%M}     {inst.fmt_price(b.open):>12} "
              f"{inst.fmt_price(b.high):>12} {inst.fmt_price(b.low):>12} "
              f"{_colour(change, inst.fmt_price(b.close)):>12} {b.volume:>14,.0f}")
    return 0


def cmd_probe(args) -> int:
    """Check every Finviz endpoint and report which parsers still match."""
    from .feeds.finviz import FinvizFeed
    feed = FinvizFeed(auth_token=os.environ.get("FINVIZ_AUTH_TOKEN", ""))
    _rule("Finviz endpoint probe")
    results = feed.probe()
    for r in results:
        mark = f"{GREEN}ok{RESET}" if r["ok"] else f"{RED}FAIL{RESET}"
        if not sys.stdout.isatty():
            mark = "ok" if r["ok"] else "FAIL"
        print(f"  {mark:<12} {r['endpoint']:<20} {r['records']:>6} records"
              + (f"   {r['error'][:70]}" if r["error"] else ""))
    ok = sum(1 for r in results if r["ok"])
    print(f"\n  {ok}/{len(results)} endpoints reachable and parseable")
    if ok == 0:
        print("\n  Every endpoint failed. Either this host cannot reach "
              "finviz.com,\n  or Finviz changed their response format. The "
              "platform will serve\n  SIMULATED prices until this is resolved.")
        return 1
    if ok < len(results):
        print("\n  Some endpoints failed. Affected asset classes will fall back "
              "to\n  simulated prices; the UI marks them as degraded.")
    return 0


def cmd_backtest(args) -> int:
    feed = build_feed(args.feed)
    symbol = resolve(args.symbol).symbol
    bars = feed.get_bars(symbol, args.interval, args.limit)
    params = {}
    for pair in args.param or []:
        if "=" not in pair:
            print(f"error: --param expects key=value, got {pair!r}", file=sys.stderr)
            return 1
        key, value = pair.split("=", 1)
        try:
            params[key] = int(value) if value.isdigit() else float(value)
        except ValueError:
            params[key] = value.lower() in ("true", "yes", "on") \
                if value.lower() in ("true", "false", "yes", "no", "on", "off") \
                else value
    try:
        cls = get_strategy(args.strategy)
    except KeyError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    result = Backtester(starting_cash=args.cash).run(cls(**params), bars,
                                                     symbol=symbol)
    p = result.performance
    _rule(f"{result.strategy} on {symbol} · {result.bars} × {args.interval} bars")
    print(f"  {result.start:%Y-%m-%d} → {result.end:%Y-%m-%d}\n")
    print(f"  {'Return':<24} {_colour(result.total_return_pct, f'{result.total_return_pct:+.2f}%')}")
    print(f"  {'Buy and hold':<24} {_colour(result.benchmark_return_pct, f'{result.benchmark_return_pct:+.2f}%')}")
    print(f"  {'Alpha':<24} {_colour(result.alpha_pct or 0, f'{result.alpha_pct:+.2f}%')}")
    print(f"  {'Ending equity':<24} {result.ending_equity:,.2f}")
    _rule("Risk")
    print(f"  {'Max drawdown':<24} {p.max_drawdown_pct:.2f}%  "
          f"({p.drawdown_days} days underwater)")
    print(f"  {'Sharpe':<24} {p.sharpe_ratio:.2f}")
    print(f"  {'Sortino':<24} {p.sortino_ratio:.2f}")
    _rule("Trades")
    print(f"  {'Closed trades':<24} {p.trades}")
    print(f"  {'Win rate':<24} {p.win_rate_pct:.1f}%")
    print(f"  {'Profit factor':<24} {p.profit_factor:.2f}")
    print(f"  {'Median trade':<24} {_colour(p.median_trade_pnl, f'{p.median_trade_pnl:+,.2f}')}")
    print(f"  {'Mean trade':<24} {_colour(p.mean_trade_pnl, f'{p.mean_trade_pnl:+,.2f}')}")
    print(f"  {'Fees paid':<24} {p.total_fees:,.2f}  "
          f"({p.fees_pct_of_gross:.1f}% of gross)")
    _rule("Verdict")
    print(f"  {p.verdict()}")
    for c in p.caveats:
        print(f"  {YELLOW if sys.stdout.isatty() else ''}! {c}"
              f"{RESET if sys.stdout.isatty() else ''}")
    if args.json:
        print("\n" + json.dumps(result.summary(), indent=2, default=str))
    return 0


def cmd_strategies(args) -> int:
    _rule("Built-in strategies")
    for s in available_strategies():
        print(f"\n  {BOLD if sys.stdout.isatty() else ''}{s['name']}"
              f"{RESET if sys.stdout.isatty() else ''}")
        print(f"    {s['description']}")
        if s["params"]:
            for key, spec in s["params"].items():
                print(f"      --param {key}={spec.get('default')}"
                      f"   {DIM if sys.stdout.isatty() else ''}"
                      f"({spec.get('type', 'str')})"
                      f"{RESET if sys.stdout.isatty() else ''}")
    return 0


def cmd_instruments(args) -> int:
    items = catalog(args.asset_class)
    _rule(f"Instruments ({len(items)})")
    print(f"  {'symbol':<10} {'class':<8} {'tick':>10} {'min size':>12} "
          f"{'leverage':>9}  name")
    for i in items:
        lev = f"{int(i.max_leverage)}:1" if i.is_leveraged else "cash"
        print(f"  {i.symbol:<10} {i.asset_class.value:<8} {i.tick_size:>10} "
              f"{i.fmt_qty(i.min_qty):>12} {lev:>9}  {i.name}")
    return 0


def cmd_status(args) -> int:
    conn = connect(args.db)
    st = stats(conn)
    _rule("Deol Tech")
    print(f"  version         {__version__}")
    print(f"  database        {st['db_path']}")
    print(f"  database size   {st['db_size_bytes'] / 1024:,.0f} KB")
    print(f"  users           {st['users']} ({st['active_users']} active, "
          f"{st['admins']} admin)")
    print(f"  accounts        {st['accounts']}")
    print(f"  orders / fills  {st['orders']:,} / {st['fills']:,}")
    print(f"  sessions        {st['sessions']} active")
    print(f"  feed mode       {get_setting(conn, 'feed_mode', 'auto')}")
    _rule("Markets")
    for ac in ("equity", "crypto", "fx"):
        s = market_status(ac)
        print(f"  {ac:<8} {s.label}")
    if st["users"] == 0:
        print("\n  No users yet. Run:  python -m deoltech admin create")
    return 0


def cmd_demo(args) -> int:
    """Seed a demo account with a realistic multi-asset trading history.

    The trades are produced by replaying historical bars through the real
    matching engine, not by firing live orders. That matters for two reasons:
    it works at 2am on a Sunday when every equity market is shut, and the
    resulting record is large enough that the performance page has something
    honest to say instead of "1 trade, not enough evidence".
    """
    from .engine.broker import EquityPoint
    from .strategies import DonchianBreakout, MeanReversion, RsiPullback, SmaCrossover

    conn = connect(args.db)
    user = find_user(conn, args.username)
    if not user:
        password = generate_password()
        try:
            user = create_user(conn, args.username, password, role=Role.TRADER,
                               display_name="Demo Trader")
        except AuthError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        print(f"created demo user {user.username} with password: {password}")
    account_id = default_account(conn, user.id, user.username)

    service = AccountService(connect, feed_mode="synthetic")
    broker = service.broker(account_id)
    feed = service.feed

    book = [
        ("AAPL", SmaCrossover(fast=10, slow=30, risk_pct=1.5)),
        ("NVDA", DonchianBreakout(entry=15, exit=8, risk_pct=1.5)),
        ("BTCUSD", MeanReversion(period=15, entry_z=-1.5, risk_pct=1.0)),
        ("ETHUSD", DonchianBreakout(entry=12, exit=6, risk_pct=1.0)),
        ("EURUSD", SmaCrossover(fast=8, slow=21, risk_pct=0.8)),
        ("SPY", RsiPullback(trend_sma=60, rsi_period=3, risk_pct=1.0)),
    ]

    orders, fills = [], []
    for symbol, strategy in book:
        bars = feed.get_bars(symbol, "1d", 400)
        # A slice of the account per instrument, so no single one can consume
        # all the buying power and starve the rest.
        result = Backtester(starting_cash=broker.portfolio.starting_cash / len(book)
                            ).run(strategy, bars, symbol=symbol, benchmark=False)
        orders.extend(result.orders)
        fills.extend(result.fills)

    fills.sort(key=lambda f: f.ts)
    for order in orders:
        broker.orders[order.id] = order
    for fill in fills:
        broker.portfolio.apply_fill(fill)
        broker.fills.append(fill)
        p = broker.portfolio
        broker.equity_curve.append(EquityPoint(
            fill.ts, p.equity(), p.cash_total(), p.unrealized_pnl(),
            p.realized_pnl))

    service.persist(account_id, orders, fills)
    for point in broker.equity_curve:
        from .accounts import save_equity_point
        save_equity_point(conn, account_id, point)

    perf = analyze(broker.equity_curve, broker.fills)
    _rule("Demo account seeded")
    print(f"  user            {user.username}")
    print(f"  account         #{account_id}")
    print(f"  instruments     {', '.join(s for s, _ in book)}")
    print(f"  orders / fills  {len(orders)} / {len(fills)}")
    print(f"  equity          {broker.portfolio.equity():,.2f}")
    print(f"  open positions  {len(broker.portfolio.open_positions())}")
    _rule("Performance")
    print(f"  closed trades   {perf.trades}")
    print(f"  win rate        {perf.win_rate_pct:.1f}%")
    print(f"  median trade    {_colour(perf.median_trade_pnl, f'{perf.median_trade_pnl:+,.2f}')}")
    print(f"  mean trade      {_colour(perf.mean_trade_pnl, f'{perf.mean_trade_pnl:+,.2f}')}")
    print(f"  max drawdown    {perf.max_drawdown_pct:.2f}%")
    print(f"  fees paid       {perf.total_fees:,.2f}")
    print(f"\n  {perf.verdict()}")
    print("\n  Start the server and sign in:  python -m deoltech serve")
    return 0


def cmd_backup(args) -> int:
    """Consistent online backup of the database.

    Uses SQLite's own backup API rather than copying the file. A `cp` of a
    live database can capture a torn write and produce something that only
    looks like a backup — which you discover at the worst possible moment.
    """
    import gzip
    import shutil
    import sqlite3 as sq
    from pathlib import Path

    source = db_path()
    if not source.exists():
        print(f"error: no database at {source}", file=sys.stderr)
        return 1

    dest_dir = Path(args.dest)
    dest_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = dest_dir / f"deoltech-{stamp}.db"

    src = sq.connect(f"file:{source}?mode=ro", uri=True)
    dst = sq.connect(str(target))
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()

    # Verify before compressing. A backup nobody checked is a hypothesis.
    check = sq.connect(str(target))
    try:
        ok = check.execute("PRAGMA integrity_check").fetchone()[0]
        users = check.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        fills = check.execute("SELECT COUNT(*) FROM fills").fetchone()[0]
    finally:
        check.close()
    if ok != "ok":
        print(f"error: integrity check failed on the backup: {ok}", file=sys.stderr)
        return 1

    if not args.no_compress:
        with open(target, "rb") as f_in, gzip.open(f"{target}.gz", "wb") as f_out:
            shutil.copyfileobj(f_in, f_out)
        target.unlink()
        target = Path(f"{target}.gz")

    size = target.stat().st_size
    print(f"{target}  ({size / 1024:,.0f} KB, {users} users, {fills:,} fills, "
          f"integrity ok)")

    # Retention. A backup policy without one is a disk-full incident waiting.
    if args.keep_days > 0:
        cutoff = datetime.now(timezone.utc).timestamp() - args.keep_days * 86400
        removed = 0
        for old_file in dest_dir.glob("deoltech-*.db*"):
            if old_file.stat().st_mtime < cutoff:
                old_file.unlink()
                removed += 1
        if removed:
            print(f"removed {removed} backup(s) older than {args.keep_days} days")
    return 0


def cmd_audit(args) -> int:
    conn = connect(args.db)
    entries = audit_trail(conn, args.limit, severity=args.severity)
    _rule(f"Audit log ({len(entries)} entries)")
    for e in entries:
        marker = {"critical": RED, "warning": YELLOW}.get(e["severity"], "")
        if not sys.stdout.isatty():
            marker = ""
        print(f"  {e['ts'][:19]}  {marker}{e['severity']:<9}"
              f"{RESET if marker else ''} {e['action']:<24} "
              f"{(e['actor_name'] or '—'):<14} {e['target'] or ''} "
              f"{DIM if sys.stdout.isatty() else ''}{(e['detail'] or '')[:60]}"
              f"{RESET if sys.stdout.isatty() else ''}")
    return 0


# -------------------------------------------------------------------- parser


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="deoltech",
        description="Deol Tech — professional paper trading for stocks, crypto "
                    "and forex.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""examples:
  python -m deoltech admin create              create the first administrator
  python -m deoltech serve --port 8000         start the web platform
  python -m deoltech quote AAPL BTCUSD EURUSD  live prices from Finviz
  python -m deoltech probe                     check Finviz is reachable
  python -m deoltech backtest sma-crossover AAPL --param fast=10 --param slow=30
""")
    parser.add_argument("--version", action="version",
                        version=f"Deol Tech {__version__}")
    parser.add_argument("--db", help="path to the SQLite database")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("serve", help="run the web platform")
    p.add_argument("--host", default=os.environ.get("DEOLTECH_HOST", "127.0.0.1"))
    p.add_argument("--port", type=int,
                   default=int(os.environ.get("DEOLTECH_PORT", "8000")))
    p.add_argument("--feed", default="", choices=["", "auto", "live", "synthetic"],
                   help="market data mode (default: stored setting, else auto)")
    p.add_argument("--secure-cookies", action="store_true",
                   help="set Secure on cookies; required when served over TLS")
    p.add_argument("--trust-proxy", action="store_true",
                   help="honour X-Forwarded-For (only behind YOUR reverse proxy)")
    p.add_argument("--debug", action="store_true")
    p.set_defaults(func=cmd_serve)

    p = sub.add_parser("admin", help="manage administrators")
    p.add_argument("admin_action", choices=["create", "list", "reset"])
    p.add_argument("username", nargs="?", default="admin")
    p.add_argument("--password", help="set explicitly (default: generate one)")
    p.add_argument("--email", default="")
    p.set_defaults(func=cmd_admin)

    p = sub.add_parser("quote", help="print live quotes")
    p.add_argument("symbols", nargs="+")
    p.add_argument("--feed", default="auto",
                   choices=["auto", "live", "synthetic"])
    p.set_defaults(func=cmd_quote)

    p = sub.add_parser("bars", help="print an OHLCV series")
    p.add_argument("symbol")
    p.add_argument("--interval", default="1d",
                   choices=["1m", "5m", "15m", "30m", "1h", "4h", "1d", "1w"])
    p.add_argument("--limit", type=int, default=120)
    p.add_argument("--show", type=int, default=20, help="rows to print")
    p.add_argument("--feed", default="auto",
                   choices=["auto", "live", "synthetic"])
    p.set_defaults(func=cmd_bars)

    p = sub.add_parser("probe", help="check every Finviz endpoint")
    p.set_defaults(func=cmd_probe)

    p = sub.add_parser("backtest", help="run a strategy over history")
    p.add_argument("strategy")
    p.add_argument("symbol")
    p.add_argument("--interval", default="1d")
    p.add_argument("--limit", type=int, default=400)
    p.add_argument("--cash", type=float, default=100_000.0)
    p.add_argument("--param", action="append", metavar="KEY=VALUE")
    p.add_argument("--feed", default="auto",
                   choices=["auto", "live", "synthetic"])
    p.add_argument("--json", action="store_true", help="also print raw JSON")
    p.set_defaults(func=cmd_backtest)

    p = sub.add_parser("strategies", help="list built-in strategies")
    p.set_defaults(func=cmd_strategies)

    p = sub.add_parser("instruments", help="list tradeable instruments")
    p.add_argument("asset_class", nargs="?",
                   choices=["equity", "crypto", "fx"], default=None)
    p.set_defaults(func=cmd_instruments)

    p = sub.add_parser("status", help="platform status")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("demo", help="seed a demo account with trades")
    p.add_argument("--username", default="demo")
    p.set_defaults(func=cmd_demo)

    p = sub.add_parser("backup", help="consistent online backup of the database")
    p.add_argument("dest", nargs="?", default="backups",
                   help="directory to write into (default: ./backups)")
    p.add_argument("--keep-days", type=int, default=30,
                   help="delete backups older than this (0 disables)")
    p.add_argument("--no-compress", action="store_true")
    p.set_defaults(func=cmd_backup)

    p = sub.add_parser("audit", help="print the audit log")
    p.add_argument("--limit", type=int, default=50)
    p.add_argument("--severity", choices=["info", "warning", "critical"])
    p.set_defaults(func=cmd_audit)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if getattr(args, "db", None):
        os.environ["DEOLTECH_DB"] = args.db
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130
    except Exception as e:                                 # noqa: BLE001
        print(f"error: {type(e).__name__}: {e}", file=sys.stderr)
        return 1
