"""Command line interface. `python -m polymkt --help`

Reading conventions used throughout the output:
  * a price IS a probability — 0.62 means the market says 62%
  * outcome prices should sum to ~100%; a drift is flagged
  * `mid` is what you would quote, `sweep` is what you would pay
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone

from . import config as C
from . import endpoints as E
from . import store as S
from .clob import Clob
from .data import Data
from .gamma import Gamma
from .http import Client, PolymarketError, TransportError
from .models import Market
from .samples import fake_transport

BOLD, DIM, GREEN, RED, RESET = "\033[1m", "\033[2m", "\033[32m", "\033[31m", "\033[0m"


def _rule(title: str = "") -> None:
    print(f"\n{BOLD}{title}{RESET}" if title else "")
    print("-" * 72)


def _pct(x: float | None) -> str:
    return "    ?" if x is None else f"{x * 100:5.1f}%"


def _money(x: float | None) -> str:
    if x is None:
        return "-"
    for unit, size in (("M", 1e6), ("k", 1e3)):
        if abs(x) >= size:
            return f"${x / size:,.1f}{unit}"
    return f"${x:,.0f}"


def _sparkline(values: list[float]) -> str:
    blocks = "▁▂▃▄▅▆▇█"
    if not values:
        return ""
    lo, hi = min(values), max(values)
    span = hi - lo
    if span < 1e-9:
        return blocks[0] * len(values)
    return "".join(blocks[min(7, int((v - lo) / span * 7.999))] for v in values)


def _clients(a) -> tuple[Gamma, Clob, Data]:
    transport = fake_transport if getattr(a, "offline", False) else None
    kw = {"transport": transport} if transport else {}
    return Gamma(**kw), Clob(**kw), Data(**kw)


def _show_market(m: Market, *, show_tokens: bool = True) -> None:
    flag = f"{DIM}closed{RESET}" if m.closed else ""
    print(f"\n{BOLD}{m.question}{RESET} {flag}")
    print(f"  {DIM}{m.slug}   condition {m.condition_id}{RESET}")
    for o in m.outcomes:
        token = f"  {DIM}{o.token_id}{RESET}" if show_tokens and o.token_id else ""
        bar = "█" * int((o.price or 0) * 24)
        print(f"  {o.name[:22]:<22} {_pct(o.price)}  {bar:<24}{token}")
    total = m.book_sum()
    if total is not None and abs(total - 1.0) > 0.02:
        # Not necessarily an arb: stale prices and multi-outcome rounding
        # both do this. Worth seeing before you trust the numbers.
        print(f"  {RED}outcomes sum to {total * 100:.1f}%, not 100%{RESET}")
    bits = [f"vol {_money(m.volume)}", f"24h {_money(m.volume_24h)}",
            f"liq {_money(m.liquidity)}"]
    if m.end_date:
        bits.append(f"ends {m.end_date[:10]}")
    if m.neg_risk:
        bits.append("neg-risk")
    print(f"  {DIM}{'  ·  '.join(bits)}{RESET}")


# --------------------------------------------------------------- commands


def cmd_search(a) -> int:
    gamma, _, _ = _clients(a)
    found = gamma.search(a.query, limit=a.limit)
    events, markets = found["events"], found["markets"]
    if not events and not markets:
        print(f"nothing matched {a.query!r}")
        return 1
    if events:
        _rule(f"EVENTS matching {a.query!r}")
        for e in events:
            print(f"  {e.slug:<44} {_money(e.volume):>9}  {e.title[:60]}")
    if markets:
        _rule(f"MARKETS matching {a.query!r}")
        for m in markets:
            _show_market(m)
    return 0


def cmd_markets(a) -> int:
    gamma, _, _ = _clients(a)
    markets = gamma.markets(limit=a.limit, closed=a.closed, volume_min=a.min_volume)
    _rule(f"TOP {len(markets)} MARKETS BY VOLUME")
    for m in markets:
        _show_market(m, show_tokens=a.tokens)
    return 0


def cmd_events(a) -> int:
    gamma, _, _ = _clients(a)
    _rule("EVENTS")
    for e in gamma.events(limit=a.limit, closed=a.closed):
        print(f"\n{BOLD}{e.title}{RESET}  {DIM}{e.slug}{RESET}")
        print(f"  {DIM}vol {_money(e.volume)}  ·  liq {_money(e.liquidity)}  ·  "
              f"{len(e.markets)} market(s){RESET}")
        for m in e.markets[:a.limit]:
            fav = m.favourite()
            lead = f"{fav.name} {_pct(fav.price)}" if fav else "-"
            print(f"    {m.question[:52]:<52} {lead}")
    return 0


def _resolve(gamma: Gamma, key: str) -> Market:
    """Accept a slug, a numeric market id, or a condition id."""
    try:
        return gamma.market_by_slug(key)
    except (LookupError, PolymarketError):
        pass
    if key.isdigit():
        return gamma.market(key)
    # Filter by condition id, but verify the answer: a server that ignores
    # an unknown filter parameter returns row 0 of everything, and taking
    # it on trust hands back a confidently wrong market.
    for m in gamma.markets(limit=5, condition_ids=key):
        if key in (m.condition_id, m.slug, m.id):
            return m
    raise LookupError(f"no market matched {key!r} (try a slug from the market URL)")


def cmd_market(a) -> int:
    gamma, clob, _ = _clients(a)
    market = _resolve(gamma, a.key)
    _show_market(market)
    if a.live:
        _rule("LIVE BOOK")
        for o in market.outcomes:
            if not o.token_id:
                continue
            q = clob.quote(o.token_id)
            print(f"  {o.name[:18]:<18} bid {_pct(q['bid'])}  ask {_pct(q['ask'])}  "
                  f"mid {_pct(q['mid'])}  {DIM}depth {_money(q['bid_depth'])} / "
                  f"{_money(q['ask_depth'])}{RESET}")
    conn = S.connect()
    S.cache_market(conn, market)
    conn.close()
    return 0


def cmd_book(a) -> int:
    _, clob, _ = _clients(a)
    book = clob.book(a.token_id)
    _rule(f"BOOK {a.token_id}")
    if not book.bids and not book.asks:
        print("  empty book — check the token id (it is not the condition id)")
        return 1
    print(f"  {'BID':>22}    |    {'ASK':<22}")
    rows = min(a.depth, max(len(book.bids), len(book.asks)))
    for i in range(rows):
        bid = book.bids[i] if i < len(book.bids) else None
        ask = book.asks[i] if i < len(book.asks) else None
        left = f"{bid.size:>10,.0f} @ {_pct(bid.price)}" if bid else " " * 22
        right = f"{_pct(ask.price)} @ {ask.size:<10,.0f}" if ask else ""
        print(f"  {left:>22}    |    {right:<22}")
    print(f"\n  mid {_pct(book.midpoint)}   spread "
          f"{'?' if book.spread is None else f'{book.spread * 100:.1f}pp'}")
    avg, filled = book.sweep(a.size)
    if avg:
        slip = (avg - (book.midpoint or avg)) * 100
        note = f"  ({RED}{slip:+.1f}pp vs mid{RESET})" if abs(slip) > 0.05 else ""
        print(f"  buying ${filled:,.0f} fills at avg {_pct(avg)}{note}")
        if filled < a.size - 1:
            print(f"  {RED}book runs out — only ${filled:,.0f} of ${a.size:,.0f} "
                  f"is available{RESET}")
    return 0


def cmd_history(a) -> int:
    _, clob, _ = _clients(a)
    rows = clob.history(a.token_id, interval=a.interval, fidelity=a.fidelity)
    if not rows:
        print("no history returned — check the token id and interval")
        return 1
    prices = [r["p"] for r in rows]
    _rule(f"HISTORY {a.token_id}  ({a.interval}, {len(rows)} points)")
    print(f"  {_sparkline(prices)}")
    first, last = prices[0], prices[-1]
    arrow = f"{GREEN}▲{RESET}" if last >= first else f"{RED}▼{RESET}"
    print(f"  {_pct(first)} -> {_pct(last)}  {arrow} {(last - first) * 100:+.1f}pp"
          f"   {DIM}range {_pct(min(prices))}-{_pct(max(prices))}{RESET}")
    return 0


def cmd_watch(a) -> int:
    conn = S.connect()
    if a.action == "list":
        rows = S.watch_list(conn)
        if not rows:
            print("watchlist empty — `polymkt watch add <market-slug>`")
            return 0
        _rule(f"WATCHLIST ({len(rows)})")
        for w in rows:
            q = S.latest_quote(conn, w["token_id"])
            mid = _pct(q["mid"]) if q and q["mid"] is not None else "    -"
            seen = f"{DIM}{q['captured_at'][:16]}{RESET}" if q else f"{DIM}never snapped{RESET}"
            print(f"  {mid}  {w['outcome'][:10]:<10} {w['question'][:44]:<44} {seen}")
            print(f"         {DIM}{w['token_id']}{RESET}")
        return 0

    if a.action == "rm":
        removed = S.watch_remove(conn, a.key)
        print(f"removed {a.key}" if removed else f"{a.key} was not on the watchlist")
        return 0 if removed else 1

    gamma, _, _ = _clients(a)
    market = _resolve(gamma, a.key)
    added = 0
    for o in market.outcomes:
        if not o.token_id:
            continue
        if a.outcome and o.name.strip().lower() != a.outcome.strip().lower():
            continue
        S.watch_add(conn, o.token_id, condition_id=market.condition_id,
                    slug=market.slug, question=market.question, outcome=o.name,
                    note=a.note)
        print(f"watching {o.name} @ {_pct(o.price)}  {DIM}{o.token_id}{RESET}")
        added += 1
    if not added:
        print(f"no outcome matched {a.outcome!r}; market has: "
              f"{', '.join(o.name for o in market.outcomes)}")
        return 1
    return 0


def cmd_snap(a) -> int:
    """Take one snapshot of every watched token. Run it from cron."""
    conn = S.connect()
    _, clob, _ = _clients(a)
    watched = S.watch_list(conn)
    if not watched:
        print("watchlist empty — nothing to snapshot")
        return 1
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    ok, failed = 0, 0
    for w in watched:
        try:
            quote = clob.quote(w["token_id"])
        except (PolymarketError, TransportError) as exc:
            # One dead token must not abort the sweep.
            print(f"  {RED}skip{RESET} {w['question'][:40]}: {exc}", file=sys.stderr)
            failed += 1
            continue
        quote["captured_at"] = stamp
        S.record_quote(conn, quote)
        ok += 1
        if a.verbose:
            print(f"  {_pct(quote['mid'])}  {w['outcome'][:8]:<8} {w['question'][:44]}")
    print(f"snapped {ok} token(s) at {stamp}" + (f", {failed} failed" if failed else ""))
    return 0 if ok else 1


def cmd_moves(a) -> int:
    conn = S.connect()
    rows = S.moves(conn, days=a.days)
    if not rows:
        print("watchlist empty — `polymkt watch add <market-slug>`")
        return 1
    _rule(f"MOVES · last {a.days} day(s)")
    for r in rows:
        if not r["samples"]:
            print(f"      -   {DIM}no snapshots{RESET}  {r['question'][:44]}")
            continue
        change = r["change_pp"]
        colour = GREEN if change > 0 else RED if change < 0 else DIM
        # Two snapshots is a line, not a trend. Say so rather than implying one.
        n = r["samples"]
        weak = f" {DIM}(only {n} snapshot{'' if n == 1 else 's'}){RESET}" if n < 3 else ""
        print(f"  {colour}{change:+6.1f}pp{RESET}  {_pct(r['first'])} -> {_pct(r['last'])}"
              f"  {r['outcome'][:8]:<8} {r['question'][:40]:<40}{weak}")
    return 0


def cmd_positions(a) -> int:
    _, _, data = _clients(a)
    address = a.address or C.address()
    if not address:
        print("no address given and POLYMKT_ADDRESS is not set", file=sys.stderr)
        return 1
    if not C.is_address(address):
        print(f"{address!r} is not a 0x-prefixed 40-hex address", file=sys.stderr)
        return 1
    a.address = address
    positions = data.positions(address, limit=a.limit)
    if not positions:
        print(f"no open positions for {a.address}")
        return 0
    _rule(f"POSITIONS · {a.address}")
    total = 0.0
    for p in positions:
        total += p.value or 0.0
        pnl = p.pnl or 0.0
        colour = GREEN if pnl > 0 else RED if pnl < 0 else ""
        print(f"  {p.outcome[:8]:<8} {p.size:>10,.0f} @ {_pct(p.avg_price)} "
              f"now {_pct(p.current_price)}  {_money(p.value):>8}  "
              f"{colour}{pnl:+,.0f}{RESET}  {p.title[:40]}")
    print(f"\n  {BOLD}portfolio {_money(total)}{RESET}")
    return 0


def cmd_whoami(a) -> int:
    """What this install is configured with. Prints no secrets."""
    _rule("CONFIG")
    addr = C.address()
    print(f"  address    {addr or f'{DIM}unset{RESET}  (export POLYMKT_ADDRESS=0x…)'}")
    print(f"  database   {S.db_path()}")
    print(f"  auth       {C.credential_status()}")
    if addr:
        print(f"\n  {DIM}polymkt positions   # reads this address{RESET}")
    return 0


def cmd_endpoints(a) -> int:
    _rule("ENDPOINT CATALOG")
    print(f"  {DIM}confidence: documented = from Polymarket's published overview, "
          f"recall = unverified{RESET}\n")
    for service, base in E.SERVICES.items():
        rows = E.for_service(service)
        print(f"{BOLD}{service}{RESET}  {base}" + ("" if rows else f"  {DIM}(no client yet){RESET}"))
        for e in rows:
            mark = {"documented": f"{GREEN}doc{RESET}", "verified": f"{GREEN}ok!{RESET}"}.get(
                e.confidence, f"{DIM}rec{RESET}")
            print(f"   {mark}  {e.method:<4} {e.path:<28} {e.summary[:44]}")
        print()
    for name, url in E.WEBSOCKETS.items():
        print(f"{DIM}ws.{name:<8} {url}{RESET}")
    return 0


def cmd_doctor(a) -> int:
    """Probe the catalog against the live API and report what answers.

    This is the honest counterweight to a hand-written endpoint list: it
    replaces belief with evidence, one request at a time.
    """
    _rule("DOCTOR")
    probes = E.probeable()
    passed, failed = 0, 0
    for e in probes:
        client = (Client(E.SERVICES[e.service], transport=fake_transport)
                  if a.offline else Client(E.SERVICES[e.service]))
        try:
            payload = client.request(e.method, e.path, params=e.probe)
        except (PolymarketError, TransportError) as exc:
            # Strip the base URL: it is the same on every line, and the
            # reason is the only part worth the width.
            reason = str(exc).replace(E.SERVICES[e.service], "").lstrip(": ")
            print(f"  {RED}FAIL{RESET} {e.name:<26} {reason[:56]}")
            failed += 1
            continue
        n = len(payload) if isinstance(payload, (list, dict)) else 1
        print(f"  {GREEN}ok{RESET}   {e.name:<26} {e.method} {e.path} -> {n} field(s)/row(s)")
        passed += 1
    skipped = [e for e in E.CATALOG if e.probe is None]
    print(f"\n  {passed} passed, {failed} failed, {len(skipped)} need an id "
          f"(token/address/slug) and were skipped")
    if failed:
        print(f"  {DIM}a blocked network and a wrong path look the same here — "
              f"check reachability before editing endpoints.py{RESET}")
    return 0 if failed == 0 else 1


def cmd_demo(a) -> int:
    """The whole pipeline on synthetic data. No network, no account."""
    a.offline = True
    gamma, clob, _ = _clients(a)
    conn = S.connect()

    _rule("DEMO · synthetic data, no network")
    print(f"  {DIM}every number below is invented; see src/polymkt/samples.py{RESET}")

    markets = gamma.markets(limit=3)
    for m in markets:
        _show_market(m)

    fed = markets[0]
    conn_watch = [o for o in fed.outcomes if o.token_id]
    for o in conn_watch:
        S.watch_add(conn, o.token_id, condition_id=fed.condition_id, slug=fed.slug,
                    question=fed.question, outcome=o.name)

    # Two snapshots an hour apart, so `moves` has something to chew on.
    for shift, stamp in ((0.0, "2026-08-23T09:00:00+00:00"),
                         (0.04, "2026-08-24T09:00:00+00:00")):
        for o in conn_watch:
            q = clob.quote(o.token_id)
            if q["mid"] is not None:
                q["mid"] += shift
            q["captured_at"] = stamp
            S.record_quote(conn, q)

    _rule("BOOK · what the midpoint doesn't tell you")
    book = clob.book(fed.outcomes[0].token_id)
    avg, filled = book.sweep(2000)
    print(f"  mid {_pct(book.midpoint)}  but ${filled:,.0f} of size fills at "
          f"{_pct(avg)} — {((avg or 0) - (book.midpoint or 0)) * 100:+.1f}pp of slippage")

    _rule("MOVES")
    for r in S.moves(conn, days=7):
        if r["change_pp"] is None:
            print(f"       -   {DIM}no priced snapshots{RESET}  {r['outcome'][:8]}")
            continue
        print(f"  {r['change_pp']:+6.1f}pp  {_pct(r['first'])} -> {_pct(r['last'])}"
              f"  {r['outcome'][:8]:<8} {r['question'][:40]}  "
              f"{DIM}n={r['samples']}{RESET}")

    print(f"\n  {DIM}db: {S.db_path()}   (delete it to reset the demo){RESET}")
    conn.close()
    return 0


# ----------------------------------------------------------------- parser


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="polymkt",
        description="Read Polymarket: discover markets, read live prices, "
                    "track how probabilities move.")
    p.add_argument("--offline", action="store_true",
                   help="use bundled synthetic data instead of the network")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("search", help="free-text search for events and markets")
    s.add_argument("query")
    s.add_argument("--limit", type=int, default=5)
    s.set_defaults(func=cmd_search)

    s = sub.add_parser("markets", help="top markets by volume")
    s.add_argument("--limit", type=int, default=10)
    s.add_argument("--min-volume", type=float, default=None)
    s.add_argument("--closed", action="store_true", default=False)
    s.add_argument("--tokens", action="store_true", help="show CLOB token ids")
    s.set_defaults(func=cmd_markets)

    s = sub.add_parser("events", help="top events, with their markets")
    s.add_argument("--limit", type=int, default=5)
    s.add_argument("--closed", action="store_true", default=False)
    s.set_defaults(func=cmd_events)

    s = sub.add_parser("market", help="one market by slug, id or condition id")
    s.add_argument("key")
    s.add_argument("--live", action="store_true", help="also read the live books")
    s.set_defaults(func=cmd_market)

    s = sub.add_parser("book", help="order book for one outcome token")
    s.add_argument("token_id")
    s.add_argument("--depth", type=int, default=8)
    s.add_argument("--size", type=float, default=1000.0,
                   help="USD to simulate buying, for slippage")
    s.set_defaults(func=cmd_book)

    s = sub.add_parser("history", help="price history for one outcome token")
    s.add_argument("token_id")
    s.add_argument("--interval", default="1w", help="1h, 6h, 1d, 1w, 1m, max")
    s.add_argument("--fidelity", type=int, default=None, help="resolution in minutes")
    s.set_defaults(func=cmd_history)

    s = sub.add_parser("watch", help="manage the watchlist")
    s.add_argument("action", choices=["add", "list", "rm"])
    s.add_argument("key", nargs="?", help="market slug to add, or token id to remove")
    s.add_argument("--outcome", help="watch only this outcome (default: all)")
    s.add_argument("--note")
    s.set_defaults(func=cmd_watch)

    s = sub.add_parser("snap", help="snapshot every watched token (cron-friendly)")
    s.add_argument("--verbose", "-v", action="store_true")
    s.set_defaults(func=cmd_snap)

    s = sub.add_parser("moves", help="biggest probability changes on the watchlist")
    s.add_argument("--days", type=int, default=7)
    s.set_defaults(func=cmd_moves)

    s = sub.add_parser("positions", help="open positions for an address")
    s.add_argument("address", nargs="?", help="defaults to $POLYMKT_ADDRESS")
    s.add_argument("--limit", type=int, default=50)
    s.set_defaults(func=cmd_positions)

    s = sub.add_parser("whoami", help="show configured address and db path")
    s.set_defaults(func=cmd_whoami)

    s = sub.add_parser("endpoints", help="print the endpoint catalog and provenance")
    s.set_defaults(func=cmd_endpoints)

    s = sub.add_parser("doctor", help="probe the catalog against the live API")
    s.set_defaults(func=cmd_doctor)

    s = sub.add_parser("demo", help="the whole pipeline on synthetic data")
    s.set_defaults(func=cmd_demo)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except TransportError as exc:
        print(f"{RED}network error{RESET}: {exc}", file=sys.stderr)
        print(f"{DIM}if this environment blocks polymarket.com, "
              f"try `polymkt demo` or --offline{RESET}", file=sys.stderr)
        return 2
    except (PolymarketError, LookupError) as exc:
        print(f"{RED}error{RESET}: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
