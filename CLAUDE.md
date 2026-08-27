# Working in this repo

Two apps live here, both pure-stdlib Python 3.11:

- `src/revops` — the revenue tracker (below).
- `src/forge` — a self-hosted Replit-style builder for websites and apps
  (browser IDE, live preview, code runner, Claude AI pane). See
  `docs/FORGE.md`. Its user data lives in `data/forge/` (gitignored);
  every network-supplied file path must go through `Store.resolve` (the
  path jail), and tests construct `Store(tmpdir)` so nothing touches
  real data.

`revops` is a revenue tracker for Arjan's AI-content studio. It exists to
answer: what earned, what didn't, and what's unlocked but unused.

## Context

Arjan already runs the production side via Claude skills — `gemini-anime-clip-chain`
(anime shorts), `marketing-head` (distribution to 7 platforms), plus Higgsfield
and Shopify MCP connections. **This repo does not duplicate any of that.** It is
the measurement and monetization layer on top.

There are two strategy docs. `docs/PLAYBOOK.md` is the long-run plan;
`docs/SPRINT.md` is the 7-day path to a first paying client, implemented by
`sprint.py`. The sprint is the deterministic revenue engine — outreach volume
converts at a measurable rate, unlike content, which depends on an algorithm.

`docs/PLAYBOOK.md`. Its central claim — that money comes from
selling the capability (client spots, digital products) rather than the content
(ad revenue) — shapes how `monetization.py` orders and gates the streams. Don't
reorder those without re-reading the playbook's economics table.

## Constraints

- **Stdlib only.** No third-party dependencies. It must run anywhere with
  Python 3.11 and nothing else. Do not add a requirements file.
- **Local-first.** Real revenue data lives in `data/*.db`, which is gitignored.
  Never commit real numbers.
- **Median, not mean.** View counts are power-law distributed. Any new ranking
  must use median and report sample size. See the note in `analytics.py`.
- **Blend priors, don't trust small samples.** `sprint.rates()` mixes observed
  conversion with `PRIORS` using `PRIOR_WEIGHT` pseudo-counts, so one closed
  deal never displays as a 100% close rate. Keep that behaviour if you touch it.
- **Lead stages never regress.** `set_stage` takes the max of current and new
  rank. A lost deal must still count toward the stages it reached, or funnel
  conversion silently inflates.
- **Honest gating.** `MIN_SAMPLE = 3`. Below that, flag low confidence rather
  than presenting a confident-looking ranking.

## Running things

```bash
PYTHONPATH=src python3 -m revops demo      # sample data
PYTHONPATH=src python3 -m revops report
python3 -m unittest discover -s tests -v   # tests
```

Tests set `REVOPS_DB` to a temp path — never let a test touch `data/revops.db`.
