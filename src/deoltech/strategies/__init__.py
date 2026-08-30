"""Strategy framework and the built-in library."""

from __future__ import annotations

from . import indicators
from .base import REGISTRY, Strategy, StrategyContext, available, get, register
from .library import (
    BollingerBreakout, BuyAndHold, DonchianBreakout, MeanReversion, RsiPullback,
    SmaCrossover,
)

__all__ = [
    "Strategy", "StrategyContext", "register", "get", "available", "REGISTRY",
    "indicators", "BuyAndHold", "SmaCrossover", "DonchianBreakout",
    "MeanReversion", "RsiPullback", "BollingerBreakout",
]
