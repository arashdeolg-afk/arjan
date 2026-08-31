"""The 7-day revenue sprint: a direct-outreach sales pipeline.

Why this and not content: content revenue is a lottery ticket whose payout
depends on an algorithm you don't control. Outreach revenue is a function
of volume you DO control. If 15 contacts produce 1 sale, then 45 contacts
produce ~3, and you can decide today whether to make that happen.

This module turns "send some DMs" into a measurable funnel with a required
daily rate, so at any moment you know whether you are on track or behind.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

from .ledger import now

# The funnel, in order. A lead's stage never regresses, so counts stay
# honest even after the lead dies — a lost deal still proves a reply happened.
STAGES = ["sourced", "spec_made", "contacted", "replied", "negotiating", "won"]
STAGE_RANK = {s: i for i, s in enumerate(STAGES)}
OUTCOMES = {"won", "lost", "ghosted"}

# Baseline conversion rates for spec-work outreach — a free custom asset
# made before they reply. These are starting assumptions, progressively
# replaced by your own numbers as real data accumulates.
PRIORS = {
    ("sourced", "spec_made"): 0.85,
    ("spec_made", "contacted"): 0.95,
    ("contacted", "replied"): 0.25,
    ("replied", "negotiating"): 0.55,
    ("negotiating", "won"): 0.50,
}

# Weight of the prior in pseudo-counts. At 8, roughly 8 real observations
# are needed before your data outweighs the assumption. Prevents a 1-for-1
# start from reading as a 100% close rate.
PRIOR_WEIGHT = 8


# ------------------------------------------------------------------ writes


def start_sprint(conn: sqlite3.Connection, goal_usd: float, price_usd: float,
                 days: int = 7) -> None:
    conn.execute(
        "INSERT INTO sprint (id, goal_usd, price_usd, started_at, days) "
        "VALUES (1,?,?,?,?) ON CONFLICT(id) DO UPDATE SET "
        "goal_usd=excluded.goal_usd, price_usd=excluded.price_usd, "
        "started_at=excluded.started_at, days=excluded.days",
        (goal_usd, price_usd, now(), days),
    )
    conn.commit()


def get_sprint(conn: sqlite3.Connection) -> dict | None:
    row = conn.execute("SELECT * FROM sprint WHERE id = 1").fetchone()
    return dict(row) if row else None


def add_lead(conn: sqlite3.Connection, name: str, *, handle: str | None = None,
             channel: str | None = None, segment: str | None = None,
             product: str | None = None, source: str | None = None,
             notes: str | None = None) -> int:
    cur = conn.execute(
        """INSERT INTO leads (name, handle, channel, segment, product, source,
                              stage, created_at, notes)
           VALUES (?,?,?,?,?,?,'sourced',?,?)""",
        (name, handle, channel, segment, product, source, now(), notes),
    )
    conn.commit()
    return int(cur.lastrowid)


def resolve_lead(conn: sqlite3.Connection, ref: str | int) -> int:
    row = conn.execute(
        "SELECT id FROM leads WHERE id = ? OR name = ? OR handle = ?",
        (ref, str(ref), str(ref)),
    ).fetchone()
    if not row:
        raise LookupError(f"no lead matching {ref!r}")
    return int(row["id"])


def set_stage(conn: sqlite3.Connection, ref: str | int, stage: str, *,
              amount: float | None = None, notes: str | None = None) -> dict:
    """Advance a lead. Stage only moves forward; outcomes are terminal."""
    lid = resolve_lead(conn, ref)
    row = conn.execute("SELECT * FROM leads WHERE id = ?", (lid,)).fetchone()

    if stage in ("lost", "ghosted"):
        conn.execute("UPDATE leads SET outcome = ?, last_touch_at = ? WHERE id = ?",
                     (stage, now(), lid))
    elif stage in STAGE_RANK:
        # max() keeps the funnel honest — a re-logged earlier step can't
        # erase the fact that this lead already replied.
        best = max(STAGE_RANK[row["stage"]], STAGE_RANK[stage])
        outcome = "won" if stage == "won" else row["outcome"]
        conn.execute(
            "UPDATE leads SET stage = ?, outcome = ?, last_touch_at = ?, "
            "closed_usd = COALESCE(?, closed_usd) WHERE id = ?",
            (STAGES[best], outcome, now(), amount, lid),
        )
        kind = {"spec_made": "spec", "contacted": "outreach"}.get(stage, "followup")
        conn.execute(
            "INSERT INTO touches (lead_id, occurred_at, kind, notes) VALUES (?,?,?,?)",
            (lid, now(), kind, notes),
        )
    else:
        raise ValueError(f"stage must be one of {STAGES + ['lost', 'ghosted']}")

    conn.commit()
    if stage == "won" and amount:
        from .ledger import add_revenue
        add_revenue(conn, "client_ugc", amount,
                    notes=f"client: {row['name']}")
    return dict(conn.execute("SELECT * FROM leads WHERE id = ?", (lid,)).fetchone())


def log_touch(conn: sqlite3.Connection, ref: str | int, kind: str = "followup",
              notes: str | None = None) -> None:
    lid = resolve_lead(conn, ref)
    conn.execute(
        "INSERT INTO touches (lead_id, occurred_at, kind, notes) VALUES (?,?,?,?)",
        (lid, now(), kind, notes),
    )
    conn.execute("UPDATE leads SET last_touch_at = ? WHERE id = ?", (now(), lid))
    conn.commit()


# ------------------------------------------------------------------- reads


def funnel(conn: sqlite3.Connection) -> list[dict]:
    """How many leads ever reached each stage."""
    rows = [dict(r) for r in conn.execute("SELECT stage, outcome FROM leads")]
    out = []
    for i, s in enumerate(STAGES):
        n = sum(1 for r in rows if STAGE_RANK[r["stage"]] >= i)
        out.append({"stage": s, "count": n})
    return out


def rates(conn: sqlite3.Connection) -> dict[tuple[str, str], dict]:
    """Blended conversion rates: your data where it exists, priors where not."""
    counts = {f["stage"]: f["count"] for f in funnel(conn)}
    out = {}
    for (a, b), prior in PRIORS.items():
        trials, wins = counts[a], counts[b]
        blended = (wins + PRIOR_WEIGHT * prior) / (trials + PRIOR_WEIGHT)
        out[(a, b)] = {
            "prior": prior,
            "observed": (wins / trials) if trials else None,
            "rate": blended,
            "n": trials,
            "trusted": trials >= PRIOR_WEIGHT,
        }
    return out


def contacts_per_win(conn: sqlite3.Connection) -> float:
    r = rates(conn)
    p = (r[("contacted", "replied")]["rate"]
         * r[("replied", "negotiating")]["rate"]
         * r[("negotiating", "won")]["rate"])
    return (1 / p) if p > 0 else float("inf")


def status(conn: sqlite3.Connection) -> dict:
    """Are you on track, and what has to happen today."""
    sp = get_sprint(conn)
    counts = {f["stage"]: f["count"] for f in funnel(conn)}
    earned = conn.execute(
        "SELECT COALESCE(SUM(closed_usd), 0) AS s FROM leads WHERE outcome = 'won'"
    ).fetchone()["s"]

    if not sp:
        return {"started": False, "earned": earned, "funnel": counts}

    start = datetime.fromisoformat(sp["started_at"])
    elapsed = (datetime.now(timezone.utc) - start).total_seconds() / 86400
    days_left = max(0.0, sp["days"] - elapsed)

    remaining = max(0.0, sp["goal_usd"] - earned)
    wins_needed = remaining / sp["price_usd"] if sp["price_usd"] else 0
    cpw = contacts_per_win(conn)
    contacts_needed = wins_needed * cpw

    # Leads already in flight partially cover the need.
    in_flight = counts["contacted"] - counts["won"]
    still_to_contact = max(0.0, contacts_needed - in_flight * 0.5)

    per_day = still_to_contact / days_left if days_left > 0.5 else still_to_contact

    return {
        "started": True,
        "goal": sp["goal_usd"],
        "price": sp["price_usd"],
        "earned": earned,
        "remaining": remaining,
        "days_left": days_left,
        "elapsed_days": elapsed,
        "wins_needed": wins_needed,
        "contacts_per_win": cpw,
        "contacts_needed": contacts_needed,
        "contacted_so_far": counts["contacted"],
        "still_to_contact": still_to_contact,
        "per_day": per_day,
        "on_track": counts["contacted"] >= contacts_needed * (elapsed / sp["days"])
                    if sp["days"] else False,
        "funnel": counts,
    }


def followups(conn: sqlite3.Connection, after_days: float = 2.0) -> list[dict]:
    """Who to chase. Most deals die from silence, not rejection."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=after_days)).isoformat()
    sql = """
    SELECT l.*, COUNT(t.id) AS touches,
           (SELECT COUNT(*) FROM touches t2
            WHERE t2.lead_id = l.id AND t2.kind = 'followup') AS followup_count
    FROM leads l LEFT JOIN touches t ON t.lead_id = l.id
    WHERE l.outcome IS NULL
      AND l.stage IN ('contacted', 'replied', 'negotiating')
      AND COALESCE(l.last_touch_at, l.created_at) < ?
    GROUP BY l.id
    HAVING followup_count < 3
    ORDER BY l.stage DESC, l.last_touch_at ASC
    """
    return [dict(r) for r in conn.execute(sql, (cutoff,))]


def by_segment(conn: sqlite3.Connection) -> list[dict]:
    """Which kind of prospect actually converts — where to aim next week."""
    rows = [dict(r) for r in conn.execute("SELECT * FROM leads")]
    buckets: dict[str, list[dict]] = {}
    for r in rows:
        buckets.setdefault(r["segment"] or "(unset)", []).append(r)
    out = []
    for seg, rs in buckets.items():
        contacted = [r for r in rs if STAGE_RANK[r["stage"]] >= STAGE_RANK["contacted"]]
        replied = [r for r in rs if STAGE_RANK[r["stage"]] >= STAGE_RANK["replied"]]
        won = [r for r in rs if r["outcome"] == "won"]
        out.append({
            "segment": seg,
            "leads": len(rs),
            "contacted": len(contacted),
            "replied": len(replied),
            "won": len(won),
            "revenue": sum(r["closed_usd"] or 0 for r in won),
            "reply_rate": (len(replied) / len(contacted)) if contacted else None,
        })
    out.sort(key=lambda r: (r["revenue"], r["replied"]), reverse=True)
    return out
