"""Execution engine: books, matching, fees, risk, and the paper broker."""

from __future__ import annotations

from .book import BookState, build_book, depth_ladder, spread_bps_for
from .broker import BrokerEvent, EquityPoint, PaperBroker
from .fees import (
    DEFAULT_SCHEDULE, FeeBreakdown, FeeSchedule, borrow_charge, compute_fees,
    round_trip_cost_bps, swap_charge,
)
from .matching import MatchContext, Matcher, MatchResult
from .risk import RiskDecision, RiskEngine, RiskLimits, RiskState
from .slippage import SlippageModel, SlippageResult, walk_the_book

__all__ = [
    "BookState", "build_book", "depth_ladder", "spread_bps_for",
    "PaperBroker", "BrokerEvent", "EquityPoint",
    "FeeSchedule", "FeeBreakdown", "DEFAULT_SCHEDULE", "compute_fees",
    "swap_charge", "borrow_charge", "round_trip_cost_bps",
    "Matcher", "MatchContext", "MatchResult",
    "RiskEngine", "RiskLimits", "RiskState", "RiskDecision",
    "SlippageModel", "SlippageResult", "walk_the_book",
]
