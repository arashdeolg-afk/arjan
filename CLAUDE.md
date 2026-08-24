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

## The second package: `polymkt`

`src/polymkt` is a read-only Polymarket client (prediction-market prices as a
probability feed). It shares this repo's constraints — stdlib only, local-first,
SQLite in `data/polymkt.db`, gitignored — and is otherwise independent of
`revops`; neither imports the other.

Three things to know before changing it:

- **It is read-only on purpose.** Placing orders needs EIP-712 signing, which
  needs a crypto dependency. Don't add one without revisiting the stdlib rule.
- **No endpoint has been verified against a live server** — the environment it
  was written in blocks `*.polymarket.com`. Provenance is tracked per endpoint
  in `endpoints.py`; `polymkt doctor` checks the catalog and promotes entries.
- **Credentials are environment-only.** Never a file, never a commit, never a
  default. `config.credential_status()` must never return a secret.

Same sample-size discipline as `revops`: `moves` prints `n` beside every change.

## Running things

```bash
PYTHONPATH=src python3 -m revops demo      # sample data
PYTHONPATH=src python3 -m revops report
python3 polymkt.py demo                    # offline Polymarket walkthrough
python3 polymkt.py doctor                  # verify endpoints (needs network)
python3 -m unittest discover -s tests -v   # tests
```

`polymkt.py` at the repo root is a path shim so the CLI runs without
`PYTHONPATH`; the bash-only `PYTHONPATH=src python3 -m polymkt` form still
works but breaks on Windows PowerShell.

Tests set `REVOPS_DB` / `POLYMKT_DB` to a temp path — never let a test touch
`data/revops.db` or `data/polymkt.db`. Every `polymkt` test runs offline via an
injected transport; nothing in the suite may reach the network.
