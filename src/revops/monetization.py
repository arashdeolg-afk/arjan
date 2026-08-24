"""Revenue streams, ordered by how fast they realistically pay.

The central bet of this system: for an AI-content studio, the fastest and
largest money comes from selling the CAPABILITY (client spots, digital
products) rather than the CONTENT (ad revenue). Platform ad programs on
short-form pay $0.01-$1.00 per 1,000 views — a million views is lunch
money. The same million views is a portfolio that closes a $1,000 client.

So the content is the proof and the funnel. The streams below are the
business. They are listed in the order a studio can actually unlock them.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Stream:
    key: str
    name: str
    # Gate: what must be true before this can earn. None = available today.
    gate: str
    # Realistic economics, stated plainly so expectations stay calibrated.
    economics: str
    # Order-of-magnitude monthly ceiling at the point of unlock.
    early_monthly_usd: str
    effort: str            # low | medium | high
    activation: list[str] = field(default_factory=list)
    # Machine-checkable unlock conditions.
    min_followers: int = 0
    min_views_30d: int = 0
    min_published: int = 0


STREAMS: list[Stream] = [
    Stream(
        key="affiliate",
        name="Affiliate links",
        gate="None. Works from your first post.",
        economics=(
            "3-10% of sale. Anime figures/merch ~3-4%, drawing tablets and "
            "software often higher. Needs ~1-3% of viewers to click and ~2-5% "
            "of those to buy, so revenue tracks CLICKS, not views."
        ),
        early_monthly_usd="$20 - $200",
        effort="low",
        min_published=1,
        activation=[
            "Sign up for Amazon Associates plus one anime-merch program.",
            "Put ONE destination in every bio — a link page, not a bare product URL.",
            "Log clicks in the ledger; if CTR is under ~0.5% the offer is wrong, not the traffic.",
        ],
    ),
    Stream(
        key="client_ugc",
        name="Client work / AI ad spots",
        gate="A portfolio, not a follower count. ~10 solid public pieces.",
        economics=(
            "$300-$2,000 per delivered spot. Same pipeline you already run, "
            "pointed at a brand's brief. Highest dollars-per-hour available "
            "to you and it does NOT require an audience — only proof."
        ),
        early_monthly_usd="$300 - $3,000",
        effort="medium",
        min_published=10,
        activation=[
            "Cut a 45-second reel of your best 6 clips. That reel is the entire sales asset.",
            "Pick one vertical that already buys animation (games, apps, streamers, Shopify brands).",
            "Send 10 personalised offers a day: a free 5-second custom spot for their product.",
            "Price the first three at $300 to build testimonials, then raise to $800+.",
        ],
    ),
    Stream(
        key="digital_product",
        name="Digital products",
        gate="~500 engaged followers, or any traffic from other creators.",
        economics=(
            "~95% margin, no inventory, no shipping. Your audience contains "
            "people who want to MAKE what you make — prompt packs, project "
            "files, character sheets, workflow guides. $9-$49 price points."
        ),
        early_monthly_usd="$100 - $1,500",
        effort="medium",
        min_followers=500,
        activation=[
            "Package the pipeline you already run: prompts + character sheets + settings.",
            "Sell as a digital product on the Shopify store (no inventory needed).",
            "Make one 'how I made this' post per week that ends at the product.",
        ],
    ),
    Stream(
        key="tiktok_rewards",
        name="TikTok Creator Rewards",
        gate="10,000 followers + 100,000 views in 30 days. Videos must exceed 1 minute.",
        economics=(
            "RPM roughly $0.40-$1.00 per 1,000 qualified views. Only videos "
            "over one minute qualify, which conflicts with short punchy comedy "
            "— treat it as a bonus on longer cuts, never as the plan."
        ),
        early_monthly_usd="$50 - $500",
        effort="low",
        min_followers=10_000,
        min_views_30d=100_000,
        activation=[
            "Produce a weekly 60-90s compilation from that week's shorts.",
            "Qualified views only count on the long cut — keep shorts short.",
        ],
    ),
    Stream(
        key="youtube_partner",
        name="YouTube Partner Program",
        gate="1,000 subscribers + 10M Shorts views in 90 days (or 4,000 long-form watch hours in 12 months).",
        economics=(
            "Shorts RPM is roughly $0.01-$0.15 per 1,000 views. Ten million "
            "Shorts views is on the order of a few hundred dollars. The real "
            "prize is the subscriber base it builds, not the cheque."
        ),
        early_monthly_usd="$30 - $300",
        effort="low",
        min_followers=1_000,
        activation=[
            "Chase the subscriber threshold, not the revenue — subs unlock everything else.",
            "Long-form is worth 10-30x the RPM of Shorts. One weekly long cut changes the math.",
        ],
    ),
    Stream(
        key="merch",
        name="Print-on-demand merch",
        gate="~10,000 engaged followers with a recognisable character or catchphrase.",
        economics=(
            "$8-$15 margin per unit through print-on-demand, zero inventory "
            "risk. Converts on IDENTITY, not on quality — people buy a "
            "character they love, so this fails without a recurring cast."
        ),
        early_monthly_usd="$50 - $800",
        effort="medium",
        min_followers=10_000,
        activation=[
            "Only launch once one character or line recurs across many videos.",
            "Connect print-on-demand to the Shopify store so nothing ships from your hands.",
            "Three designs, not thirty. Let demand pick the fourth.",
        ],
    ),
    Stream(
        key="sponsorship",
        name="Brand sponsorships",
        gate="~10,000 engaged followers in a defined niche.",
        economics=(
            "$100-$500 per integration at 10-50k followers; scales roughly "
            "with engaged reach. Best dollars-per-hour after client work, "
            "because the brand supplies the brief."
        ),
        early_monthly_usd="$200 - $2,000",
        effort="low",
        min_followers=10_000,
        activation=[
            "Keep a one-page media kit: reach, engagement rate, audience, past work.",
            "Inbound is slow — pitch brands already advertising to your niche.",
        ],
    ),
]

STREAM_KEYS = {s.key for s in STREAMS}


def estimated_followers(conn: sqlite3.Connection) -> dict[str, int]:
    """Followers gained per platform, summed from logged snapshots.

    This is a lower bound built from what you recorded, not a live API
    reading — it undercounts if you started logging late.
    """
    sql = """
    SELECT p.platform, COALESCE(SUM(m.followers_gained), 0) AS f
    FROM posts p LEFT JOIN metrics m ON m.post_id = p.id
    GROUP BY p.platform
    """
    return {r["platform"]: int(r["f"]) for r in conn.execute(sql)}


def views_last_30d(conn: sqlite3.Connection) -> int:
    from .analytics import content_rows
    return sum(r["views"] for r in content_rows(conn, days=30))


def readiness(conn: sqlite3.Connection) -> list[dict]:
    """Which streams are unlocked, and what's blocking the rest."""
    followers = estimated_followers(conn)
    peak = max(followers.values(), default=0)
    published = conn.execute(
        "SELECT COUNT(DISTINCT content_id) AS n FROM posts"
    ).fetchone()["n"]
    views30 = views_last_30d(conn)

    earned = {
        r["stream"]: r["amt"]
        for r in conn.execute(
            "SELECT stream, SUM(amount_usd) AS amt FROM revenue GROUP BY stream"
        )
    }

    out = []
    for s in STREAMS:
        blockers = []
        if published < s.min_published:
            blockers.append(f"{s.min_published - published} more published pieces")
        if peak < s.min_followers:
            blockers.append(f"{s.min_followers - peak:,} more followers on your best platform")
        if views30 < s.min_views_30d:
            blockers.append(f"{s.min_views_30d - views30:,} more views in 30d")
        out.append({
            "key": s.key,
            "name": s.name,
            "ready": not blockers,
            "blockers": blockers,
            "gate": s.gate,
            "economics": s.economics,
            "early_monthly_usd": s.early_monthly_usd,
            "effort": s.effort,
            "activation": s.activation,
            "earned_to_date": earned.get(s.key, 0.0),
            "active": s.key in earned,
        })
    # Unlocked-but-unused first: those are the money left on the table.
    out.sort(key=lambda r: (r["active"], not r["ready"]))
    return out
