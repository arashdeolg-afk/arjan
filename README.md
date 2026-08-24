# revops — revenue operating system for an AI-content studio

A local-first tracker that answers three questions honestly:

1. **What did I make, and what did it cost me?** (credits *and* hours)
2. **What actually worked?** (ranked so one lucky viral hit can't fool you)
3. **Where is money being left on the table?** (which revenue streams are
   unlocked but earning nothing)

Zero dependencies. Pure Python 3.11 stdlib + SQLite. Nothing to install, no
service to run, no data leaves your machine.

The strategy it encodes is in **[docs/PLAYBOOK.md](docs/PLAYBOOK.md)** — read
that first. The short version: *sell the capability, not the content.*

---

## Quick start

```bash
# See it working on realistic sample data
PYTHONPATH=src python3 -m revops demo
PYTHONPATH=src python3 -m revops report --days 60
PYTHONPATH=src python3 -m revops today
PYTHONPATH=src python3 -m revops dash        # -> out/dashboard.html
```

When you're ready to use your own numbers, point at a fresh database:

```bash
export REVOPS_DB=data/revops.db     # real data; gitignored
```

---

## Daily use

```bash
# 1. Log what you made
revops new "Cat vs Roomba ep.12" --topic anime-comedy \
    --hook cold-open-punchline --cost 1.40 --minutes 35 \
    --pipeline gemini-anime-clip-chain

# 2. Log where it went (marketing-head handles the actual posting)
revops post cat-vs-roomba-ep-12 tiktok youtube instagram x

# 3. A week later, snapshot how it did
revops track cat-vs-roomba-ep-12 tiktok --views 12400 --likes 890 --clicks 41

# 4. Log money in and out
revops earn client_ugc 300 --notes "spot for indie game studio"
revops earn affiliate 4.20 --platform tiktok --content cat-vs-roomba-ep-12
revops spend tools 40 --recurring --notes "generation credits"

# 5. Read the brief
revops today
```

Add a shell alias so it's one word:

```bash
alias revops='PYTHONPATH=/home/user/arjan/src python3 -m revops'
```

---

## Commands

| Command | Purpose |
|---|---|
| `today` | The daily brief. Start here. |
| `new` | Log a piece of content, with its cost in money and time |
| `post` | Record that it went live on one or more platforms |
| `track` | Snapshot performance (append-only — history is kept) |
| `earn` / `spend` | Money in / money out |
| `streams` | Which revenue streams are unlocked, and what's blocking the rest |
| `report --days N` | Full analysis: P&L, platforms, topics, hooks, actions |
| `dash` | Self-contained HTML dashboard |
| `demo` | Seed realistic sample data |

---

## Two design decisions worth knowing

**Everything ranks on median, never mean.** View counts are power-law
distributed: one breakout drags any average upward and makes a dead format look
alive. In the bundled demo data the `slow-build` hook owns the single biggest
video (241,991 views) *and* the worst median (1,021). Rank on the best video and
you'd make more of your worst-performing format. The tool reports median, best,
and sample size side by side so the difference is visible.

**Nothing is ranked below 3 samples without saying so.** Comparisons on tiny
samples are noise. Low-n rows are flagged, and `recommendations()` stays quiet
until there's enough data to justify an opinion.

---

## Layout

```
src/revops/
  db.py            schema (SQLite, created on first run)
  ledger.py        writes: content, posts, metrics, revenue, costs
  analytics.py     reads: P&L, platform efficiency, what's working
  monetization.py  revenue streams, unlock gates, activation steps
  dashboard.py     self-contained HTML output
  cli.py           the interface
docs/PLAYBOOK.md   the strategy — the important file
```

---

## Also in this repo: `polymkt`

A read-only [Polymarket](https://polymarket.com) client, same house rules —
stdlib only, local-first, SQLite. Prediction-market prices are probabilities,
and this reads them from a terminal.

```bash
PYTHONPATH=src python3 -m polymkt demo          # synthetic data, no network
PYTHONPATH=src python3 -m polymkt markets       # top markets by volume
PYTHONPATH=src python3 -m polymkt market <slug> --live
PYTHONPATH=src python3 -m polymkt watch add <slug>
PYTHONPATH=src python3 -m polymkt snap          # cron-friendly snapshot
PYTHONPATH=src python3 -m polymkt moves --days 7
```

It answers what the API alone won't: **how a probability moved.** `snap` records
book snapshots locally, append-only; `moves` reports the change with its sample
size attached, because two snapshots is a line and not a trend.

No credentials required — everything it reads is public. See
**[docs/POLYMARKET.md](docs/POLYMARKET.md)** for the API gotchas (token id vs
condition id, JSON-inside-JSON, why the midpoint isn't the price you pay) and
for which endpoints are still unverified.

```
src/polymkt/
  http.py          urllib client: throttle, backoff, injectable transport
  endpoints.py     the API surface as data, with per-endpoint provenance
  models.py        normalisation — where the JSON-inside-JSON is untangled
  gamma.py         discovery: events, markets, search
  clob.py          live prices, order books, history
  data.py          positions, activity, holders
  store.py         watchlist + append-only quote history
  samples.py       synthetic payloads, so demo and tests run offline
  cli.py           the interface
```
