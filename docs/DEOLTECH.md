# Deol Tech — Paper Trading Platform

Professional paper trading for **stocks, crypto and forex**, with live market
data from Finviz, a matching engine that models real execution costs, and a
multi-user web platform with administrator accounts.

Pure Python 3.11 standard library. No dependencies, no build step, no services
to provision. `python -m deoltech serve` and it is running.

**Nothing here places a real order or touches real money.**

---

## Quick start

```bash
export PYTHONPATH=src

python3 -m deoltech admin create            # first administrator (prints a password)
python3 -m deoltech demo                    # optional: a seeded demo account
python3 -m deoltech serve                   # http://127.0.0.1:8000
```

On first run with no administrator, the web app redirects to `/setup` so you can
create one in the browser instead.

```bash
python3 -m deoltech quote AAPL BTCUSD EURUSD    # live prices
python3 -m deoltech probe                       # is Finviz reachable?
python3 -m deoltech backtest sma-crossover AAPL --param fast=10 --param slow=30
python3 -m deoltech backup /var/backups         # consistent, verified, compressed
python3 -m unittest discover -s tests           # 154 tests, no network
```

---

## Why this exists

Most paper trading is worse than useless because it is too kind. It fills market
orders at the last printed price, fills stop-losses exactly at the stop, ignores
commissions, and lets a strategy buy the low of the bar it is looking at. A
trader learns a set of habits that lose money the moment real fills are
involved.

Deol Tech is built the other way round. Every simplification that would flatter
a result has been removed on purpose:

| What most simulators do | What Deol Tech does |
|---|---|
| Fill at the last price | Cross a modelled bid/ask spread, and pay it |
| Stop-loss fills at the stop | **Stops gap through** — a stop at 100 fills at 92 when the market opens at 92 |
| Unlimited size at one price | Fills bounded by displayed liquidity; larger orders walk the book |
| Commission-free | SEC Section 31 and FINRA TAF on equity sells, maker/taker bps on crypto, per-lot commission plus overnight swap on FX |
| Signal and fill on the same bar | A signal from a bar's close fills at the **next** bar's open |
| One leverage number | Reg-T 2:1 on equities, 1:1 spot crypto, 50:1 FX majors / 20:1 minors |
| Shorting is a long with a minus sign | Real short accounting, margin, and daily borrow cost |
| Averages everywhere | **Median trade reported alongside the mean**, always |

The last one matters more than it looks. Trade P&L is fat-tailed: one outsized
winner drags the mean above a strategy that loses on most trades. When the mean
is positive and the median is not, the platform says so in plain language rather
than showing a green number.

---

## Market data

Finviz publishes no documented public API, so the adapter reads the surfaces a
browser does, plus one supported export:

| Asset class | Endpoint | Notes |
|---|---|---|
| Equities (bulk) | `screener.ashx?v=111&t=…` | One request for up to 40 symbols |
| Equities (deep) | `quote.ashx?t=SYM` | Price plus the fundamentals table |
| Equities (Elite) | `export.ashx?…&auth=TOKEN` | CSV; used automatically when a token is configured |
| Crypto | `api/crypto_all.ashx` | Every pair in one payload |
| Forex | `api/forex_all.ashx` | Every pair in one payload |
| Bars (any) | `api/quote.ashx?instrument=…` | OHLCV series |

Three properties make this survivable in production:

**Bulk endpoints are preferred.** A forty-symbol watchlist is one request, not
forty. Politeness here is what keeps the feed working.

**Parsers are shape-tolerant and fail loudly.** Every parser accepts each
response shape Finviz has been observed to serve, and raises `ParseError` rather
than inventing a price when none of them match. Prices are the one thing this
system must never guess at.

**`deoltech probe` tells you which endpoint broke.** After a Finviz redesign, run
it: a format change becomes a named failing endpoint instead of an empty
watchlist.

```
$ python3 -m deoltech probe
  ok           equity/screener         2 records
  ok           equity/quote            1 records
  FAIL         crypto/all              0 records   ParseError: no pairs found …
```

### When Finviz is unreachable

The feed stack is `CachingFeed(CompositeFeed(FinvizFeed, SyntheticFeed))`. If
Finviz is down, rate-limiting, or blocked by a network policy, the platform
falls through to a deterministic simulator and **says so** — the sidebar reads
`SIMULATED — live feed unreachable`, `/api/health` reports
`"market_data": "degraded"`, and the admin console shows the last error. It
degrades visibly; it never passes a simulated or stale price off as live.

Feed modes (`--feed`, or the admin console):

- `auto` — Finviz with the simulator behind it. The production default.
- `live` — Finviz only. Fails loudly rather than serving simulated prices.
- `synthetic` — simulator only. Demos, training, air-gapped installs, tests.

The simulator is a *pure function of (symbol, timestamp)* — fractional Brownian
motion in log-price space — so restarts do not teleport prices and two workers
agree on what BTC costs. It produces realistic volatility by asset class (~30%
equities, ~65% crypto, ~8% FX) but is **not a claim about market dynamics** and
nothing from it is a forecast.

### A note on quality

Finviz serves delayed prices (roughly 15 minutes for US equities) and no
bid/ask. Both are handled honestly rather than hidden: quotes carry their true
timestamp so staleness checks fire, and the missing book is synthesized with
`is_synthetic_book=True` set, so a fill against a modelled spread is never
mistaken for a fill against a real one.

---

## The execution engine

### Order types and time in force

`MARKET` · `LIMIT` · `STOP` · `STOP_LIMIT` · `TRAILING_STOP` · `MARKET_ON_CLOSE`

`DAY` · `GTC` · `GTD` · `IOC` · `FOK`

Flags: `post_only` (reject rather than cross), `reduce_only` (may shrink a
position, never open or flip one), `display_qty` (iceberg), `allow_extended`
(opt in to pre/post-market), plus `take_profit` / `stop_loss` which arm an OCO
bracket automatically when the entry fills.

### The rules that matter

**Stops gap through.** A stop-loss is not a guarantee of price, only of exit.
The engine reproduces this, including the case that teaches the most:

```
stop-loss @100, market gaps open to 92  ->  fills at 92    (8% worse than the stop)
stop-limit stop 100 / limit 99, same gap ->  NOT FILLED    (position stays open)
```

That second line is why a stop-limit is not a stop-loss, and the platform will
show you rather than tell you.

**Resting limits need the market to trade through them.** Being *at* the touch is
not being filled — there is a queue in front of you. Optimism here manufactures
an edge that evaporates with real money.

**Maker versus taker is tracked.** An order that rested and was then crossed
fills at its own limit as a maker; a marketable order pays the spread as a
taker. This flows straight through to fees, which is the point of `post_only`.

**Nothing fills in a closed market.** Orders queue for the next session, and a
DAY order placed at 9pm belongs to tomorrow rather than expiring on arrival.

### Costs

- **Equities** — zero commission by default, but never free: SEC Section 31
  ($27.80/$1M) and FINRA TAF ($0.000166/share, capped at $8.30) on **sells
  only**. A round trip therefore costs less than twice a single leg.
- **Crypto** — maker/taker basis points, tiered by 30-day volume.
- **FX** — $3.50 per standard lot per side, plus overnight swap at the 17:00 ET
  roll, tripled on Wednesday to carry the weekend. Swap accrues in the *quote*
  currency and is converted — a long 100k USD/JPY earns about $10/day, not
  ¥1,572.
- **Shorts** — daily borrow at the instrument's rate. Hard-to-borrow names cost
  what they really cost.

Slippage is the square-root law, `Δp/p = η·σ·√(Q/ADV)`, plus a latency term.
It is **deterministic** given the same inputs, so backtests reproduce and nobody
can re-roll until they like the answer.

### Pre-trade risk

Buying power and margin · fat-finger price collars · position concentration
(measured on *margin*, not notional, so leveraged instruments are not uniformly
banned) · pattern day trader rule · daily loss limit · short availability ·
per-account kill switch.

Every rejection returns a machine-readable code and a sentence a human can act
on:

```
insufficient_buying_power: needs 20,000.00 of margin, account has 9,982.14
                           available (2:1 on AAPL)
```

### Accounting

FIFO tax lots (not average cost), real short accounting, multi-currency cash
with conversion to the account currency, Reg-T margin with maintenance calls and
largest-requirement-first liquidation, and an append-only cash ledger where
every balance on screen can be traced to the events that produced it.

---

## Strategies and backtesting

Six built-ins: `buy-and-hold`, `sma-crossover`, `donchian-breakout`,
`mean-reversion`, `rsi-pullback`, `bollinger-breakout`.

`buy-and-hold` is included deliberately — it is the benchmark every other
strategy has to beat, and every backtest reports **alpha against it**. A system
that makes that comparison inconvenient is helping its user fool themselves.

The backtester uses the **same matching engine, fee schedule and risk checks as
live paper trading**, and the bar loop enforces the ordering that prevents
lookahead:

```
for each bar:
    1. match orders placed on the PREVIOUS bar against THIS bar
    2. mark the portfolio to this bar's close
    3. record the equity point
    4. show the strategy this completed bar
       (any orders it places are matched on the NEXT bar)
```

Writing a strategy:

```python
from deoltech.strategies import Strategy, register
from deoltech.strategies.indicators import atr, sma, crossed_above

@register
class MyStrategy(Strategy):
    name = "my-strategy"
    params_schema = {"fast": {"type": "int", "default": 10}}

    def on_bar(self, ctx, bar):
        fast = sma(ctx.closes, self.param("fast"))
        slow = sma(ctx.closes, 50)
        i = len(ctx.bars) - 1
        if ctx.is_flat and crossed_above(fast, slow, i):
            stop_distance = 2 * (atr(ctx.bars, 14)[i] or bar.close * 0.02)
            qty = ctx.size_by_risk(stop_distance, risk_pct=1.0)
            ctx.buy(qty, stop_loss=bar.close - stop_distance)
```

`size_by_risk` is what makes results comparable across instruments: the same 1%
is at stake whether the stop is 30 cents away on a $12 stock or $900 away on
Bitcoin.

---

## Users, roles and administration

Three roles:

| | viewer | trader | admin |
|---|:--:|:--:|:--:|
| View markets, accounts, blotter, analytics | ● | ● | ● |
| Run backtests | ● | ● | ● |
| Place and cancel orders | | ● | ● |
| Manage own account, watchlist, API tokens | | ● | ● |
| Create/suspend/delete users, reset passwords | | | ● |
| Halt accounts, change feed settings, read the audit log | | | ● |

### Security

- **PBKDF2-HMAC-SHA256, 600,000 iterations**, 16-byte per-user salt, with
  transparent rehashing on login when the cost factor is raised.
- **Constant-time comparison** everywhere a secret is checked.
- **Session tokens stored hashed** — a stolen database yields hashes to grind,
  not live cookies to replay.
- **Username enumeration resisted**: a bad username and a bad password give the
  same message, and a wrong username still runs a dummy hash so the timing
  matches.
- **Login throttling** — per-account lockout after 8 failures plus a per-IP
  sliding window, so spraying one password across many usernames is limited too.
- **Privilege changes revoke live sessions.** A suspended user is out
  immediately, not at the end of their session.
- **The last administrator cannot be demoted, suspended or deleted** — losing it
  would lock everyone out with no supported way back in.
- **CSRF** via an HMAC-signed double-submit token on every state-changing
  request.
- **A strict Content-Security-Policy** with no `unsafe-inline` and no external
  origins. There is not one inline `style` or `script` in the application.
- **API tokens are scoped, and the scope is enforced.** A token's effective
  permissions are its scopes (`read`, `trade`, `admin`) intersected with the
  owner's role, so a token can never exceed the person who issued it and a
  read-only token cannot trade even for an administrator. Unknown scopes
  narrow rather than widen.
- **Credentials never travel in a URL.** A new password or API token is shown
  through a one-shot server-side store, not a redirect query string — which
  would put it in the access log, nginx's log, and the browser's history.
  Query strings are redacted from the request log regardless.
- **Every administrative action is audited** with actor, target, detail and IP.

Two things an administrator deliberately **cannot** do: read a user's password
(there is nothing to read), or place a trade on someone else's account. Admins
can halt, inspect and reset, which covers the operational needs without creating
a way to trade as someone else.

---

## Deployment

Everything needed is in [`deploy/`](../deploy). For a step-by-step launch on a
fresh VPS — server hardening, DNS, TLS, backups, adding users — follow
**[docs/LAUNCH.md](LAUNCH.md)**.

### Docker (recommended)

```bash
cp deploy/.env.example deploy/.env
python3 -c "import secrets; print(secrets.token_urlsafe(48))"   # → DEOLTECH_SECRET

# Brings the stack up and obtains a Let's Encrypt certificate.
DOMAIN=trade.example.com EMAIL=you@example.com ./deploy/init-tls.sh

docker compose -f deploy/docker-compose.yml exec app python -m deoltech admin create
docker compose -f deploy/docker-compose.yml exec app python -m deoltech probe
```

That last command is the one worth running: it confirms Finviz is actually
reachable from the server. A host that cannot reach it runs happily on
simulated prices and looks completely normal.

The app binds to `127.0.0.1` only; nginx terminates TLS and is the sole
internet-facing service. The image runs as an unprivileged user with a read-only
root filesystem, and the database lives on a named volume so redeploys do not
wipe it.

### systemd

`deploy/deoltech.service` — hardened unit (`ProtectSystem=strict`,
`NoNewPrivileges`, a syscall filter, one writable path).

### Behind a reverse proxy

Run with `--trust-proxy --secure-cookies`. The supplied nginx config
**overwrites** `X-Forwarded-For` rather than appending to it — appending would
let any client forge their IP past the login rate limiter and into the audit
log.

### Backups

```bash
./deploy/backup.sh /var/backups/deoltech
```

Uses SQLite's online backup API, verifies the result with an integrity check
before compressing it, and applies 30-day retention. Copying a live database
with `cp` can capture a torn write and produce a file that only looks like a
backup.

### Configuration

| Variable | Purpose |
|---|---|
| `DEOLTECH_SECRET` | Signs session cookies and CSRF tokens. Set it. |
| `DEOLTECH_DB` | SQLite path (default `data/deoltech.db`) |
| `DEOLTECH_FEED` | `auto` / `live` / `synthetic` |
| `FINVIZ_AUTH_TOKEN` | Optional Elite token; switches to the CSV export |
| `DEOLTECH_HOST` / `DEOLTECH_PORT` | Bind address |

---

## HTTP API

Every endpoint accepts a session cookie or `Authorization: Bearer dt_…`, under
the same permission checks as the UI.

Tokens are scoped: `read` grants the view and backtest permissions, `trade`
adds order entry and account management, and `admin` — never implied by the
others — adds the administrative ones. The effective set is always the scope
intersected with the owner's role.

```
GET  /api/health                     liveness; no auth
GET  /api/quotes?symbols=A,B,C       batch quotes + feed status
GET  /api/quotes/<symbol>            one quote with its book
GET  /api/bars?symbol=&interval=     OHLCV
GET  /api/account                    summary, positions, working orders
GET  /api/equity-curve               NAV history
GET  /api/blotter                    executions
GET  /api/performance                full performance record
GET  /api/instruments?q=             search the contract catalog
GET  /api/max-qty?symbol=&side=      largest permitted size
POST /api/preview                    cost and risk BEFORE placing
POST /api/orders                     place an order
POST /api/orders/<id>/cancel
POST /api/positions/<symbol>/close
```

`/api/preview` is worth calling out: it returns the estimated fill, the spread
being crossed, itemized fees, the margin consumed, remaining buying power, and
the pre-trade risk verdict — before the click, not after.

---

## Layout

```
src/deoltech/
  types.py          core value objects: Quote, Bar, Order, Fill, Position
  clock.py          market calendars — NYSE holidays, FX week, 24/7 crypto
  instruments.py    contract specs and symbology for all three asset classes
  portfolio.py      FIFO lots, shorts, multi-currency cash, margin
  analytics.py      performance, with median-first and low-sample gating
  backtest.py       historical replay through the live engine
  accounts.py       account service, write-through persistence
  auth.py           passwords, sessions, roles, API tokens
  db.py             SQLite schema
  cli.py            command line interface
  feeds/
    base.py         Feed contract, HTTP client, breaker, rate limiter
    finviz.py       the live adapter and its parsers
    synthetic.py    deterministic simulated market
    cache.py        TTL cache and last-known-good retention
  engine/
    book.py         order book synthesis and spread modelling
    slippage.py     market impact and latency
    fees.py         commissions, regulatory fees, swap, borrow
    matching.py     the matching engine
    risk.py         pre-trade risk
    broker.py       order lifecycle, brackets, financing, margin calls
  strategies/       strategy API, indicators, built-in library
  web/
    server.py       routing, sessions, CSRF, security headers
    app.py          routes and authentication middleware
    views.py        pages
    admin.py        administrator console
    api.py          JSON API
    templates.py    HTML rendering
    assets.py       stylesheet and client script
tests/              154 tests, no network, no real database
deploy/             Dockerfile, compose, nginx, systemd, backups
```

---

## Testing

```bash
python3 -m unittest discover -s tests -v
```

Two rules the suite holds itself to: **no network** (market-data tests use the
deterministic feed or recorded Finviz fixtures) and **no real database**
(`DEOLTECH_DB` is pointed at a temp file before anything imports it).

The matching-engine tests are the important ones. Each is written so that the
*optimistic* implementation fails it — a simulator that filled stops at the stop
price, or let a strategy see the current bar, would go red.

---

## Limitations, stated plainly

- **Finviz data is delayed** (~15 minutes for US equities) and carries no
  bid/ask. Every spread in this system is modelled, and labelled as modelled.
- **The synthetic feed is not a market model.** It generates plausible-looking
  price action for testing and fallback. It forecasts nothing.
- **Fills are simulated.** However carefully the microstructure is modelled, no
  simulator can tell you what the market would have done had your order actually
  been in it.
- **Money is float, not Decimal.** No real cash settles here; the ledger rounds
  to the currency's minor unit on every write, so balances stay exact to the
  cent.
- **Single-node.** SQLite with WAL and one writer. Right for hundreds of users;
  a different database if you ever need more.
- **Backtest results are not predictions.** A grid search's best cell is mostly a
  measurement of how many cells were tried.
