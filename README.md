# revops — revenue operating system for an AI-content studio

> **Also in this repo:** [Forge](docs/FORGE.md) — a self-hosted,
> Replit-style builder for websites and apps. `PYTHONPATH=src python3 -m forge`
> and open http://127.0.0.1:8484. Zero dependencies, like everything here.

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

## The 7-day sprint — start here if you want money this week

The fastest predictable revenue isn't content, it's **client work sold by
direct outreach with free spec work attached**. No audience needed, no
algorithm in the loop: if 15 contacts produce 1 sale, 45 produce ~3, and that
is a decision rather than a hope.

Full plan, targeting, and the actual message copy: **[docs/SPRINT.md](docs/SPRINT.md)**

```bash
revops sprint --goal 600 --price 200      # computes your daily contact target
revops lead import prospects.csv          # bulk-load day 1's list (template in docs/)
revops lead add "Pixel Forge" --segment indie-game --handle @pixelforge \
       --product "roguelike launching in March"
revops lead set 1 spec_made               # made the free 5-second clip
revops lead set 1 contacted               # sent it
revops lead set 1 replied
revops lead set 1 won --amount 200        # records revenue automatically
revops pipeline                           # funnel, conversion, on-track or behind
revops followups                          # who to chase today
```

`pipeline` blends your real conversion rates with baseline assumptions, so one
lucky close never reads as a 100% close rate — and once you have real volume,
your numbers take over. It recomputes the daily target every time, so falling
behind shows up as a bigger number tomorrow rather than a nasty surprise on
day 7.

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
| `sprint` | Start a revenue sprint; computes the daily contact target |
| `lead` | Add and advance sales prospects (`add` / `set` / `list`) |
| `pipeline` | Funnel, conversion rates, and whether you're on pace |
| `followups` | Who to chase today, hottest leads first |

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
  sprint.py        outreach funnel: stages, conversion math, follow-ups
  dashboard.py     self-contained HTML output
  cli.py           the interface
docs/PLAYBOOK.md   the long-run strategy
docs/SPRINT.md     the 7-day plan to a first paying client
```
