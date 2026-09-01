"""The honesty layer: is this edge real, or is it noise?

Near-coin-flip bets produce enormous variance, so a strategy that is
genuinely worthless will show a "profitable" run remarkably often. Roughly
1 in 6 zero-edge strategies looks up 5%+ over 100 trades. Every function
here exists to stop that from being mistaken for skill.

The primary test runs on the PnL series rather than the win rate, because
PnL already accounts for varying entry prices, sizes, and fees. The
win-rate test is reported alongside it because it is easier to reason
about, and the two should agree.
"""

from __future__ import annotations

import math
import random
import statistics
from dataclasses import dataclass
from itertools import accumulate


def inv_norm_cdf(p: float) -> float:
    """Inverse standard normal CDF (Acklam's rational approximation).

    Accurate to ~1e-9 across the range, which is far beyond what any of
    these confidence statements actually need.
    """
    if not 0.0 < p < 1.0:
        raise ValueError("p must be in (0, 1)")
    a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
         3.754408661907416e+00]
    plow, phigh = 0.02425, 1 - 0.02425
    if p < plow:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / \
               ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    if p > phigh:
        q = math.sqrt(-2 * math.log(1 - p))
        return -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / \
                ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    q = p - 0.5
    r = q * q
    return (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q / \
           (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1)


def wilson_interval(successes: int, n: int, confidence: float = 0.95
                    ) -> tuple[float, float]:
    """Wilson score interval for a proportion.

    Preferred over the normal approximation because it stays inside [0,1]
    and behaves sensibly at small n — exactly the regime where a hopeful
    trader is most likely to fool themselves.
    """
    if n == 0:
        return (0.0, 1.0)
    z = inv_norm_cdf(1 - (1 - confidence) / 2)
    phat = successes / n
    denom = 1 + z * z / n
    centre = (phat + z * z / (2 * n)) / denom
    half = z / denom * math.sqrt(phat * (1 - phat) / n + z * z / (4 * n * n))
    return (max(0.0, centre - half), min(1.0, centre + half))


def bootstrap_mean_ci(values: list[float], confidence: float = 0.95,
                      iters: int = 4000, seed: int = 12345
                      ) -> tuple[float, float]:
    """Percentile bootstrap CI for the mean. Distribution-free."""
    n = len(values)
    if n == 0:
        return (0.0, 0.0)
    if n == 1:
        return (values[0], values[0])
    rng = random.Random(seed)
    # Bound total work so large samples stay fast. The bootstrap SE of the
    # mean stabilises well before 4000 resamples, so capping iterations
    # costs precision far below the width of the interval itself.
    iters = min(iters, max(600, 2_000_000 // n))
    choices = rng.choices
    means = [sum(choices(values, k=n)) / n for _ in range(iters)]
    means.sort()
    lo_i = int((1 - confidence) / 2 * iters)
    hi_i = min(iters - 1, int((1 + confidence) / 2 * iters))
    return (means[lo_i], means[hi_i])


def required_n(values: list[float], alpha: float = 0.05, power: float = 0.80
               ) -> float:
    """Trades needed to detect the observed effect at the stated power.

    This is usually the most sobering number in the report: a real 2% edge
    on near-even bets typically needs four figures of trades before it is
    distinguishable from luck.
    """
    if len(values) < 2:
        return float("inf")
    mu = statistics.mean(values)
    sd = statistics.pstdev(values)
    if mu == 0 or sd == 0:
        return float("inf")
    za = inv_norm_cdf(1 - alpha / 2)
    zb = inv_norm_cdf(power)
    return ((za + zb) * sd / abs(mu)) ** 2


def max_drawdown(pnls: list[float]) -> float:
    """Largest peak-to-trough fall of the cumulative equity curve."""
    peak = 0.0
    equity = 0.0
    worst = 0.0
    for x in pnls:
        equity += x
        peak = max(peak, equity)
        worst = min(worst, equity - peak)
    return abs(worst)


def risk_of_ruin(pnls: list[float], bankroll: float, iters: int = 2000,
                 seed: int = 999) -> float:
    """Fraction of resampled orderings that would have busted the bankroll.

    A real edge still ruins you if the bankroll can't absorb the variance,
    so this is reported next to profitability, never instead of it.
    """
    if not pnls or bankroll <= 0:
        return 0.0
    rng = random.Random(seed)
    n = len(pnls)
    iters = min(iters, max(400, 1_000_000 // n))
    ruined = 0
    for _ in range(iters):
        # Accumulate the whole resampled path at C speed, then ask whether
        # it ever dipped below zero — equivalent to stepping one trade at a
        # time, but without the Python-level inner loop.
        path = accumulate(rng.choices(pnls, k=n))
        if min(path) <= -bankroll:
            ruined += 1
    return ruined / iters


@dataclass
class Verdict:
    n: int
    wins: int
    win_rate: float
    breakeven_rate: float          # average entry price: the bar to clear
    win_rate_ci: tuple[float, float]
    total_pnl: float
    mean_pnl: float
    pnl_ci: tuple[float, float]
    roi: float
    required_n: float
    max_drawdown: float
    risk_of_ruin: float
    significant: bool
    verdict: str
    notes: list[str]


def evaluate(pnls: list[float], entry_prices: list[float], wins: list[bool],
             notional: float, bankroll: float = 500.0,
             confidence: float = 0.95, strategies_tested: int = 1) -> Verdict:
    """Produce the honest read on a set of paper trades.

    `strategies_tested` applies a Bonferroni correction. If you tried ten
    strategies and reported the best, the bar for significance is genuinely
    higher — this makes that explicit rather than letting the winner's
    curse pass as an edge.
    """
    n = len(pnls)
    notes: list[str] = []
    if n == 0:
        return Verdict(0, 0, 0.0, 0.0, (0.0, 1.0), 0.0, 0.0, (0.0, 0.0), 0.0,
                       float("inf"), 0.0, 0.0, False, "NO TRADES",
                       ["The strategy never traded. Check its entry condition."])

    adj_conf = 1 - (1 - confidence) / max(1, strategies_tested)
    if strategies_tested > 1:
        notes.append(
            f"Corrected for {strategies_tested} strategies tested: "
            f"significance now requires {adj_conf * 100:.2f}% confidence, not "
            f"{confidence * 100:.0f}%. Testing many strategies guarantees one "
            f"looks good by chance."
        )

    wins_n = sum(1 for w in wins if w)
    win_rate = wins_n / n
    breakeven = statistics.mean(entry_prices) if entry_prices else 0.0
    total = sum(pnls)
    mean = total / n
    lo, hi = bootstrap_mean_ci(pnls, adj_conf)
    wlo, whi = wilson_interval(wins_n, n, adj_conf)
    need = required_n(pnls)
    dd = max_drawdown(pnls)
    ror = risk_of_ruin(pnls, bankroll)
    roi = (total / notional) if notional else 0.0

    significant = lo > 0
    if significant:
        head = "EDGE DETECTED"
        notes.append(
            f"Mean PnL per trade is positive with its entire {adj_conf * 100:.0f}% "
            f"interval above zero (${lo:.4f} to ${hi:.4f})."
        )
    elif hi < 0:
        head = "NEGATIVE EDGE"
        notes.append(
            f"The strategy loses money with confidence — the whole interval "
            f"sits below zero (${lo:.4f} to ${hi:.4f}). This is the expected "
            f"result for short-horizon crypto binaries after costs."
        )
    else:
        head = "NO EDGE DETECTED"
        notes.append(
            f"The confidence interval straddles zero (${lo:.4f} to ${hi:.4f}), "
            f"so the result is indistinguishable from luck at this sample size."
        )

    if not significant and math.isfinite(need) and need > n:
        notes.append(
            f"To resolve the observed effect you would need about {need:,.0f} "
            f"trades; you have {n}. At ~12 five-minute windows an hour that is "
            f"roughly {need / 12 / 24:,.0f} days of continuous trading."
        )
    if win_rate > breakeven and not significant:
        notes.append(
            f"Win rate {win_rate * 100:.1f}% does exceed the {breakeven * 100:.1f}% "
            f"break-even, but not by enough to rule out chance. This is the "
            f"single most common way traders talk themselves into a losing system."
        )
    if ror > 0.05:
        notes.append(
            f"Risk of ruin on a ${bankroll:,.0f} bankroll is {ror * 100:.1f}%. "
            f"Even a genuine edge is worthless if a normal losing streak ends "
            f"the account first."
        )
    return Verdict(n, wins_n, win_rate, breakeven, (wlo, whi), total, mean,
                   (lo, hi), roi, need, dd, ror, significant, head, notes)
