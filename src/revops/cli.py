"""Command line interface. `python -m revops --help`"""

from __future__ import annotations

import argparse
import sys

from . import analytics as A
from . import ledger as L
from . import monetization as M
from .db import connect, db_path


def _money(x: float) -> str:
    return f"${x:,.2f}"


def _rule(title: str = "") -> None:
    print(f"\n\033[1m{title}\033[0m" if title else "")
    print("-" * 66)


# --------------------------------------------------------------- commands


def cmd_new(conn, a) -> None:
    cid = L.add_content(
        conn, a.title, fmt=a.format, topic=a.topic, hook_type=a.hook,
        series=a.series, duration_s=a.duration, cost_usd=a.cost,
        minutes=a.minutes, pipeline=a.pipeline, notes=a.notes,
    )
    row = conn.execute("SELECT slug FROM content WHERE id = ?", (cid,)).fetchone()
    print(f"logged content #{cid}  ({row['slug']})")


def cmd_post(conn, a) -> None:
    for platform in a.platforms:
        L.add_post(conn, a.content, platform, url=a.url)
        print(f"posted #{a.content} -> {platform}")


def cmd_track(conn, a) -> None:
    L.add_metrics(
        conn, a.content, a.platform, views=a.views, likes=a.likes,
        comments=a.comments, shares=a.shares, followers_gained=a.followers,
        clicks=a.clicks, watch_time_s=a.watch_time,
    )
    print(f"tracked {a.platform}: {a.views:,} views on #{a.content}")


def cmd_earn(conn, a) -> None:
    if a.stream not in M.STREAM_KEYS:
        print(f"warning: '{a.stream}' is not a known stream "
              f"({', '.join(sorted(M.STREAM_KEYS))})", file=sys.stderr)
    L.add_revenue(conn, a.stream, a.amount, platform=a.platform,
                  content_ref=a.content, notes=a.notes)
    print(f"recorded {_money(a.amount)} from {a.stream}")


def cmd_spend(conn, a) -> None:
    L.add_cost(conn, a.category, a.amount, recurring=a.recurring, notes=a.notes)
    print(f"recorded {_money(a.amount)} cost ({a.category})")


def cmd_streams(conn, a) -> None:
    _rule("REVENUE STREAMS")
    for s in M.readiness(conn):
        if s["active"]:
            mark, tag = "\033[32m●\033[0m", f"active · {_money(s['earned_to_date'])} to date"
        elif s["ready"]:
            mark, tag = "\033[33m○\033[0m", "READY — not yet earning"
        else:
            mark, tag = "\033[90m·\033[0m", "locked"
        print(f"\n{mark} \033[1m{s['name']}\033[0m — {tag}")
        print(f"    potential: {s['early_monthly_usd']}/mo · effort: {s['effort']}")
        if s["blockers"]:
            print(f"    blocked by: {', '.join(s['blockers'])}")
        elif not s["active"]:
            for step in s["activation"]:
                print(f"      → {step}")


def cmd_report(conn, a) -> None:
    d = a.days
    p = A.pnl(conn, d)

    _rule(f"P&L — LAST {d} DAYS")
    print(f"  revenue        {_money(p['revenue']):>12}")
    for k, v in p["revenue_by_stream"].items():
        print(f"    {k:<26} {_money(v):>10}")
    print(f"  cost           {_money(p['cost']):>12}")
    print(f"  \033[1mprofit         {_money(p['profit']):>12}\033[0m")
    print(f"\n  {p['content_made']} pieces · {p['hours']:.1f} hrs · "
          f"{_money(p['cost_per_content'])}/piece")
    if p["hours"]:
        print(f"  effective hourly: {_money(p['effective_hourly'])}/hr")

    plats = A.platform_efficiency(conn, d)
    if plats:
        _rule("PLATFORMS")
        print(f"  {'platform':<12}{'posts':>6}{'views':>11}{'views/post':>12}"
              f"{'eng%':>7}{'ctr%':>7}{'rpm':>8}")
        for r in plats:
            print(f"  {r['platform']:<12}{r['posts']:>6}{r['views']:>11,}"
                  f"{r['views_per_post']:>12,.0f}{r['engagement_rate']*100:>7.1f}"
                  f"{r['ctr']*100:>7.2f}{r['rpm']:>8.2f}")

    for dim in ("topic", "hook_type"):
        rows = [r for r in A.by_dimension(conn, dim, d) if r[dim] != "(unset)"]
        if not rows:
            continue
        _rule(f"BY {dim.upper()}")
        print(f"  {dim:<24}{'n':>4}{'median':>10}{'best':>11}{'revenue':>10}")
        for r in rows:
            flag = "" if r["confident"] else "  (low n)"
            print(f"  {str(r[dim])[:23]:<24}{r['n']:>4}{r['median_views']:>10,.0f}"
                  f"{r['best_views']:>11,}{_money(r['revenue']):>10}{flag}")

    recs = A.recommendations(conn, d)
    if recs:
        _rule("WHAT TO DO NEXT")
        for r in recs:
            print(f"  • {r}")
    print()


def cmd_today(conn, a) -> None:
    """The 1-2 hours/day surface: what happened, what to do now."""
    p7, p30 = A.pnl(conn, 7), A.pnl(conn, 30)
    _rule("TODAY")
    print(f"  last 7d   {_money(p7['revenue']):>10} revenue   "
          f"{p7['content_made']} made   {_money(p7['profit'])} profit")
    print(f"  last 30d  {_money(p30['revenue']):>10} revenue   "
          f"{p30['content_made']} made   {_money(p30['profit'])} profit")

    ready = [s for s in M.readiness(conn) if s["ready"] and not s["active"]]
    if ready:
        _rule("MONEY ON THE TABLE")
        for s in ready:
            print(f"  \033[33m○\033[0m {s['name']} — unlocked, earning nothing "
                  f"({s['early_monthly_usd']}/mo)")
            print(f"      → {s['activation'][0]}")

    tb = A.top_and_bottom(conn, 30, k=3)
    if tb["top"]:
        _rule("BEST OF LAST 30 DAYS")
        for r in tb["top"]:
            print(f"  {r['views']:>9,} views  {r['title'][:38]:<40}"
                  f"{r['topic'] or '-'}")
        print("\n  Make the next three pieces resemble these.")

    recs = A.recommendations(conn, 30)
    if recs:
        _rule("ACTIONS")
        for r in recs:
            print(f"  • {r}")
    print()


def cmd_dash(conn, a) -> None:
    from .dashboard import render
    out = render(conn, days=a.days, path=a.out)
    print(f"dashboard written to {out}")


def cmd_demo(conn, a) -> None:
    from .demo import seed
    seed(conn)
    print("seeded example data — try `python -m revops report` and `python -m revops today`")


# ------------------------------------------------------------------ parser


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="revops",
        description="Revenue operating system for an AI-content studio.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    n = sub.add_parser("new", help="log a piece of content you made")
    n.add_argument("title")
    n.add_argument("--format", default="short", choices=sorted(L.VALID_FORMATS))
    n.add_argument("--topic")
    n.add_argument("--hook", help="opening device, e.g. cold-open-punchline")
    n.add_argument("--series")
    n.add_argument("--duration", type=float, help="seconds")
    n.add_argument("--cost", type=float, default=0.0, help="credits/API spend in USD")
    n.add_argument("--minutes", type=float, default=0.0, help="your time")
    n.add_argument("--pipeline", help="which tool chain made it")
    n.add_argument("--notes")
    n.set_defaults(fn=cmd_new)

    po = sub.add_parser("post", help="record that content went live somewhere")
    po.add_argument("content", help="content id or slug")
    po.add_argument("platforms", nargs="+")
    po.add_argument("--url")
    po.set_defaults(fn=cmd_post)

    t = sub.add_parser("track", help="record a performance snapshot")
    t.add_argument("content")
    t.add_argument("platform")
    t.add_argument("--views", type=int, default=0)
    t.add_argument("--likes", type=int, default=0)
    t.add_argument("--comments", type=int, default=0)
    t.add_argument("--shares", type=int, default=0)
    t.add_argument("--followers", type=int, default=0)
    t.add_argument("--clicks", type=int, default=0)
    t.add_argument("--watch-time", type=float, default=0.0, dest="watch_time")
    t.set_defaults(fn=cmd_track)

    e = sub.add_parser("earn", help="record money in")
    e.add_argument("stream")
    e.add_argument("amount", type=float)
    e.add_argument("--platform")
    e.add_argument("--content")
    e.add_argument("--notes")
    e.set_defaults(fn=cmd_earn)

    s = sub.add_parser("spend", help="record money out")
    s.add_argument("category", choices=sorted(L.VALID_COST_CATEGORIES))
    s.add_argument("amount", type=float)
    s.add_argument("--recurring", action="store_true")
    s.add_argument("--notes")
    s.set_defaults(fn=cmd_spend)

    for name, fn, helptext in (
        ("today", cmd_today, "the daily brief — start here"),
        ("streams", cmd_streams, "which revenue streams are unlocked"),
        ("demo", cmd_demo, "seed example data to see the system work"),
    ):
        q = sub.add_parser(name, help=helptext)
        q.set_defaults(fn=fn)

    r = sub.add_parser("report", help="full performance analysis")
    r.add_argument("--days", type=int, default=30)
    r.set_defaults(fn=cmd_report)

    d = sub.add_parser("dash", help="write an HTML dashboard")
    d.add_argument("--days", type=int, default=30)
    d.add_argument("--out", default="out/dashboard.html")
    d.set_defaults(fn=cmd_dash)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    conn = connect()
    try:
        args.fn(conn, args)
    except (LookupError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
