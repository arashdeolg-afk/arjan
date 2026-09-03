"""Command line interface. `python -m revops --help`"""

from __future__ import annotations

import argparse
import sys
import textwrap

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
    from . import sprint as S
    st = S.status(conn)
    if st.get("started") and st["remaining"] > 0:
        pct = (st["earned"] / st["goal"] * 100) if st["goal"] else 0
        bar = "\u2588" * int(pct / 5) + "\u2591" * (20 - int(pct / 5))
        _rule("SPRINT")
        print(f"  {bar}  {_money(st['earned'])} / {_money(st['goal'])}"
              f"   {st['days_left']:.1f}d left")
        print(f"  \033[1mcontact {st['per_day']:.0f} prospects today\033[0m"
              f"   ({st['contacted_so_far']} sent so far)")
        fu = S.followups(conn)
        if fu:
            print(f"  {len(fu)} waiting on a follow-up — `revops followups`")

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


def cmd_ingest(conn, a) -> None:
    """Bulk-load a platform export. Reports what it could not match."""
    from . import ingest as I

    overrides = {}
    for pair in a.map or []:
        if "=" not in pair:
            raise ValueError(f"--map needs COLUMN=field, got {pair!r}")
        column, field = pair.split("=", 1)
        field = field.strip()
        if field not in I.METRIC_FIELDS + I.IDENTITY_FIELDS:
            raise ValueError(
                f"unknown field {field!r} — pick from "
                f"{', '.join(I.METRIC_FIELDS + I.IDENTITY_FIELDS)}"
            )
        overrides[column.strip()] = field

    try:
        r = I.ingest_file(
            conn, a.path, a.platform, captured_at=a.captured_at,
            dry_run=a.dry_run, force=a.force, overrides=overrides,
        )
    except I.IngestError as exc:
        raise ValueError(str(exc)) from exc

    _rule(f"INGEST — {a.platform.lower()} — {r['rows_read']} rows read")

    if r["aborted"]:
        print("  \033[31mrefused\033[0m — nothing written.\n")
        for line in textwrap.wrap(r["abort_reason"], 64):
            print(f"  {line}")
        for g in r["regressions"][:5]:
            print(f"    {g['label'][:44]:<46}{g['was']:>10,} -> {g['now']:>10,}")
        print()
        return

    verb = "would write" if a.dry_run else "wrote"
    print(f"  {verb:<14}{len(r['write']):>5} snapshots at {r['captured_at']}")
    if r["duplicates"]:
        print(f"  {'skipped':<14}{len(r['duplicates']):>5} already imported at this timestamp")

    if r["regressions"]:
        _rule("VIEWS WENT DOWN")
        print("  Lifetime totals should only rise. Check these are not a daily export.")
        for g in r["regressions"][:10]:
            print(f"  {g['label'][:44]:<46}{g['was']:>10,} -> {g['now']:>10,}")

    if r["unmatched"]:
        _rule(f"UNMATCHED — {len(r['unmatched'])} rows NOT imported")
        print("  These rows name something this database does not know about.")
        print("  Left alone they would silently bias every ranking, so they are skipped.\n")
        for u in r["unmatched"][:15]:
            print(f"  \033[33m{u['label'][:56]}\033[0m")
            print(f"      {u['reason']}")
            print(f"      fix: {I.fix_command(u, a.platform)}")
        if len(r["unmatched"]) > 15:
            print(f"\n  ...and {len(r['unmatched']) - 15} more.")
        print("\n  Tip: add a 'slug' column to the export for exact matching.")

    if a.dry_run:
        print("\n  Dry run — nothing written. Re-run without --dry-run to commit.")
    elif r["written"]:
        print(f"\n  Next: python3 -m revops report")
    print()


def cmd_dash(conn, a) -> None:
    from .dashboard import render
    out = render(conn, days=a.days, path=a.out)
    print(f"dashboard written to {out}")


def cmd_demo(conn, a) -> None:
    from .demo import seed
    seed(conn)
    print("seeded example data — try `python -m revops report` and `python -m revops today`")



def cmd_sprint(conn, a) -> None:
    from . import sprint as S
    S.start_sprint(conn, a.goal, a.price, a.days)
    st = S.status(conn)
    _rule(f"{a.days}-DAY SPRINT STARTED")
    print(f"  goal            {_money(a.goal)} at {_money(a.price)}/spot")
    print(f"  sales needed    {st['wins_needed']:.0f}")
    print(f"  contacts/win    {st['contacts_per_win']:.0f}  (assumption until your data replaces it)")
    print(f"  total outreach  {st['contacts_needed']:.0f}")
    print(f"  \033[1mper day         {st['per_day']:.0f} prospects\033[0m")
    print("\n  Read docs/SPRINT.md for the day-by-day plan and the message copy.\n")


def cmd_lead(conn, a) -> None:
    from . import sprint as S
    if a.action == "add":
        lid = S.add_lead(conn, a.name, handle=a.handle, channel=a.channel,
                         segment=a.segment, product=a.product, source=a.source,
                         notes=a.notes)
        print(f"lead #{lid}: {a.name}")
    elif a.action == "set":
        row = S.set_stage(conn, a.name, a.stage, amount=a.amount, notes=a.notes)
        extra = f" — {_money(row['closed_usd'])}" if row.get("closed_usd") else ""
        print(f"#{row['id']} {row['name']} -> {a.stage}{extra}")
        if a.stage == "won":
            print("  revenue recorded automatically.")
    elif a.action == "import":
        n = _import_leads(conn, a.name)
        print(f"imported {n} leads from {a.name}")
        print("next: `revops lead list --stage sourced` to see who needs a spec clip")
    elif a.action == "list":
        q = ("SELECT * FROM leads WHERE (? IS NULL OR stage = ?) "
             "ORDER BY CASE stage WHEN 'won' THEN 0 ELSE 1 END, last_touch_at DESC")
        rows = [dict(r) for r in conn.execute(q, (a.stage, a.stage))]
        if not rows:
            print("no leads yet — `revops lead add \"Name\" --segment indie-game`")
            return
        _rule("LEADS")
        print(f"  {'#':>3} {'name':<26}{'segment':<14}{'stage':<13}{'outcome':<9}")
        for r in rows:
            print(f"  {r['id']:>3} {(r['name'] or '')[:25]:<26}"
                  f"{(r['segment'] or '-')[:13]:<14}{r['stage']:<13}"
                  f"{r['outcome'] or '-':<9}")



def _import_leads(conn, path: str) -> int:
    """Bulk-load prospects from CSV so day one is 20 minutes, not two hours.

    Columns: name, handle, channel, segment, product, source, notes.
    Only `name` is required; unknown columns are ignored.
    """
    import csv
    from . import sprint as S

    with open(path, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    fields = {"handle", "channel", "segment", "product", "source", "notes"}
    n = 0
    for row in rows:
        clean = {(k or "").strip().lower(): (v or "").strip()
                 for k, v in row.items() if k}
        name = clean.get("name")
        if not name:
            continue
        S.add_lead(conn, name, **{k: (clean.get(k) or None) for k in fields})
        n += 1
    return n


def cmd_pipeline(conn, a) -> None:
    from . import sprint as S
    st = S.status(conn)
    if not st["started"]:
        print("no sprint running — `revops sprint --goal 600 --price 200`")
        return

    _rule("SPRINT PIPELINE")
    pct = (st["earned"] / st["goal"] * 100) if st["goal"] else 0
    bar = "█" * int(pct / 5) + "░" * (20 - int(pct / 5))
    print(f"  {bar}  {_money(st['earned'])} / {_money(st['goal'])}  ({pct:.0f}%)")
    print(f"  {st['days_left']:.1f} days left\n")

    f = st["funnel"]
    for stage in S.STAGES:
        n = f[stage]
        print(f"  {stage:<14}{n:>4}  {'▪' * min(n, 40)}")

    r = S.rates(conn)
    _rule("CONVERSION")
    for (a_, b_), v in r.items():
        obs = f"{v['observed'] * 100:.0f}%" if v["observed"] is not None else "—"
        tag = "" if v["trusted"] else "  (using assumption)"
        pair = f"{a_} -> {b_}"
        print(f"  {pair:<34}{v['rate'] * 100:>5.0f}%   yours: {obs:>5}{tag}")

    _rule("TO STAY ON TRACK")
    if st["remaining"] <= 0:
        print("  \033[32mGoal hit. Raise the price and keep going.\033[0m")
    else:
        print(f"  {st['still_to_contact']:.0f} more prospects to contact "
              f"({st['per_day']:.0f}/day for {st['days_left']:.1f} days)")
        mark = "\033[32mon track\033[0m" if st["on_track"] else "\033[33mbehind — raise volume today\033[0m"
        print(f"  status: {mark}")

    fu = S.followups(conn)
    if fu:
        _rule("FOLLOW UP TODAY")
        print("  Most deals die from silence, not rejection.")
        for r_ in fu[:10]:
            print(f"  #{r_['id']:<4}{(r_['name'] or '')[:28]:<30}{r_['stage']:<13}"
                  f"{r_['followup_count']} sent")

    segs = [s for s in S.by_segment(conn) if s["contacted"] >= 3]
    if len(segs) >= 2:
        _rule("WHICH SEGMENT WORKS")
        for s_ in segs:
            rr = f"{s_['reply_rate'] * 100:.0f}%" if s_["reply_rate"] is not None else "—"
            print(f"  {s_['segment']:<18}{s_['contacted']:>4} sent{rr:>7} reply"
                  f"{s_['won']:>4} won{_money(s_['revenue']):>10}")
    print()


def cmd_followups(conn, a) -> None:
    from . import sprint as S
    rows = S.followups(conn, a.after)
    if not rows:
        print("nobody to chase right now.")
        return
    _rule("FOLLOW UP")
    for r in rows:
        print(f"  #{r['id']:<4}{(r['name'] or '')[:26]:<28}{r['stage']:<13}"
              f"{r['handle'] or '':<20}{r['followup_count']} sent")
    print()


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

    ing = sub.add_parser(
        "ingest",
        help="bulk-load metrics from a platform export (CSV/JSON, or - for stdin)",
    )
    ing.add_argument("path", help="export file, or '-' to read stdin")
    ing.add_argument("--platform", required=True,
                     help="which platform this export came from")
    ing.add_argument("--captured-at", dest="captured_at",
                     help="ISO timestamp for the snapshot (default: now)")
    ing.add_argument("--dry-run", action="store_true",
                     help="show what would happen without writing")
    ing.add_argument("--force", action="store_true",
                     help="import even if the numbers look like daily deltas")
    ing.add_argument("--map", action="append", metavar="COLUMN=field",
                     help="map an unrecognised column, e.g. --map 'Plays=views'")
    ing.set_defaults(fn=cmd_ingest)

    d = sub.add_parser("dash", help="write an HTML dashboard")
    d.add_argument("--days", type=int, default=30)
    d.add_argument("--out", default="out/dashboard.html")
    d.set_defaults(fn=cmd_dash)
    sp = sub.add_parser("sprint", help="start a revenue sprint and get the daily target")
    sp.add_argument("--goal", type=float, required=True, help="revenue target in USD")
    sp.add_argument("--price", type=float, default=200.0, help="price per spot")
    sp.add_argument("--days", type=int, default=7)
    sp.set_defaults(fn=cmd_sprint)

    ld = sub.add_parser("lead", help="manage sales prospects")
    ld.add_argument("action", choices=["add", "set", "list", "import"])
    ld.add_argument("name", nargs="?", help="name/handle/id, or CSV path for import")
    ld.add_argument("stage", nargs="?",
                    help="sourced|spec_made|contacted|replied|negotiating|won|lost|ghosted")
    ld.add_argument("--handle")
    ld.add_argument("--channel")
    ld.add_argument("--segment")
    ld.add_argument("--product")
    ld.add_argument("--source")
    ld.add_argument("--amount", type=float, help="closed value when stage=won")
    ld.add_argument("--notes")
    ld.add_argument("--stage", help="filter `list` by funnel stage")
    ld.set_defaults(fn=cmd_lead)

    pl = sub.add_parser("pipeline", help="sprint progress, conversion, and today's target")
    pl.set_defaults(fn=cmd_pipeline)

    fu = sub.add_parser("followups", help="who to chase today")
    fu.add_argument("--after", type=float, default=2.0, help="days of silence")
    fu.set_defaults(fn=cmd_followups)

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
