# Working in this repo

This repository holds **two unrelated products**. Read the section for the one
you are touching; their constraints differ in places.

- **`src/deoltech/`** — Deol Tech, a paper trading platform. See "Deol Tech"
  below and `docs/DEOLTECH.md`.
- **`src/revops/`** — the revenue tracker described in the rest of this file.


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


---

# Deol Tech (`src/deoltech/`)

A paper trading platform for stocks, crypto and forex. Live market data from
Finviz, a matching engine that models real execution costs, and a multi-user web
app with administrator accounts. Full documentation is in `docs/DEOLTECH.md`;
read it before changing engine behaviour.

## Constraints

- **Stdlib only**, same as revops. Python 3.11, SQLite, no requirements file.
  The web app is `http.server`; the UI has no build step.
- **Local-first.** Real data lives in `data/deoltech.db`, which is gitignored.
- **Tests never touch the network or the real database.** `setUpModule` points
  `DEOLTECH_DB` at a temp file; market-data tests use the deterministic feed or
  recorded Finviz fixtures. Do not add a test that fetches from finviz.com.

## The rules that must not be relaxed

These are the difference between a simulator that teaches and one that flatters.
Each has a test written so the optimistic implementation fails it.

- **Stops gap through.** An elected stop fills at the market, not at the stop
  price. `matching.match_bar` takes the *worse* of the stop and the bar's open.
- **No lookahead.** A signal from a bar's close fills at the next bar's open.
  The backtest loop in `backtest.py` matches orders *before* showing the
  strategy the bar; do not reorder those steps.
- **Limits fill at the limit**, never at the bar's favourable extreme.
- **Resting limits need the market to trade through them**, and fill as makers
  at their own price.
- **Costs are always charged** — spread, slippage, commission, regulatory fees,
  swap, borrow. A backtest with fees switched off is not a result.
- **Median beside mean, always.** Same house rule as revops: trade P&L is
  fat-tailed. `MIN_TRADES = 20` gates per-trade statistics, and annualized
  figures are suppressed under 30 days of history.
- **Never invent a price.** Finviz parsers raise `ParseError` when no known
  response shape matches. Do not add a fallback that guesses.
- **Degrade visibly.** When the live feed fails the platform serves simulated
  prices and says so in the UI, the health endpoint and the admin console. Never
  present a simulated or stale price as live.

## Units and currency, where the bugs live

- `Instrument.adv` is in **tradeable units** (shares/coins/base currency), not
  dollars. The impact model divides an order quantity by it.
- `Instrument.notional()` is in the instrument's **quote currency**. Anything
  derived from it — crypto exchange fees, FX swap — must be converted to the
  account currency before it reaches `FeeBreakdown`. A long 100k USD/JPY earns
  about $10/day of carry; skipping the conversion reports ¥1,572.
- Concentration limits are measured on **margin**, not notional. Measuring
  notional makes an ordinary 100k EUR/USD position read as 1,085% of a $10k
  account.
- The broker takes its time from `self.clock`, never the wall clock. The
  backtester points it at the bar being processed.

## Running things

```bash
export PYTHONPATH=src
python3 -m deoltech admin create        # first administrator
python3 -m deoltech serve               # http://127.0.0.1:8000
python3 -m deoltech probe               # is Finviz reachable and parsing?
python3 -m deoltech demo                # seed a demo account from replayed history
python3 -m unittest discover -s tests   # 139 tests
```
