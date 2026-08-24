# Polymarket notes

Working notes for `src/polymkt`. The parts that cost time to learn, and the
parts that are still unverified.

---

## What this is for

A Polymarket price *is* a probability. `0.62` means the market is willing to
pay 62¢ for a contract that settles at $1 if the thing happens — so the crowd
says 62%. That makes the API useful as a live, money-backed forecast feed,
independent of whether you ever place a trade.

This package reads that feed:

| you want | use |
|---|---|
| which questions exist, what they're called | Gamma |
| what a probability is *right now*, and how deep the book is | CLOB |
| who holds what, and what has traded | Data |
| how a probability *moved* | local snapshots (`snap` + `moves`) |

That last row is the one the API doesn't give you for free, which is why
there's a database.

---

## The three gotchas

**1. Token id ≠ condition id.** A market has one `conditionId`. Each *outcome*
has its own CLOB token id, its own order book, and its own price. Almost every
CLOB call wants the token id. The trap is `/prices-history`, whose parameter is
literally named `market` but takes a **token** id — pass a condition id and you
get an empty series rather than an error, so it looks like a market with no
history.

**2. Gamma returns JSON inside JSON.** `outcomes`, `outcomePrices` and
`clobTokenIds` come back as *strings* containing JSON arrays:

```json
{"outcomes": "[\"Yes\", \"No\"]", "outcomePrices": "[\"0.62\", \"0.38\"]"}
```

Iterate `"Yes"` naively and you get `['Y', 'e', 's']`. `models.as_list()`
decodes this once at the edge; there's a test pinning that exact bug.

**3. The midpoint is not the price you get.** These books are thin. A $2,000
order on a market quoting 62% can fill at 64%. `Book.sweep(usd)` walks the
ladder and returns the real average fill plus a partial-fill warning when the
book runs out. Quote the midpoint, budget for the sweep.

Two smaller ones: `Yes` and `No` books are independent, so `bid_No` is not
`1 - ask_Yes`; and outcome prices summing to 103% usually means stale data or
multi-outcome rounding, not free money.

---

## Verification status

This package was written in an environment where `*.polymarket.com` is blocked
by the network egress proxy, so **no call in it has been made against a live
server.** Rather than hide that, provenance is recorded per endpoint in
`endpoints.py`, weakest to strongest:

- `recall` — believed correct, never confirmed against anything
- `documented` — from Polymarket's published API overview (the base URLs)
- `client` — matches Polymarket's official `py-clob-client` source, read from
  PyPI 0.34.6 on 2026-08-24. PyPI is reachable from environments that block
  polymarket.com, which makes their own client a usable second-best source:
  the path spelling is theirs, not ours. It is still their code and not a live
  response, so a path could in principle be deprecated server-side.
- `verified` — confirmed by a `doctor` run against the live API

Current split: **15 `client`, 14 `recall`, 0 `verified`.** All 15 CLOB paths are
cross-checked. Gamma and Data are not — the official client is CLOB-only, so
every Gamma and Data path remains recall, as does `/prices-history`, which does
not appear in their client at all.

What that cross-check already corrected: paginated CLOB reads must send
`next_cursor=MA==` (base64 `0`) on the *first* request. Omitting the parameter
is not the same request as starting at zero, and this client used to omit it.
It also confirmed `LTE=` as the end sentinel, `/` as the health check, and
turned up seven endpoints that were missing here — `/time`,
`/last-trade-price`, `/tick-size`, `/neg-risk`, `/sampling-simplified-markets`,
and the batch `POST /prices` and `/spreads`.

To check the whole catalog from a machine with network access:

```bash
python3 polymkt.py doctor      # or: python polymkt.py doctor   (Windows)
```

It probes every endpoint that needs no user-supplied id and prints pass/fail.
Promote anything that answers to `confidence="verified"` and note the date
here. A blocked network and a wrong path look identical in that output — rule
out reachability before editing paths.

Last `doctor` run: **never** — the network is blocked wherever this has been
edited so far. That is the one gap the cross-check above cannot close: it
confirms the paths Polymarket's own code uses, not that the server still
answers them today.

---

## Credentials

Three different things get called credentials. Only two are secret, and this
package needs none of them.

| thing | secret? | needed for |
|---|---|---|
| Your wallet address (`0x…`) | **no** — it's on-chain and public | reading positions |
| CLOB API key / secret / passphrase (L2) | **yes** | order placement, private history |
| Your wallet private key | **yes, absolutely** | deriving L2 creds, signing orders |

Everything `polymkt` does today is public and unauthenticated: market
discovery, order books, prices, and anyone's positions by address. **Do not
supply API credentials to run any of it.**

Configuration is environment-only — nothing is read from or written to a file
in this repo:

```bash
export POLYMKT_ADDRESS=0x…          # public; the default account for `positions`
export POLYMKT_API_KEY=…            # only if a signing layer is added later
export POLYMKT_API_SECRET=…
export POLYMKT_API_PASSPHRASE=…
```

`polymkt whoami` prints what's configured and masks the key. `credential_status()`
never returns a secret, and a test asserts that.

> **If an L2 key, secret or passphrase has ever been pasted into a chat, a
> screenshot, an issue, or a commit, rotate it.** Revoke the old one in the
> Polymarket UI and create a new one. A key is cheap to replace and impossible
> to un-share.

---

## Why read-only

Placing an order means signing an EIP-712 typed-data struct with a secp256k1
key. There is no secp256k1 in the Python standard library, and this repo is
stdlib-only (see `CLAUDE.md`). Writing one by hand would be the worst of both
worlds: a hand-rolled signer guarding real money.

So the line is drawn at reading. If trading is wanted later, the honest options
are (a) relax the stdlib rule for a signing dependency such as `py-clob-client`,
or (b) keep signing in a separate, isolated tool and let `polymkt` stay the
research layer. `config.py` already has one obvious place for the credentials
either would need.

---

## Rate limits

Polymarket publishes per-endpoint limits, and they change. Rather than encode
numbers that go stale, `http.py` keeps a floor between requests
(`POLYMKT_MIN_INTERVAL`, default 120ms) and backs off on `429`, honouring
`Retry-After`. `4xx` is never retried — it won't get better.

Being slow is cheaper than being blocked. Raise the floor before raising
concurrency.

---

## Snapshots from cron

`moves` is only as good as the history behind it, and history only exists if
something takes snapshots. One line in crontab, every 15 minutes:

```cron
*/15 * * * * POLYMKT_DB=data/polymkt.db \
    PYTHONPATH=src /usr/bin/python3 -m polymkt snap >> /tmp/polymkt-snap.log 2>&1
```

`snap` is deliberately survivable: one dead token logs and is skipped rather
than aborting the sweep, and it exits non-zero only if *nothing* was recorded.

Two snapshots is a line, not a trend. `moves` prints the sample size next to
every change for that reason — the same discipline `revops` applies to view
counts.
