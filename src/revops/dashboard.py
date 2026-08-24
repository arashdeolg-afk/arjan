"""Self-contained HTML dashboard. No CDN, no build step, works offline."""

from __future__ import annotations

import html
import sqlite3
from pathlib import Path

from . import analytics as A
from . import monetization as M

CSS = """
:root{--bg:#faf9f7;--fg:#1c1a17;--muted:#6b6660;--card:#fff;--line:#e5e1dc;
--pos:#1a7f4b;--neg:#b3261e;--warn:#b26a00;--accent:#3b5bdb}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){
--bg:#16150f;--fg:#eceae4;--muted:#9d968c;--card:#211f19;--line:#332f27;
--pos:#4ade80;--neg:#f87171;--warn:#fbbf24;--accent:#8ea6ff}}
:root[data-theme=dark]{--bg:#16150f;--fg:#eceae4;--muted:#9d968c;--card:#211f19;
--line:#332f27;--pos:#4ade80;--neg:#f87171;--warn:#fbbf24;--accent:#8ea6ff}
*{box-sizing:border-box}
body{margin:0;padding:2rem 1.25rem 4rem;background:var(--bg);color:var(--fg);
font:15px/1.55 ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif}
.wrap{max-width:1080px;margin:0 auto}
h1{font-size:1.6rem;margin:0 0 .25rem}
.sub{color:var(--muted);margin:0 0 2rem;font-size:.9rem}
h2{font-size:.78rem;text-transform:uppercase;letter-spacing:.09em;
color:var(--muted);margin:2.5rem 0 .85rem;font-weight:600}
.grid{display:grid;gap:.85rem;grid-template-columns:repeat(auto-fit,minmax(170px,1fr))}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:1rem}
.k{font-size:.72rem;color:var(--muted);text-transform:uppercase;letter-spacing:.06em}
.v{font-size:1.65rem;font-weight:650;margin-top:.3rem;font-variant-numeric:tabular-nums}
.pos{color:var(--pos)}.neg{color:var(--neg)}
.scroll{overflow-x:auto;-webkit-overflow-scrolling:touch}
table{border-collapse:collapse;width:100%;font-size:.88rem;min-width:520px}
th{text-align:left;font-size:.7rem;text-transform:uppercase;letter-spacing:.06em;
color:var(--muted);padding:.5rem .7rem;border-bottom:1px solid var(--line);font-weight:600}
td{padding:.5rem .7rem;border-bottom:1px solid var(--line);font-variant-numeric:tabular-nums}
tr:last-child td{border-bottom:none}
.num{text-align:right}
.bar{height:5px;border-radius:3px;background:var(--accent);min-width:2px}
.pill{display:inline-block;font-size:.68rem;padding:.14rem .5rem;border-radius:999px;
border:1px solid var(--line);color:var(--muted)}
.on{color:var(--pos);border-color:var(--pos)}
.rdy{color:var(--warn);border-color:var(--warn)}
li{margin:.4rem 0}
.lowsig{color:var(--muted);font-size:.72rem}
"""


def _e(x) -> str:
    return html.escape(str(x))


def _money(x: float) -> str:
    return f"${x:,.2f}"


def render(conn: sqlite3.Connection, days: int = 30, path: str = "out/dashboard.html") -> Path:
    p = A.pnl(conn, days)
    plats = A.platform_efficiency(conn, days)
    streams = M.readiness(conn)
    recs = A.recommendations(conn, days)
    tb = A.top_and_bottom(conn, days, k=5)

    def kpi(label: str, value: str, cls: str = "") -> str:
        return (f'<div class="card"><div class="k">{_e(label)}</div>'
                f'<div class="v {cls}">{_e(value)}</div></div>')

    profit_cls = "pos" if p["profit"] >= 0 else "neg"
    kpis = "".join([
        kpi("Revenue", _money(p["revenue"])),
        kpi("Cost", _money(p["cost"])),
        kpi("Profit", _money(p["profit"]), profit_cls),
        kpi("Effective hourly", f"{_money(p['effective_hourly'])}/hr",
            "pos" if p["effective_hourly"] >= 0 else "neg"),
        kpi("Pieces made", f"{p['content_made']}"),
        kpi("Cost / piece", _money(p["cost_per_content"])),
    ])

    # Revenue mix
    total_rev = p["revenue"] or 1
    mix = "".join(
        f'<tr><td>{_e(k)}</td><td class="num">{_money(v)}</td>'
        f'<td class="num">{v / total_rev * 100:.0f}%</td>'
        f'<td style="width:38%"><div class="bar" style="width:{v / total_rev * 100:.1f}%"></div></td></tr>'
        for k, v in p["revenue_by_stream"].items()
    ) or '<tr><td colspan="4">No revenue recorded yet.</td></tr>'

    plat_rows = "".join(
        f'<tr><td>{_e(r["platform"])}</td><td class="num">{r["posts"]}</td>'
        f'<td class="num">{r["views"]:,}</td><td class="num">{r["views_per_post"]:,.0f}</td>'
        f'<td class="num">{r["engagement_rate"] * 100:.1f}%</td>'
        f'<td class="num">{r["ctr"] * 100:.2f}%</td>'
        f'<td class="num">{_money(r["revenue"])}</td></tr>'
        for r in plats
    ) or '<tr><td colspan="7">Nothing published in this window.</td></tr>'

    def dim_table(dim: str) -> str:
        rows = [r for r in A.by_dimension(conn, dim, days) if r[dim] != "(unset)"]
        if not rows:
            return ""
        body = "".join(
            f'<tr><td>{_e(r[dim])}'
            + ("" if r["confident"] else ' <span class="lowsig">low n</span>')
            + f'</td><td class="num">{r["n"]}</td>'
              f'<td class="num">{r["median_views"]:,.0f}</td>'
              f'<td class="num">{r["best_views"]:,}</td>'
              f'<td class="num">{_money(r["revenue"])}</td></tr>'
            for r in rows
        )
        return (f'<h2>By {_e(dim.replace("_", " "))}</h2><div class="scroll"><table>'
                f'<tr><th>{_e(dim)}</th><th class="num">n</th><th class="num">median views</th>'
                f'<th class="num">best</th><th class="num">revenue</th></tr>{body}</table></div>')

    stream_items = ""
    for s in streams:
        if s["active"]:
            pill = f'<span class="pill on">active · {_money(s["earned_to_date"])}</span>'
            detail = ""
        elif s["ready"]:
            pill = '<span class="pill rdy">ready — earning nothing</span>'
            detail = f'<div class="lowsig">Next: {_e(s["activation"][0])}</div>'
        else:
            pill = '<span class="pill">locked</span>'
            detail = f'<div class="lowsig">Needs: {_e(", ".join(s["blockers"]))}</div>'
        stream_items += (
            f'<div class="card"><div><strong>{_e(s["name"])}</strong> {pill}</div>'
            f'<div class="lowsig" style="margin-top:.35rem">{_e(s["early_monthly_usd"])}/mo '
            f'· {_e(s["effort"])} effort</div>{detail}</div>'
        )

    top_rows = "".join(
        f'<tr><td>{_e(r["title"])[:52]}</td><td>{_e(r["topic"] or "-")}</td>'
        f'<td>{_e(r["hook_type"] or "-")}</td><td class="num">{r["views"]:,}</td>'
        f'<td class="num">{_money(r["revenue"])}</td></tr>'
        for r in tb["top"]
    ) or '<tr><td colspan="5">Nothing published yet.</td></tr>'

    rec_html = ("<ul>" + "".join(f"<li>{_e(r)}</li>" for r in recs) + "</ul>") if recs else \
        "<p class='lowsig'>Not enough data for recommendations yet.</p>"

    doc = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Studio Revenue Dashboard</title><style>{CSS}</style></head><body><div class="wrap">
<h1>Studio Revenue Dashboard</h1>
<p class="sub">Last {days} days · generated locally from your ledger</p>
<div class="grid">{kpis}</div>
<h2>Revenue mix</h2><div class="scroll"><table>
<tr><th>stream</th><th class="num">amount</th><th class="num">share</th><th></th></tr>{mix}</table></div>
<h2>Platforms</h2><div class="scroll"><table>
<tr><th>platform</th><th class="num">posts</th><th class="num">views</th>
<th class="num">views/post</th><th class="num">eng</th><th class="num">ctr</th>
<th class="num">revenue</th></tr>{plat_rows}</table></div>
{dim_table("topic")}{dim_table("hook_type")}
<h2>Best performers</h2><div class="scroll"><table>
<tr><th>title</th><th>topic</th><th>hook</th><th class="num">views</th>
<th class="num">revenue</th></tr>{top_rows}</table></div>
<h2>Revenue streams</h2><div class="grid">{stream_items}</div>
<h2>What to do next</h2>{rec_html}
</div></body></html>"""

    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(doc, encoding="utf-8")
    return out
