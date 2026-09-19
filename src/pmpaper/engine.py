"""Replay engine: run a strategy over recorded or synthetic snapshots."""

from __future__ import annotations

import bisect
from dataclasses import dataclass, field

from .book import Fill, FillModel, Snapshot, settle
from .strategy import Strategy


@dataclass
class Result:
    strategy: str
    fills: list[Fill] = field(default_factory=list)
    pnls: list[float] = field(default_factory=list)
    wins: list[bool] = field(default_factory=list)
    entry_prices: list[float] = field(default_factory=list)
    notional: float = 0.0
    total_fees: float = 0.0
    total_slippage: float = 0.0
    windows_traded: int = 0
    signals: int = 0        # how often the strategy wanted to trade
    unfilled: int = 0       # wanted to, but the order never landed


def replay(snapshots: list[Snapshot], strategy: Strategy,
           fill_model: FillModel, *, one_trade_per_window: bool = True) -> Result:
    """Run `strategy` across `snapshots` with realistic execution.

    Each decision is made on the book at time t and filled against the book
    at t + latency, so a strategy that only looks good with instant fills
    will show that here.
    """
    if not snapshots:
        return Result(strategy=strategy.name)

    strategy.reset()
    times = [s.ts for s in snapshots]
    lat = fill_model.latency_ms / 1000.0

    # Final underlying price for each window, for settlement.
    finals: dict[float, float] = {}
    for s in snapshots:
        finals[s.window_end] = s.spot     # last write per window wins

    res = Result(strategy=strategy.name)
    traded_windows: set[float] = set()

    for i, snap in enumerate(snapshots):
        if one_trade_per_window and snap.window_start in traded_windows:
            # Still feed the snapshot through so stateful strategies keep
            # their history intact.
            strategy.on_snapshot(snap)
            continue

        intent = strategy.on_snapshot(snap)
        if intent is None:
            continue
        res.signals += 1

        j = bisect.bisect_left(times, snap.ts + lat)
        arrival = snapshots[j] if j < len(snapshots) else None
        # An order that lands after this window has resolved is not a fill.
        if arrival is not None and arrival.window_start != snap.window_start:
            arrival = None

        fill = fill_model.execute(intent.side, intent.size, snap, arrival)
        if fill is None:
            res.unfilled += 1
            continue

        final_spot = finals.get(fill.window_end)
        if final_spot is None:
            res.unfilled += 1
            continue

        pnl = settle(fill, final_spot)
        res.fills.append(fill)
        res.pnls.append(pnl)
        res.wins.append(pnl > 0)
        res.entry_prices.append(fill.price)
        res.notional += fill.price * fill.size
        res.total_fees += fill.fee
        res.total_slippage += fill.slippage * fill.size
        traded_windows.add(snap.window_start)
        res.windows_traded += 1

    return res
