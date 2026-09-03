"""Bulk metric ingest: platform exports -> the metrics table.

`revops track` records one snapshot by hand. That is fine for three posts
and hopeless for three hundred, which is why `analytics.MIN_SAMPLE` keeps
tripping in practice: the data never gets entered. This module reads
whatever CSV or JSON a platform hands you and turns it into snapshots.

Three rules shape everything here.

1.  **Rows are lifetime totals, not daily deltas.** `analytics.LATEST_METRICS`
    takes the most recent snapshot per post rather than summing them, so a
    daily-breakdown export would understate every video by orders of
    magnitude and quietly re-rank every topic. Ingest watches for the
    signature of that mistake — new numbers *below* the previous snapshot —
    and refuses the file when it shows up across the board.

2.  **Unmatched rows are reported, never dropped.** An export names videos
    the way the platform does; this database names them by slug. When those
    disagree the row surfaces in the report along with the command that
    would fix it. Importing 40 of 50 rows and saying nothing produces a
    confident, wrong ranking, which is worse than importing none.

3.  **Aliases, not per-vendor parsers.** Platforms rename their columns far
    more often than they change what the columns mean. One header table
    beats six brittle vendor adapters, and `--map` covers whatever it
    misses.

Parsing (`parse_*`) is kept free of IO and of the database so the header
table stays unit-testable without fixture files or a live export.
"""

from __future__ import annotations

import csv
import io
import json
import sqlite3
import sys
from pathlib import Path

from .ledger import add_metrics_for_post, now, resolve_content, slugify

# Snapshot fields this database stores. Everything else in an export is noise.
METRIC_FIELDS = (
    "views", "likes", "comments", "shares",
    "followers_gained", "watch_time_s", "clicks",
)

# Fields used to work out which post a row is talking about.
IDENTITY_FIELDS = ("slug", "external_id", "url", "title")

# Canonical field -> header spellings, lowercased and stripped.
# Deliberately conservative: 'impressions' and 'reach' are NOT views, and
# treating them as such would inflate every ranking in analytics.py.
ALIASES: dict[str, set[str]] = {
    "views": {
        "views", "view count", "views total", "total views", "video views",
        "plays", "play count", "post views", "impressions (video views)",
    },
    "likes": {
        "likes", "like count", "total likes", "reactions", "favorites",
        "hearts", "upvotes",
    },
    "comments": {
        "comments", "comment count", "total comments", "replies",
    },
    "shares": {
        "shares", "share count", "total shares", "reposts", "retweets",
        "sends",
    },
    "followers_gained": {
        "followers gained", "new followers", "net followers", "follows",
        "subscribers gained", "subscribers", "net subscribers",
    },
    "watch_time_s": {
        "watch time (seconds)", "watch time seconds", "seconds viewed",
        "total time watched (s)", "watch time",
    },
    "clicks": {
        "clicks", "link clicks", "website clicks", "bio link clicks",
        "outbound clicks", "url clicks",
    },
    "slug": {
        "slug", "content slug", "revops slug",
    },
    "external_id": {
        "content", "video id", "post id", "media id", "item id",
        "external id", "id", "tweet id",
    },
    "url": {
        "url", "link", "permalink", "post url", "video url", "share url",
        "post link",
    },
    "title": {
        "title", "video title", "post title", "name", "caption",
    },
}

# Same meaning, different unit. Value is (canonical field, multiplier).
# Watch time is the usual offender: YouTube exports hours, TikTok minutes.
SCALED: dict[str, tuple[str, float]] = {
    "watch time (hours)": ("watch_time_s", 3600.0),
    "watch time hours": ("watch_time_s", 3600.0),
    "hours watched": ("watch_time_s", 3600.0),
    "total watch time (hours)": ("watch_time_s", 3600.0),
    "watch time (minutes)": ("watch_time_s", 60.0),
    "watch time minutes": ("watch_time_s", 60.0),
    "minutes viewed": ("watch_time_s", 60.0),
    "total time watched": ("watch_time_s", 60.0),
}

_HEADER_TO_FIELD = {
    spelling: (field, 1.0)
    for field, spellings in ALIASES.items()
    for spelling in spellings
}
_HEADER_TO_FIELD.update(SCALED)

# Fraction of comparable rows that may go backwards before the whole file is
# treated as a daily export rather than lifetime totals. One video genuinely
# losing views (a deletion, a correction) is normal; half of them is a
# different kind of file.
REGRESSION_ABORT_RATIO = 0.5

# Below this many comparable rows there is no pattern to detect, so the
# guard stays quiet rather than rejecting a small legitimate import.
REGRESSION_MIN_ROWS = 3

_MAGNITUDE = {"k": 1_000.0, "m": 1_000_000.0, "b": 1_000_000_000.0}
_BLANK = {"", "-", "--", "---", "—", "–", "n/a", "na", "null", "none", "––"}


class IngestError(ValueError):
    """Raised when a file cannot be read as metrics at all."""


# ------------------------------------------------------------------ parsing


def normalize_header(header: str) -> tuple[str, float] | None:
    """Map one export column heading onto a canonical field and multiplier.

    Returns None for columns this system has no use for, which is most of
    them — exports carry twenty columns and we want seven.
    """
    key = " ".join(str(header or "").strip().lower().split())
    if not key:
        return None
    if key in _HEADER_TO_FIELD:
        return _HEADER_TO_FIELD[key]
    # Exports love trailing units and footnote markers: "Views (total)".
    stripped = key.split("(")[0].strip()
    return _HEADER_TO_FIELD.get(stripped)


def parse_number(raw: object) -> float | None:
    """Read a number the way a human wrote it, or None if it isn't one.

    Export cells are formatted for reading, not parsing: '1,234', '1.2K',
    '0:03:20', and an em dash for missing all show up in the same column.
    """
    if raw is None:
        return None
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        return float(raw)
    s = str(raw).strip()
    if s.lower() in _BLANK:
        return None
    s = s.replace(",", "").replace("%", "").replace("$", "").strip()
    if not s or s.lower() in _BLANK:
        return None

    # Durations: h:mm:ss or mm:ss, seen in watch-time columns.
    if ":" in s:
        parts = s.split(":")
        try:
            nums = [float(p) for p in parts]
        except ValueError:
            return None
        total = 0.0
        for n in nums:
            total = total * 60 + n
        return total

    multiplier = 1.0
    if s[-1].lower() in _MAGNITUDE:
        multiplier = _MAGNITUDE[s[-1].lower()]
        s = s[:-1].strip()
    try:
        return float(s) * multiplier
    except ValueError:
        return None


def _canonical_row(raw: dict, overrides: dict[str, str] | None = None) -> dict:
    """Reduce one export record to canonical fields, dropping the rest."""
    overrides = {k.strip().lower(): v for k, v in (overrides or {}).items()}
    out: dict = {}
    for header, value in raw.items():
        if header is None:
            continue
        key = " ".join(str(header).strip().lower().split())
        if key in overrides:
            mapping: tuple[str, float] | None = (overrides[key], 1.0)
        else:
            mapping = normalize_header(header)
        if not mapping:
            continue
        field, scale = mapping
        if field in IDENTITY_FIELDS:
            text = str(value or "").strip()
            # Don't let a blank cell overwrite an identity we already read.
            if text and not out.get(field):
                out[field] = text
        elif field not in out:
            # First column wins rather than summing: exports sometimes carry
            # two spellings of the same measure ("Views" and "Video views"),
            # and adding them would silently double every count.
            n = parse_number(value)
            if n is not None:
                out[field] = n * scale
    return out


def _score_header(cells: list[str], overrides: dict[str, str] | None = None) -> int:
    """How much a row looks like the header row of a metrics export.

    Overrides count towards the score: --map exists precisely for files
    whose columns this table does not recognise, so ignoring it here would
    reject the file before the mapping ever got a chance to apply.
    """
    lookup = {k.strip().lower(): v for k, v in (overrides or {}).items()}
    fields = set()
    for cell in cells:
        key = " ".join(str(cell or "").strip().lower().split())
        if key in lookup:
            fields.add(lookup[key])
            continue
        mapped = normalize_header(cell)
        if mapped:
            fields.add(mapped[0])
    has_metric = any(f in METRIC_FIELDS for f in fields)
    has_identity = any(f in IDENTITY_FIELDS for f in fields)
    if not (has_metric and has_identity):
        return 0
    return len(fields)


def parse_csv(text: str, overrides: dict[str, str] | None = None) -> list[dict]:
    """Parse CSV/TSV export text into canonical rows.

    Platform exports bury the real header under title lines and blank rows,
    so the header is found by scoring rather than assumed to be line one.
    """
    text = text.lstrip("﻿")
    if not text.strip():
        return []
    sample = text[:8192]
    delimiter = ","
    try:
        delimiter = csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
    except csv.Error:
        for candidate in ("\t", ";", "|"):
            if sample.count(candidate) > sample.count(","):
                delimiter = candidate
                break

    grid = list(csv.reader(io.StringIO(text), delimiter=delimiter))
    header_at, best = None, 0
    for i, row in enumerate(grid[:15]):
        score = _score_header(row, overrides)
        if score > best:
            header_at, best = i, score
    if header_at is None:
        raise IngestError(
            "no recognisable columns — expected something like "
            "'title'/'url' plus 'views'. Use --map to name them explicitly."
        )

    header = grid[header_at]
    rows = []
    for cells in grid[header_at + 1:]:
        if not any(str(c).strip() for c in cells):
            continue
        record = dict(zip(header, cells))
        row = _canonical_row(record, overrides)
        if row:
            rows.append(row)
    return rows


def parse_json(text: str, overrides: dict[str, str] | None = None) -> list[dict]:
    """Parse a JSON export — a bare list, or a list under a wrapper key."""
    try:
        blob = json.loads(text)
    except json.JSONDecodeError as exc:
        raise IngestError(f"not valid JSON: {exc}") from exc

    records = None
    if isinstance(blob, list):
        records = blob
    elif isinstance(blob, dict):
        for key in ("data", "results", "posts", "items", "analytics", "rows"):
            if isinstance(blob.get(key), list):
                records = blob[key]
                break
        if records is None and any(normalize_header(k) for k in blob):
            records = [blob]
    if records is None:
        raise IngestError("JSON has no list of records to import")

    rows = []
    for record in records:
        if not isinstance(record, dict):
            continue
        flat = {k: v for k, v in record.items() if not isinstance(v, (dict, list))}
        row = _canonical_row(flat, overrides)
        if row:
            rows.append(row)
    return rows


def parse_text(text: str, overrides: dict[str, str] | None = None) -> list[dict]:
    """Parse an export without being told which format it is."""
    head = text.lstrip("﻿").lstrip()
    if head.startswith(("{", "[")):
        return parse_json(text, overrides)
    return parse_csv(text, overrides)


def load(path: str) -> str:
    """Read an export off disk, or stdin when path is '-'."""
    if path == "-":
        return sys.stdin.read()
    p = Path(path)
    if not p.exists():
        raise IngestError(f"no such file: {path}")
    return p.read_text(encoding="utf-8-sig")


# ----------------------------------------------------------------- matching


def _norm_url(url: str | None) -> str | None:
    s = (url or "").strip().rstrip("/").lower()
    return s or None


def match_post(conn: sqlite3.Connection, row: dict, platform: str) -> tuple[int | None, str]:
    """Find the post an export row describes.

    Returns (post_id, how) on a hit and (None, why) on a miss. Tries the
    unambiguous identifiers first so a title collision can never override an
    explicit id.
    """
    platform = platform.lower()

    slug = row.get("slug")
    if slug:
        try:
            cid = resolve_content(conn, slug)
        except LookupError:
            return None, f"slug {slug!r} is not in the content table"
        hit = conn.execute(
            "SELECT id FROM posts WHERE content_id = ? AND platform = ?", (cid, platform)
        ).fetchone()
        if hit:
            return int(hit["id"]), "slug"
        return None, f"content {slug!r} exists but was never posted to {platform}"

    ext = row.get("external_id")
    if ext:
        hit = conn.execute(
            "SELECT id FROM posts WHERE platform = ? AND external_id = ?", (platform, ext)
        ).fetchone()
        if hit:
            return int(hit["id"]), "external_id"

    url = _norm_url(row.get("url"))
    if url:
        for post in conn.execute(
            "SELECT id, url FROM posts WHERE platform = ? AND url IS NOT NULL", (platform,)
        ):
            if _norm_url(post["url"]) == url:
                return int(post["id"]), "url"

    title = row.get("title")
    if title:
        hit = conn.execute(
            "SELECT p.id FROM posts p JOIN content c ON c.id = p.content_id "
            "WHERE p.platform = ? AND c.slug = ?",
            (platform, slugify(title)),
        ).fetchone()
        if hit:
            return int(hit["id"]), "title"

    if not (ext or url or title):
        return None, "row carries no id, url or title to match on"
    tried = []
    if ext:
        tried.append(f"id {ext!r}")
    if url:
        tried.append(f"url {url}")
    if title:
        tried.append(f"slug {slugify(title)!r}")
    return None, f"no {platform} post with " + ", or ".join(tried)


def _latest_views(conn: sqlite3.Connection, post_id: int) -> int | None:
    row = conn.execute(
        "SELECT views FROM metrics WHERE post_id = ? "
        "ORDER BY captured_at DESC, id DESC LIMIT 1",
        (post_id,),
    ).fetchone()
    return int(row["views"]) if row else None


def _is_duplicate(conn: sqlite3.Connection, post_id: int, captured_at: str, views: int) -> bool:
    """Re-running the same export must not stack identical snapshots."""
    return conn.execute(
        "SELECT 1 FROM metrics WHERE post_id = ? AND captured_at = ? AND views = ?",
        (post_id, captured_at, views),
    ).fetchone() is not None


# ------------------------------------------------------------------ ingest


def _int(row: dict, field: str) -> int:
    return int(round(row.get(field, 0.0)))


def plan(
    conn: sqlite3.Connection,
    rows: list[dict],
    platform: str,
    *,
    captured_at: str | None = None,
) -> dict:
    """Work out what an import would do, touching nothing.

    Split out from `ingest` so --dry-run and the real run cannot drift
    apart, and so the daily-export guard can see the whole file before a
    single row is written.
    """
    stamp = captured_at or now()
    matched: list[dict] = []
    unmatched: list[dict] = []
    duplicates: list[dict] = []
    regressions: list[dict] = []

    for row in rows:
        if not any(f in row for f in METRIC_FIELDS):
            continue
        post_id, how = match_post(conn, row, platform)
        label = row.get("title") or row.get("url") or row.get("external_id") \
            or row.get("slug") or "(unnamed row)"
        if post_id is None:
            unmatched.append({"label": label, "reason": how, "row": row})
            continue

        views = _int(row, "views")
        previous = _latest_views(conn, post_id)
        if previous is not None and views < previous:
            regressions.append({"label": label, "post_id": post_id,
                                "was": previous, "now": views})
        entry = {"post_id": post_id, "how": how, "label": label,
                 "row": row, "views": views}
        if _is_duplicate(conn, post_id, stamp, views):
            duplicates.append(entry)
        else:
            matched.append(entry)

    comparable = len(matched) + len(duplicates)
    aborted = (
        comparable >= REGRESSION_MIN_ROWS
        and len(regressions) > comparable * REGRESSION_ABORT_RATIO
    )
    return {
        "platform": platform.lower(),
        "captured_at": stamp,
        "rows_read": len(rows),
        "write": matched,
        "duplicates": duplicates,
        "unmatched": unmatched,
        "regressions": regressions,
        "aborted": aborted,
        "abort_reason": (
            f"{len(regressions)} of {comparable} matched rows report fewer views than "
            "the snapshot already stored. That is what a daily-breakdown export looks "
            "like, and importing it would corrupt every ranking, because analytics "
            "reads the latest snapshot as a lifetime total. Export lifetime totals "
            "instead, or pass --force if the drop is real."
        ) if aborted else None,
    }


def ingest(
    conn: sqlite3.Connection,
    rows: list[dict],
    platform: str,
    *,
    captured_at: str | None = None,
    dry_run: bool = False,
    force: bool = False,
) -> dict:
    """Write one snapshot per matched row. Returns the plan, plus `written`."""
    result = plan(conn, rows, platform, captured_at=captured_at)
    result["dry_run"] = dry_run
    result["forced"] = force and result["aborted"]
    if result["aborted"] and not force:
        result["written"] = 0
        return result
    result["aborted"] = False

    if dry_run:
        result["written"] = 0
        return result

    for entry in result["write"]:
        row = entry["row"]
        add_metrics_for_post(
            conn,
            entry["post_id"],
            views=entry["views"],
            likes=_int(row, "likes"),
            comments=_int(row, "comments"),
            shares=_int(row, "shares"),
            followers_gained=_int(row, "followers_gained"),
            watch_time_s=float(row.get("watch_time_s", 0.0)),
            clicks=_int(row, "clicks"),
            captured_at=result["captured_at"],
            commit=False,
        )
    conn.commit()
    result["written"] = len(result["write"])
    return result


def ingest_file(
    conn: sqlite3.Connection,
    path: str,
    platform: str,
    *,
    captured_at: str | None = None,
    dry_run: bool = False,
    force: bool = False,
    overrides: dict[str, str] | None = None,
) -> dict:
    """Read an export off disk and import it."""
    rows = parse_text(load(path), overrides)
    if not rows:
        raise IngestError(f"{path} produced no importable rows")
    result = ingest(conn, rows, platform, captured_at=captured_at,
                    dry_run=dry_run, force=force)
    result["source"] = path
    return result


def fix_command(entry: dict, platform: str) -> str:
    """The command that would make an unmatched row match next time."""
    row = entry["row"]
    ref = row.get("slug") or slugify(row.get("title") or "") or "<content>"
    parts = [f"revops post {ref} {platform.lower()}"]
    if row.get("url"):
        parts.append(f"--url {row['url']}")
    return " ".join(parts)
