# Working in this repo

Three independent tools live here: `revops` (revenue tracking for the content
studio), `polymkt` (a read-only Polymarket client) and `pmpaper` (a Polymarket
paper-trading harness). They share only the repo and the stdlib-only rule — do
not couple them. `polymkt` reads live prices; `pmpaper` measures whether a
strategy has an edge. None of them import each other.

## revops

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

## polymkt

`src/polymkt` is a read-only Polymarket client (prediction-market prices as a
probability feed), documented in `docs/POLYMKT.md`. It shares this repo's
constraints — stdlib only, local-first, SQLite in `data/polymkt.db`, gitignored
— and is independent of both `revops` and `pmpaper`; none of them import each
other. It is the *price feed*; `pmpaper` is the *edge measurement*.

Three things to know before changing it:

- **It is read-only on purpose.** Placing orders needs EIP-712 signing, which
  needs a crypto dependency. Don't add one without revisiting the stdlib rule.
- **No endpoint has been verified against a live server** — the environment it
  was written in blocks `*.polymarket.com`. Provenance is tracked per endpoint
  in `endpoints.py`; `polymkt doctor` checks the catalog and promotes entries.
  Record the date of a passing run in `docs/POLYMKT.md`.
- **Credentials are environment-only.** Never a file, never a commit, never a
  default. `config.credential_status()` must never return a secret.

Same sample-size discipline as `revops`: `moves` prints `n` beside every change.

## Running things

```bash
PYTHONPATH=src python3 -m revops demo      # sample data
PYTHONPATH=src python3 -m revops report
python3 polymkt.py demo                    # offline Polymarket walkthrough
python3 polymkt.py doctor                  # verify endpoints (needs network)
PYTHONPATH=src python3 -m pmpaper validate # prove the harness works
python3 -m unittest discover -s tests -v   # tests
```

`polymkt.py` at the repo root is a path shim so the CLI runs without
`PYTHONPATH`; the bash-only `PYTHONPATH=src python3 -m polymkt` form still
works but breaks on Windows PowerShell.

Tests set `REVOPS_DB` / `POLYMKT_DB` to a temp path — never let a test touch
`data/revops.db` or `data/polymkt.db`. Every `polymkt` and `pmpaper` test runs
offline; nothing in the suite may reach the network.

## pmpaper

A paper-trading harness for Polymarket binaries (`src/pmpaper/`, docs in
`docs/POLYMARKET.md`). Its purpose is to *refuse* to confirm edges that
aren't there, so the conservative behaviour is the feature, not a bug.

- **Costs are mandatory.** Spread, latency, and fees are all modelled. A
  decision made on the book at time t fills against the book at t+latency;
  an order landing after its window closes is not a fill. Never "simplify"
  any of these away — each one alone makes a coin flip look profitable.
- **Validate before trusting.** `python3 -m pmpaper validate` checks the
  harness against a synthetic market with a known injected edge. It must
  pass all five checks, including that it does NOT flag a real-but-small
  edge as significant. If you change the fill model or stats, re-run it.
- **Statistical tolerances, not flat ones.** Comparisons against theory use
  a multiple-of-standard-error bound. An early version of the self-check
  used a flat tolerance and failed on a correct implementation.
- **Network is often blocked.** `feeds.py` splits `fetch_*` (IO) from
  `parse_*` (pure) so parsers stay unit-testable without a live venue.
  Tests must never hit the network.
