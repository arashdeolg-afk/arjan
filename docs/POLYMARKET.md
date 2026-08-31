# pmpaper — measuring an edge before betting on it

A paper-trading harness for Polymarket binary markets. It exists to answer
one question honestly: **does this strategy have an edge that survives
spread, latency and fees — or does it only look like it does?**

```bash
PYTHONPATH=src python3 -m pmpaper validate         # prove the harness works
PYTHONPATH=src python3 -m pmpaper sim fair-value-arb --maker-lag 2000 --latency 150
PYTHONPATH=src python3 -m pmpaper probe            # can this machine reach the APIs?
PYTHONPATH=src python3 -m pmpaper record --duration 3600
PYTHONPATH=src python3 -m pmpaper replay 1 fair-value-arb --latency 150
```

---

## Why the 5-minute BTC market is hard

Two numbers decide it before any strategy is written.

**The drift is ~1,000x smaller than the noise.** BTC at 50% annualised vol
has a 5-minute standard deviation of **15.4 basis points**. Even assuming an
aggressive 50%/year expected return, the drift over the same five minutes is
**0.05 bp**. Run that through a normal CDF and the true probability of "up"
is **50.1%** — a number this repo computes rather than asserts:

```python
fair_yes(60_000, 60_000, 300, 0.50)   # -> 0.49969
```

**The spread demands ~1 percentage point.** Those contracts quote 0–1 with a
1–3¢ spread. Buying at 51¢ when mid is 50¢ needs the true probability above
**51%** to break even. Fundamentals hand you 0.1pp of the 1pp you need.

So **over 90% of the required edge must come from something other than
predicting bitcoin.** That something is microstructure, which is why the only
strategy here with a coherent theory is `fair-value-arb`.

---

## What the harness actually proves

`pmpaper validate` runs five checks against a synthetic market whose true
edge is known by construction — the one setting where a measured edge can be
checked against the truth.

| # | Check | What it proves |
|---|---|---|
| 1 | Control loses the half-spread | The fill model charges costs correctly |
| 2 | Fair market yields nothing | No false positives |
| 3 | Injected edge is found | Real edges are recovered |
| 4 | Small real edge is *not* called | It won't call luck an edge |
| 5 | Edge decays with your latency | The edge is a race |

Check 5 is the finding that answers the original question:

```
  your latency       roi   verdict
         100ms     13.4%   EDGE DETECTED
        1000ms     11.7%   EDGE DETECTED
        5000ms      5.3%   NO EDGE DETECTED
       10000ms     -5.3%   NO EDGE DETECTED
       15000ms     -5.5%   NO EDGE DETECTED
```

The maker's quote is stale by 10 seconds throughout. **Only your own speed
changes.** The edge inverts precisely where your latency reaches the maker's
lag — past that point you are the stale side, and the same strategy that made
13% now loses 5%.

That is the whole answer to "can a fast algorithm win here". The edge is not
forecasting bitcoin; it is being faster than the maker. Real makers on that
market react to Binance and Coinbase in single-digit milliseconds from
colocated hardware. From a retail VM over public internet you are 80–250ms
behind. You are on the wrong row of that table.

---

## The finding that costs people the most money

Check 4 injects a **real** edge — a 2-second stale quote, enormous by
market-making standards — and the harness still refuses to call it:

```
  trades=1,000   roi=+4.7%   verdict=NO EDGE DETECTED
  needs ~3,542 trades to prove — about 12 days of continuous markets
```

A genuine +4.7% return over a thousand trades is **not** distinguishable from
luck. Anyone who runs 100 trades, sees green, and scales up is reading noise.

The variance is worse than intuition suggests. Running the control strategy —
which has a **known, guaranteed negative** edge — across eight independent
samples of 601 trades:

```
 seed   mean pnl   win rate
    1    -0.0142      0.496
    2    -0.0092      0.501
    3    -0.0424      0.468
    4    +0.0258      0.536      <- "profitable"
    5    +0.0175      0.527      <- "profitable"
    6    -0.0375      0.473
    7    +0.0108      0.521      <- "profitable"
    8    -0.0258      0.484
```

**Four of eight samples printed a profit on a strategy that cannot win.**
Pooled across all 4,808 trades the mean lands at −0.0094 against a theoretical
−0.0103 — a 0.13σ match. The edge was never there; the samples were too small
to say so.

---

## How the costs are modelled

Omit any one of these and a coin flip looks profitable.

- **Spread** — you buy the ask and sell the bid, never the mid.
- **Latency** — you decide on the book at time *t* and fill against the book
  at *t + latency*. If the underlying moved meanwhile, you eat it. An order
  landing after its window closes is **not** a fill.
- **Fees** — charged on notional, configurable in basis points.

Slippage is signed so positive always means *worse than expected*, whether
you were buying or selling.

---

## Using it on your own data

The endpoints are blocked from some networks, so start with `probe`:

```bash
PYTHONPATH=src python3 -m pmpaper probe
```

Then record real market data for as long as you can stand, and replay
strategies against the same tape:

```bash
PYTHONPATH=src python3 -m pmpaper record --duration 86400 --interval 1
PYTHONPATH=src python3 -m pmpaper runs
PYTHONPATH=src python3 -m pmpaper replay 1 fair-value-arb --latency 150 --fee-bps 0
```

**Measure your real latency first.** It is the single input that decides the
outcome, and guessing it optimistically is how a backtest lies to you.

If you test several strategies, say so:

```bash
... replay 1 momentum --strategies-tested 8
```

That applies a Bonferroni correction. Testing eight strategies and reporting
the best one is a different experiment from testing one, and the significance
bar genuinely moves.

---

## What would change the answer

The harness is not an argument that prediction markets are always efficient.
Real mispricings exist in **thin, new, or unusual markets** where no
professional is paying attention. The 5-minute BTC contract is the opposite:
the most liquid, most contested, most obviously arbitraged market on the
venue. If free money were sitting there it would already be gone.

Point this harness at a market nobody is watching and the answer may differ.
Run it on the busiest one and it will tell you what the table above already
shows.

---

## Layout

```
src/pmpaper/
  book.py       Snapshot, fill model (spread + latency + fees), settlement
  market.py     synthetic market with a controllable, known edge
  strategy.py   strategies; fair-value-arb is the only theoretically sound one
  engine.py     replay loop
  stats.py      the honesty layer: CIs, required sample size, risk of ruin
  feeds.py      live recorders; fetch and parse split so parsers are testable
  db.py         SQLite recording
  cli.py        validate | sim | probe | record | replay | runs
```
