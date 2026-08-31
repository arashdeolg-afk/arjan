"""pmpaper CLI. `python -m pmpaper --help`"""

from __future__ import annotations

import argparse
import sys
import time

from .book import FillModel
from .engine import replay
from .market import SyntheticMarket
from .stats import Verdict, evaluate
from .strategy import REGISTRY


def _rule(t: str = "") -> None:
    if t:
        print(f"\n\033[1m{t}\033[0m")
    print("-" * 70)


def _report(v: Verdict, label: str, extra: dict | None = None) -> None:
    _rule(f"RESULT — {label}")
    if v.n == 0:
        print("  No trades. The strategy's entry condition never fired.")
        for n in v.notes:
            print(f"  • {n}")
        return

    colour = {"EDGE DETECTED": "32", "NEGATIVE EDGE": "31"}.get(v.verdict, "33")
    print(f"  \033[1;{colour}m{v.verdict}\033[0m\n")
    print(f"  trades            {v.n:>12,}")
    print(f"  win rate          {v.win_rate * 100:>11.2f}%   "
          f"(need > {v.breakeven_rate * 100:.2f}% to break even)")
    print(f"  95% CI on win     {v.win_rate_ci[0] * 100:>11.2f}% – {v.win_rate_ci[1] * 100:.2f}%")
    print(f"  total pnl         {'$' + format(v.total_pnl, ',.2f'):>12}")
    print(f"  pnl per trade     {'$' + format(v.mean_pnl, ',.4f'):>12}")
    print(f"  95% CI on pnl     ${v.pnl_ci[0]:,.4f} – ${v.pnl_ci[1]:,.4f}")
    print(f"  return on stake   {v.roi * 100:>11.2f}%")
    print(f"  max drawdown      {'$' + format(v.max_drawdown, ',.2f'):>12}")
    print(f"  risk of ruin      {v.risk_of_ruin * 100:>11.1f}%")
    if extra:
        print()
        for k, val in extra.items():
            print(f"  {k:<18}{val:>12}")
    print()
    for n in v.notes:
        print(f"  • {n}")


# Generating a tick series is ~5x the cost of replaying one, and several
# checks share the same market. Cache on the parameters that define it.
_MARKETS: dict[tuple, list] = {}


def _market(mm_lag, seed, vol, spread, window_s, windows):
    key = (mm_lag, seed, vol, spread, window_s, windows)
    if key not in _MARKETS:
        _MARKETS[key] = SyntheticMarket(
            vol=vol, spread=spread, mm_lag_ms=mm_lag, window_s=window_s,
            tick_ms=100.0, seed=seed,
        ).generate(window_s * windows)[0]
    return _MARKETS[key]


def control_theory(vol: float, spread: float, window_s: float) -> float:
    """Expected PnL per trade for buying the ask at the money.

    Derived rather than hardcoded so the check stays correct if the
    window, vol, or spread changes.
    """
    import math

    from .book import TICK
    from .market import fair_yes
    fair = fair_yes(1.0, 1.0, window_s, vol)
    ask = math.ceil((fair + spread / 2) / TICK) * TICK
    return fair - ask


def _sim(strategy_name: str, *, mm_lag: float, latency: float, fee_bps: float,
         seeds: int, windows: int, vol: float, spread: float,
         threshold: float, window_s: float = 300.0):
    P, E, W, N = [], [], [], 0.0
    fees = slip = 0.0
    signals = unfilled = 0
    for s in range(1, seeds + 1):
        snaps = _market(mm_lag, s, vol, spread, window_s, windows)
        cls = REGISTRY[strategy_name]
        strat = (cls(vol=vol, edge_threshold=threshold)
                 if strategy_name == "fair-value-arb" else cls())
        r = replay(snaps, strat, FillModel(latency_ms=latency, fee_bps=fee_bps))
        P += r.pnls; E += r.entry_prices; W += r.wins; N += r.notional
        fees += r.total_fees; slip += r.total_slippage
        signals += r.signals; unfilled += r.unfilled
    v = evaluate(P, E, W, notional=N)
    return v, {"fees paid": f"${fees:,.2f}", "slippage cost": f"${slip:,.2f}",
               "signals": f"{signals:,}", "unfilled": f"{unfilled:,}"}


def cmd_sim(a) -> None:
    v, extra = _sim(a.strategy, mm_lag=a.maker_lag, latency=a.latency,
                    fee_bps=a.fee_bps, seeds=a.seeds, windows=a.windows,
                    vol=a.vol, spread=a.spread, threshold=a.threshold,
                    window_s=a.window_s)
    _report(v, f"{a.strategy} · maker lag {a.maker_lag:.0f}ms · "
               f"your latency {a.latency:.0f}ms", extra)


def cmd_validate(a) -> None:
    """Prove the harness measures correctly before you trust any result."""
    W_S = a.window_s
    print("\nHarness self-validation.")
    print("An uncalibrated measuring instrument is worse than none.\n")

    _rule("1. CONTROL — always buy, in a perfectly fair market")
    print("  Buys the ask every window, so it must lose the half-spread.")
    print("  Compared against theory on a statistical tolerance, not a flat")
    print("  one: at this sample size the estimate is itself noisy.\n")
    v, _ = _sim("always-buy", mm_lag=0, latency=0, fee_bps=0, seeds=a.seeds,
                windows=a.windows, vol=0.5, spread=0.02, threshold=0.02,
                window_s=W_S)
    theory = control_theory(0.5, 0.02, W_S)
    se = 0.5 / max(1, v.n) ** 0.5          # payoffs are bounded by +/-0.5
    sigma = abs(v.mean_pnl - theory) / se if se else 0.0
    ok1 = sigma < 3.0
    print(f"  measured {v.mean_pnl:+.4f}   theory {theory:+.4f}   "
          f"n={v.n:,}   {sigma:.2f} sigma apart")
    print(f"  {'PASS' if ok1 else 'FAIL'} — fill model charges the spread correctly")

    _rule("2. NULL — fair market, nothing stale to exploit")
    print("  The maker prices perfectly. There is no edge, so the arb must")
    print("  find nothing. This is the false-positive test.\n")
    v2, _ = _sim("fair-value-arb", mm_lag=0, latency=150, fee_bps=0,
                 seeds=a.seeds, windows=a.windows, vol=0.5, spread=0.02,
                 threshold=0.02, window_s=W_S)
    ok2 = not v2.significant
    print(f"  trades={v2.n:,}   verdict={v2.verdict}")
    print(f"  {'PASS' if ok2 else 'FAIL'} — no edge invented where none exists")

    _rule("3. RECOVERY — inject a real edge, see if it is found")
    print("  The maker now quotes off a 10-second-old price: a large,")
    print("  unambiguous mispricing. The harness must detect it.\n")
    v3, _ = _sim("fair-value-arb", mm_lag=10_000, latency=100, fee_bps=0,
                 seeds=a.seeds, windows=a.windows, vol=0.5, spread=0.02,
                 threshold=0.02, window_s=W_S)
    ok3 = v3.significant
    print(f"  trades={v3.n:,}   roi={v3.roi * 100:+.1f}%   verdict={v3.verdict}")
    print(f"  {'PASS' if ok3 else 'FAIL'} — real edge detected")

    _rule("4. SUBTLE EDGE — real, but too small to prove here")
    print("  A 2-second stale quote is still an enormous edge by market-making")
    print("  standards. Watch how much data it takes to establish.\n")
    v4, _ = _sim("fair-value-arb", mm_lag=2000, latency=100, fee_bps=0,
                 seeds=a.seeds, windows=a.windows, vol=0.5, spread=0.02,
                 threshold=0.02, window_s=W_S)
    print(f"  trades={v4.n:,}   roi={v4.roi * 100:+.1f}%   verdict={v4.verdict}")
    if v4.required_n and v4.required_n != float("inf"):
        days = v4.required_n / 12 / 24
        print(f"  needs ~{v4.required_n:,.0f} trades to prove — about {days:,.0f} days")
        print("  of continuous five-minute markets.")
    ok4 = not v4.significant
    print(f"  {'PASS' if ok4 else 'FAIL'} — refuses to call a positive ROI an edge")
    print("       on insufficient evidence")

    _rule("5. LATENCY DECAY — the edge is a race, and only a race")
    print("  Same 10-second stale quote. Only your own speed changes.\n")
    print(f"  {'your latency':>14}{'roi':>10}   verdict")
    rows = []
    for lat in (100, 1000, 5000, 10_000, 15_000):
        vv, _ = _sim("fair-value-arb", mm_lag=10_000, latency=lat, fee_bps=0,
                     seeds=a.seeds, windows=a.windows, vol=0.5, spread=0.02,
                     threshold=0.02, window_s=W_S)
        rows.append((lat, vv.roi))
        print(f"  {str(lat) + 'ms':>14}{vv.roi * 100:>9.1f}%   {vv.verdict}")
    ok5 = rows[0][1] > rows[-1][1]
    print(f"\n  {'PASS' if ok5 else 'FAIL'} — edge decays as you get slower")

    _rule("VERDICT")
    checks = [ok1, ok2, ok3, ok4, ok5]
    if all(checks):
        print("  \033[1;32mAll 5 checks passed.\033[0m The harness charges costs correctly,")
        print("  invents no edges, recovers real ones, and refuses to call a")
        print("  profitable-looking run an edge without the evidence.\n")
        print("  What this demonstrates about 5-minute crypto binaries:")
        print("  the edge is a latency race against the market maker. It exists")
        print("  only while you are faster, and it vanishes the moment you are")
        print("  not — no amount of price prediction substitutes for that.")
    else:
        print(f"  \033[1;31m{checks.count(False)} of 5 checks failed.\033[0m "
              f"Do not trust results until they pass.")
    if not all(checks):
        sys.exit(1)


def cmd_probe(a) -> None:
    """Check whether the live endpoints are reachable from this machine."""
    from . import feeds
    _rule("ENDPOINT PROBE")
    checks = [
        ("spot (binance)", lambda: feeds.fetch_spot("binance")),
        ("spot (coinbase)", lambda: feeds.fetch_spot("coinbase")),
        ("polymarket markets", lambda: len(feeds.fetch_markets(a.contains))),
    ]
    for name, fn in checks:
        try:
            print(f"  {name:<22} \033[32mok\033[0m    {fn()}")
        except Exception as exc:                       # noqa: BLE001
            print(f"  {name:<22} \033[31mfail\033[0m  {type(exc).__name__}: {exc}")
    print("\n  A failure here is usually a network policy, not a bug.")
    print("  Run this on the machine you intend to trade from.\n")


def cmd_record(a) -> None:
    """Record live book + spot to SQLite. Run this for days before trusting it."""
    from . import feeds
    from .book import Snapshot
    from .db import connect, new_run, save_snapshots

    conn = connect()
    markets = feeds.fetch_markets(a.contains)
    if not markets:
        print(f"no open markets matching {a.contains!r}", file=sys.stderr)
        return
    m = markets[0]
    print(f"recording: {m['question']}")
    run_id = new_run(conn, m["question"] or a.contains,
                     {"token": m["yes_token"], "interval": a.interval})

    started = time.time()
    strike = feeds.fetch_spot(a.spot_source)
    buf: list[Snapshot] = []
    try:
        while time.time() - started < a.duration:
            spot = feeds.fetch_spot(a.spot_source)
            book = feeds.fetch_book(m["yes_token"])
            if spot is not None and book is not None:
                bid, ask, bsz, asz = book
                now = time.time()
                buf.append(Snapshot(
                    ts=now, window_start=started, window_end=started + a.window,
                    strike=strike or spot, spot=spot,
                    yes_bid=bid, yes_ask=ask, yes_bid_size=bsz, yes_ask_size=asz))
            if len(buf) >= 100:
                save_snapshots(conn, run_id, buf, m["yes_token"]); buf.clear()
                print(f"  {int(time.time() - started)}s elapsed", end="\r")
            time.sleep(a.interval)
    except KeyboardInterrupt:
        print("\n  stopped")
    finally:
        if buf:
            save_snapshots(conn, run_id, buf, m["yes_token"])
        n = conn.execute("SELECT COUNT(*) c FROM snapshots WHERE run_id=?",
                         (run_id,)).fetchone()["c"]
        print(f"\nrun {run_id}: {n:,} snapshots recorded")
        conn.close()


def cmd_replay(a) -> None:
    from .db import connect, load_snapshots
    conn = connect()
    snaps = load_snapshots(conn, a.run)
    if not snaps:
        print(f"run {a.run} has no snapshots", file=sys.stderr)
        return
    cls = REGISTRY[a.strategy]
    strat = cls(vol=a.vol, edge_threshold=a.threshold) \
        if a.strategy == "fair-value-arb" else cls()
    r = replay(snaps, strat, FillModel(latency_ms=a.latency, fee_bps=a.fee_bps))
    v = evaluate(r.pnls, r.entry_prices, r.wins, notional=r.notional,
                 strategies_tested=a.strategies_tested)
    _report(v, f"{a.strategy} on recorded run {a.run}",
            {"fees paid": f"${r.total_fees:,.2f}",
             "slippage cost": f"${r.total_slippage:,.2f}",
             "signals": f"{r.signals:,}", "unfilled": f"{r.unfilled:,}"})
    conn.close()


def cmd_runs(a) -> None:
    from .db import connect, list_runs
    conn = connect()
    rows = list_runs(conn)
    if not rows:
        print("no recorded runs yet — `pmpaper record`")
        return
    _rule("RECORDED RUNS")
    for r in rows:
        print(f"  {r['id']:>4}  {r['started_at']:<22}{r['snaps']:>9,} snaps  "
              f"{(r['label'] or '')[:34]}")
    conn.close()


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="pmpaper",
        description="Paper-trading harness for Polymarket binary markets. "
                    "Measures whether an edge survives spread, latency and fees.")
    sub = p.add_subparsers(dest="cmd", required=True)

    v = sub.add_parser("validate", help="prove the harness measures correctly")
    v.add_argument("--seeds", type=int, default=4)
    v.add_argument("--windows", type=int, default=250)
    v.add_argument("--window-s", type=float, default=120.0,
                   help="binary window length; shorter runs faster and the "
                        "mechanics are identical")
    v.set_defaults(fn=cmd_validate)

    s = sub.add_parser("sim", help="run a strategy on synthetic data")
    s.add_argument("strategy", choices=sorted(REGISTRY))
    s.add_argument("--maker-lag", type=float, default=0.0,
                   help="ms the maker's quote is stale (0 = perfectly fair market)")
    s.add_argument("--latency", type=float, default=150.0,
                   help="your round-trip latency in ms")
    s.add_argument("--fee-bps", type=float, default=0.0)
    s.add_argument("--seeds", type=int, default=4)
    s.add_argument("--windows", type=int, default=300)
    s.add_argument("--vol", type=float, default=0.50, help="annualised vol")
    s.add_argument("--spread", type=float, default=0.02)
    s.add_argument("--threshold", type=float, default=0.02,
                   help="min mispricing before the arb trades")
    s.add_argument("--window-s", type=float, default=300.0,
                   help="binary window length in seconds")
    s.set_defaults(fn=cmd_sim)

    pr = sub.add_parser("probe", help="check live endpoints from this machine")
    pr.add_argument("--contains", default="bitcoin")
    pr.set_defaults(fn=cmd_probe)

    rec = sub.add_parser("record", help="record live book + spot to SQLite")
    rec.add_argument("--contains", default="bitcoin")
    rec.add_argument("--duration", type=float, default=3600)
    rec.add_argument("--interval", type=float, default=1.0)
    rec.add_argument("--window", type=float, default=300)
    rec.add_argument("--spot-source", default="binance",
                     choices=["binance", "coinbase"])
    rec.set_defaults(fn=cmd_record)

    rp = sub.add_parser("replay", help="replay a recorded run through a strategy")
    rp.add_argument("run", type=int)
    rp.add_argument("strategy", choices=sorted(REGISTRY))
    rp.add_argument("--latency", type=float, default=150.0)
    rp.add_argument("--fee-bps", type=float, default=0.0)
    rp.add_argument("--vol", type=float, default=0.50)
    rp.add_argument("--threshold", type=float, default=0.02)
    rp.add_argument("--strategies-tested", type=int, default=1,
                    help="how many strategies you tried; corrects for the winner's curse")
    rp.set_defaults(fn=cmd_replay)

    r = sub.add_parser("runs", help="list recorded runs")
    r.set_defaults(fn=cmd_runs)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    args.fn(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
