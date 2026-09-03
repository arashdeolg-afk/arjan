---
name: revops-ingest
description: Pull performance numbers off the platforms and load them into the revops database, so rankings run on real data instead of nothing. Use when Arjan says "ingest the numbers", "import the analytics", "load the export", "update the stats", "how did the clips do", "pull the view counts", or when a fresh analytics export lands and revops report is still showing low-confidence rankings.
---

# revops-ingest

`revops report` ranks topics, hooks and platforms by **median** views and
refuses to sound confident below `MIN_SAMPLE = 3`. That gating only works if
the numbers actually get in. Typing `revops track` once per post per platform
does not survive contact with a real week, so the rankings stay empty and the
whole measurement layer is decorative.

This skill closes that loop: export → `revops ingest` → `revops report`.

## When to run it

Weekly is enough. View counts on a short mostly settle within 7 days, and
`analytics.py` keeps every snapshot, so a weekly cadence still gives velocity.

Run it after `marketing-head` has published a batch, or whenever
`revops report` shows `(low n)` next to rankings that ought to be trustworthy
by now.

## The workflow

### 1. Get the export

Each platform hands you a file. Whatever it's called, save it somewhere and
note **which platform it came from** — ingest needs to be told, because a
YouTube export and a TikTok export both just say "Views".

- **YouTube Studio** → Analytics → Advanced mode → Export → *Table data.csv*
- **TikTok** → Creator Center → Analytics → Content → Download data
- **Instagram** → Professional dashboard → Insights → Export
- **postiz** (if installed) → `postiz analytics --format json > yt.json`

Anything with a title-or-URL column and a views column works, including a
spreadsheet Arjan typed by hand.

### 2. Always dry-run first

```bash
PYTHONPATH=src python3 -m revops ingest ~/Downloads/yt.csv \
    --platform youtube --dry-run
```

This writes nothing and prints exactly what a real run would do. Read the
**UNMATCHED** section before going further — see step 3.

### 3. Fix unmatched rows

Ingest matches an export row to a post by, in order: `slug` column →
`external_id` → `url` → title slugified. A row that matches none of those is
**skipped and reported**, never guessed at, because a half-imported export
produces a confident and wrong ranking.

Each unmatched row prints the command that fixes it. Usually the content was
never logged, or was logged but never marked as posted to that platform:

```bash
PYTHONPATH=src python3 -m revops new "Ninja Barista Ep 3" \
    --topic anime-comedy --hook cold-open --cost 2.40 --minutes 35
PYTHONPATH=src python3 -m revops post ninja-barista-ep-3 youtube --url https://youtu.be/xyz
```

If titles drift between the studio and the platform, add a `slug` column to
the export — that matches exactly and permanently.

### 4. Run it for real

```bash
PYTHONPATH=src python3 -m revops ingest ~/Downloads/yt.csv --platform youtube
PYTHONPATH=src python3 -m revops report --days 30
```

Re-running the same export is safe: identical snapshots at the same timestamp
are skipped rather than stacked.

## The one thing that will bite you

**Export lifetime totals, not a daily breakdown.**

`analytics.py` reads the *most recent* snapshot per post as that post's total
(`LATEST_METRICS`). It does not sum snapshots — summing would double-count
every time you re-import. So a daily-breakdown export ("this video got 40
views on Tuesday") overwrites "this video has 50,000 views" and silently
re-ranks every topic in the report.

Ingest catches the common case: when most matched rows report *fewer* views
than what's already stored, it refuses the whole file and explains why. In
YouTube Studio that means picking a date range and exporting the **table**,
not the day-by-day chart.

If a drop is genuine — a video was deleted, or the platform corrected its
count — `--force` accepts it.

## Escape hatches

```bash
# A column this system doesn't recognise
--map "Plays=views" --map "Profile visits=clicks"

# Backdate a snapshot you exported days ago
--captured-at 2026-09-01T00:00:00+00:00

# Pipe straight from another tool
postiz analytics --format json | \
  PYTHONPATH=src python3 -m revops ingest - --platform tiktok
```

Recognised fields for `--map`: `views`, `likes`, `comments`, `shares`,
`followers_gained`, `watch_time_s`, `clicks`, plus the identity columns
`slug`, `external_id`, `url`, `title`.

## What it deliberately will not do

- **Guess at unmatched rows.** Fuzzy title matching would attach numbers to
  the wrong video, and nothing downstream would ever reveal it.
- **Treat impressions or reach as views.** Different measures; conflating
  them inflates every ranking.
- **Touch the network.** It reads files. Fetching is the platform's job or
  postiz's, which keeps this testable and keeps `revops` stdlib-only.
