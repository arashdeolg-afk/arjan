# Working in this repo

`revops` is a revenue tracker for Arjan's AI-content studio. It exists to
answer: what earned, what didn't, and what's unlocked but unused.

## Context

Arjan already runs the production side via Claude skills — `gemini-anime-clip-chain`
(anime shorts), `marketing-head` (distribution to 7 platforms), plus Higgsfield
and Shopify MCP connections. **This repo does not duplicate any of that.** It is
the measurement and monetization layer on top.

The strategy is in `docs/PLAYBOOK.md`. Its central claim — that money comes from
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
- **Honest gating.** `MIN_SAMPLE = 3`. Below that, flag low confidence rather
  than presenting a confident-looking ranking.

## Running things

```bash
PYTHONPATH=src python3 -m revops demo      # sample data
PYTHONPATH=src python3 -m revops report
python3 -m unittest discover -s tests -v   # tests
```

Tests set `REVOPS_DB` to a temp path — never let a test touch `data/revops.db`.
