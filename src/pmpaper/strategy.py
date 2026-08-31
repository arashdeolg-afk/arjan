"""Strategies, including the one that matters: fair-value arbitrage.

A strategy sees only Snapshots — the same public data you would have live.
None of them receive the market's true fair value; that would be lookahead,
which is the most common way a backtest lies.
"""

from __future__ import annotations

from dataclasses import dataclass

from .book import Snapshot
from .market import fair_yes


@dataclass(frozen=True)
class Intent:
    side: str          # "buy" | "sell"
    size: float
    reason: str = ""


class Strategy:
    name = "base"

    def reset(self) -> None:
        pass

    def on_snapshot(self, snap: Snapshot) -> Intent | None:
        raise NotImplementedError


class AlwaysBuy(Strategy):
    """Control. Buys at the ask every window.

    Its job is to lose almost exactly the half-spread. If it doesn't, the
    fill model is wrong and every other result is worthless.
    """
    name = "always-buy"

    def __init__(self, size: float = 1.0):
        self.size = size

    def on_snapshot(self, snap: Snapshot) -> Intent | None:
        return Intent("buy", self.size, "control")


class RandomEntry(Strategy):
    """Control. Coin-flip direction — must show no edge."""
    name = "random"

    def __init__(self, size: float = 1.0, seed: int = 42):
        import random
        self.size = size
        self.rng = random.Random(seed)

    def on_snapshot(self, snap: Snapshot) -> Intent | None:
        return Intent("buy" if self.rng.random() < 0.5 else "sell",
                      self.size, "coin flip")


class Momentum(Strategy):
    """Buy when the underlying has been rising. The classic retail intuition.

    At five-minute horizons price is very close to a martingale, so this
    should find nothing and then pay the spread for the privilege.
    """
    name = "momentum"

    def __init__(self, lookback: int = 20, threshold_bps: float = 2.0,
                 size: float = 1.0):
        self.lookback = lookback
        self.threshold = threshold_bps / 10_000.0
        self.size = size
        self.history: list[float] = []

    def reset(self) -> None:
        self.history = []

    def on_snapshot(self, snap: Snapshot) -> Intent | None:
        self.history.append(snap.spot)
        if len(self.history) > self.lookback + 1:
            self.history.pop(0)
        if len(self.history) <= self.lookback:
            return None
        change = (self.history[-1] - self.history[0]) / self.history[0]
        if change > self.threshold:
            return Intent("buy", self.size, f"up {change * 10000:.1f}bps")
        if change < -self.threshold:
            return Intent("sell", self.size, f"down {change * 10000:.1f}bps")
        return None


class FairValueArb(Strategy):
    """The only strategy with a coherent theory behind it.

    Prices the binary from the live underlying and trades when the quoted
    book disagrees by more than `edge_threshold`. This is what "a fast
    algorithm" actually means on a prediction market: not forecasting
    bitcoin, but noticing the maker's quote is stale.

    It works only when your latency beats the maker's. That is the whole
    question, and this harness is built to answer it with your numbers.
    """
    name = "fair-value-arb"

    def __init__(self, vol: float = 0.50, edge_threshold: float = 0.02,
                 size: float = 1.0, min_seconds_left: float = 20.0):
        self.vol = vol
        self.edge_threshold = edge_threshold
        self.size = size
        self.min_seconds_left = min_seconds_left

    def on_snapshot(self, snap: Snapshot) -> Intent | None:
        left = snap.time_to_expiry
        # Near expiry the digital price goes vertical: a tick of underlying
        # swings it wildly, so quotes look "wrong" when they aren't.
        if left < self.min_seconds_left:
            return None
        fair = fair_yes(snap.spot, snap.strike, left, self.vol)
        if snap.yes_ask < fair - self.edge_threshold:
            return Intent("buy", self.size,
                          f"ask {snap.yes_ask:.2f} < fair {fair:.3f}")
        if snap.yes_bid > fair + self.edge_threshold:
            return Intent("sell", self.size,
                          f"bid {snap.yes_bid:.2f} > fair {fair:.3f}")
        return None


REGISTRY = {
    "always-buy": AlwaysBuy,
    "random": RandomEntry,
    "momentum": Momentum,
    "fair-value-arb": FairValueArb,
}
