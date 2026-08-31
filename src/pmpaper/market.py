"""A synthetic BTC up/down market with a controllable, known edge.

This exists so the harness can be validated. Against live data you can
never check whether a measured edge is real — you don't know the truth.
Here you set the truth, then confirm the harness recovers it:

  * mm_lag_ms = 0   -> the maker quotes fair value. There is NO edge, and
                       a correct harness must report none.
  * mm_lag_ms > 0   -> the maker quotes off a stale price. An edge EXISTS,
                       but only for a trader whose own latency is lower.

That second case is the real question about 5-minute crypto binaries: the
edge is not "can I predict bitcoin", it is "am I faster than the maker".
"""

from __future__ import annotations

import math
import random

from .book import MAX_PRICE, MIN_PRICE, TICK, Snapshot

SECONDS_PER_YEAR = 365.0 * 24.0 * 3600.0


def norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def fair_yes(spot: float, strike: float, seconds_left: float, vol: float) -> float:
    """P(S_T > K) for geometric Brownian motion with zero drift.

    This is the digital-option price: Phi(d2). At 5-minute horizons the
    drift term is ~1000x smaller than the diffusion term, so leaving it out
    changes the answer by far less than one price tick.
    """
    if seconds_left <= 0:
        return 1.0 if spot > strike else 0.0
    tau = seconds_left / SECONDS_PER_YEAR
    denom = vol * math.sqrt(tau)
    if denom <= 0:
        return 1.0 if spot > strike else 0.0
    d2 = (math.log(spot / strike) - 0.5 * vol * vol * tau) / denom
    return norm_cdf(d2)


class SyntheticMarket:
    """Generates a tick series of underlying prices and maker quotes."""

    def __init__(self, *, vol: float = 0.50, drift: float = 0.0,
                 spot0: float = 60_000.0, window_s: float = 300.0,
                 spread: float = 0.02, mm_lag_ms: float = 0.0,
                 tick_ms: float = 100.0, seed: int = 1):
        if tick_ms <= 0:
            raise ValueError("tick_ms must be positive")
        self.vol = vol
        self.drift = drift
        self.spot0 = spot0
        self.window_s = window_s
        self.spread = spread
        self.mm_lag_ms = mm_lag_ms
        self.tick_ms = tick_ms
        self.rng = random.Random(seed)

    def _quote(self, fair: float) -> tuple[float, float]:
        """Symmetric two-sided quote around fair, snapped to the cent grid."""
        half = self.spread / 2.0
        bid = math.floor((fair - half) / TICK) * TICK
        ask = math.ceil((fair + half) / TICK) * TICK
        bid = min(max(bid, MIN_PRICE), MAX_PRICE)
        ask = min(max(ask, MIN_PRICE), MAX_PRICE)
        # Deep in/out of the money both sides clamp to the same bound, which
        # would lock the book. Widen away from whichever bound was hit.
        if ask <= bid:
            if bid + TICK <= MAX_PRICE:
                ask = bid + TICK
            else:
                ask = MAX_PRICE
                bid = MAX_PRICE - TICK
        return round(bid, 4), round(ask, 4)

    def generate(self, duration_s: float) -> tuple[list[Snapshot], list[float]]:
        """Return (snapshots, true_fair_values).

        The truth series is returned separately and never reaches a
        strategy — it exists only so tests can build an oracle.
        """
        dt = self.tick_ms / 1000.0
        dt_years = dt / SECONDS_PER_YEAR
        n = int(duration_s / dt)
        lag_ticks = int(round(self.mm_lag_ms / self.tick_ms))

        spots: list[float] = [self.spot0]
        s = self.spot0
        for _ in range(n):
            z = self.rng.gauss(0.0, 1.0)
            s *= math.exp((self.drift - 0.5 * self.vol ** 2) * dt_years
                          + self.vol * math.sqrt(dt_years) * z)
            spots.append(s)

        snaps: list[Snapshot] = []
        truth: list[float] = []
        strike = spots[0]
        w_start = 0.0
        for i in range(n + 1):
            t = i * dt
            if t >= w_start + self.window_s:
                w_start += self.window_s
                strike = spots[i]
            w_end = w_start + self.window_s
            left = w_end - t

            true_fair = fair_yes(spots[i], strike, left, self.vol)
            # The maker prices off what it last saw, which may be stale.
            seen_spot = spots[max(0, i - lag_ticks)]
            quote_fair = fair_yes(seen_spot, strike, left, self.vol)
            bid, ask = self._quote(quote_fair)

            snaps.append(Snapshot(
                ts=t, window_start=w_start, window_end=w_end, strike=strike,
                spot=spots[i], yes_bid=bid, yes_ask=ask,
            ))
            truth.append(true_fair)
        return snaps, truth
