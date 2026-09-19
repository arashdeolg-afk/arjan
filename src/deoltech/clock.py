"""Market calendars and sessions.

Three asset classes keep three different kinds of time, and a paper engine that
ignores the difference will happily fill a stock order at 3am. Equities trade a
holiday-aware NYSE session with early closes; FX runs continuously from Sunday
17:00 ET to Friday 17:00 ET; crypto never stops.

All wall-clock reasoning happens in America/New_York because that is the
timezone every US market convention is written in. Everything crossing a module
boundary is timezone-aware UTC.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from enum import Enum
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
UTC = timezone.utc

REGULAR_OPEN = time(9, 30)
REGULAR_CLOSE = time(16, 0)
PREMARKET_OPEN = time(4, 0)
AFTERHOURS_CLOSE = time(20, 0)
EARLY_CLOSE = time(13, 0)

# FX week: opens Sunday evening, closes Friday evening, both New York time.
FX_WEEK_OPEN = (6, time(17, 0))    # Sunday=6 in Python's weekday()
FX_WEEK_CLOSE = (4, time(17, 0))   # Friday=4

# NYSE full-day closures. Kept as literal dates because the observance rules
# (Saturday holidays roll back to Friday, Sunday rolls forward to Monday, plus
# one-off closures for national days of mourning) are not worth deriving wrong.
MARKET_HOLIDAYS: frozenset[date] = frozenset(
    date(*d) for d in [
        (2024, 1, 1), (2024, 1, 15), (2024, 2, 19), (2024, 3, 29), (2024, 5, 27),
        (2024, 6, 19), (2024, 7, 4), (2024, 9, 2), (2024, 11, 28), (2024, 12, 25),
        (2025, 1, 1), (2025, 1, 9), (2025, 1, 20), (2025, 2, 17), (2025, 4, 18),
        (2025, 5, 26), (2025, 6, 19), (2025, 7, 4), (2025, 9, 1), (2025, 11, 27),
        (2025, 12, 25),
        (2026, 1, 1), (2026, 1, 19), (2026, 2, 16), (2026, 4, 3), (2026, 5, 25),
        (2026, 6, 19), (2026, 7, 3), (2026, 9, 7), (2026, 11, 26), (2026, 12, 25),
        (2027, 1, 1), (2027, 1, 18), (2027, 2, 15), (2027, 3, 26), (2027, 5, 31),
        (2027, 6, 18), (2027, 7, 5), (2027, 9, 6), (2027, 11, 25), (2027, 12, 24),
    ]
)

# 1:00pm ET closes: July 3rd, the day after Thanksgiving, Christmas Eve.
EARLY_CLOSES: frozenset[date] = frozenset(
    date(*d) for d in [
        (2024, 7, 3), (2024, 11, 29), (2024, 12, 24),
        (2025, 7, 3), (2025, 11, 28), (2025, 12, 24),
        (2026, 11, 27), (2026, 12, 24),
        (2027, 11, 26),
    ]
)


class Session(str, Enum):
    CLOSED = "closed"
    PREMARKET = "premarket"
    REGULAR = "regular"
    AFTERHOURS = "afterhours"

    @property
    def is_tradeable(self) -> bool:
        return self is not Session.CLOSED

    @property
    def is_regular(self) -> bool:
        return self is Session.REGULAR


def to_et(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(ET)


def is_business_day(d: date) -> bool:
    return d.weekday() < 5 and d not in MARKET_HOLIDAYS


def close_time_for(d: date) -> time:
    return EARLY_CLOSE if d in EARLY_CLOSES else REGULAR_CLOSE


def equity_session(dt: datetime) -> Session:
    """Which NYSE session a moment falls in, holidays and early closes included."""
    et = to_et(dt)
    if not is_business_day(et.date()):
        return Session.CLOSED
    t, close = et.time(), close_time_for(et.date())
    if t < PREMARKET_OPEN:
        return Session.CLOSED
    if t < REGULAR_OPEN:
        return Session.PREMARKET
    if t < close:
        return Session.REGULAR
    # An early close ends the day outright; there is no 1pm-to-8pm extended
    # session on a half day worth modelling.
    if et.date() in EARLY_CLOSES or t >= AFTERHOURS_CLOSE:
        return Session.CLOSED
    return Session.AFTERHOURS


def fx_session(dt: datetime) -> Session:
    """FX is one continuous session from Sunday 17:00 ET to Friday 17:00 ET."""
    et = to_et(dt)
    wd, t = et.weekday(), et.time()
    if wd == 5:                                   # Saturday
        return Session.CLOSED
    if wd == 6:                                   # Sunday
        return Session.REGULAR if t >= FX_WEEK_OPEN[1] else Session.CLOSED
    if wd == 4 and t >= FX_WEEK_CLOSE[1]:         # Friday after the bell
        return Session.CLOSED
    return Session.REGULAR


def crypto_session(dt: datetime) -> Session:
    return Session.REGULAR


def session_for(asset_class: str, dt: datetime) -> Session:
    if asset_class == "equity":
        return equity_session(dt)
    if asset_class == "fx":
        return fx_session(dt)
    return crypto_session(dt)


def next_open(asset_class: str, dt: datetime, max_days: int = 14) -> datetime | None:
    """The next moment the market is tradeable, or None if it's already open.

    Scans forward in 15-minute steps: coarse enough to be cheap, fine enough
    that every session boundary in the calendar lands exactly on a step.
    """
    if session_for(asset_class, dt).is_tradeable:
        return None
    cursor = to_et(dt).replace(second=0, microsecond=0)
    cursor -= timedelta(minutes=cursor.minute % 15)
    limit = cursor + timedelta(days=max_days)
    while cursor < limit:
        cursor += timedelta(minutes=15)
        if session_for(asset_class, cursor).is_tradeable:
            return cursor.astimezone(UTC)
    return None


def session_close(asset_class: str, dt: datetime) -> datetime | None:
    """When the current session ends — what a DAY order's expiry is pinned to."""
    et = to_et(dt)
    if asset_class == "equity":
        if not is_business_day(et.date()):
            return None
        return datetime.combine(et.date(), close_time_for(et.date()), ET).astimezone(UTC)
    if asset_class == "fx":
        # Roll forward to Friday 17:00 ET, the end of the FX trading week.
        days_ahead = (4 - et.weekday()) % 7
        end = datetime.combine(et.date() + timedelta(days=days_ahead), FX_WEEK_CLOSE[1], ET)
        if end <= et:
            end += timedelta(days=7)
        return end.astimezone(UTC)
    # Crypto has no close; a DAY order expires at 00:00 UTC, the convention
    # every major crypto venue uses for daily accounting.
    nxt = (et.astimezone(UTC) + timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0)
    return nxt


def is_rollover_time(dt: datetime) -> bool:
    """FX swap is charged once daily at 17:00 ET, the interbank value-date roll."""
    et = to_et(dt)
    return et.hour == 17 and et.minute == 0


def swap_multiplier(dt: datetime) -> int:
    """Wednesday's roll carries three days of interest to cover the weekend."""
    return 3 if to_et(dt).weekday() == 2 else 1


@dataclass(frozen=True, slots=True)
class MarketStatus:
    asset_class: str
    session: Session
    now: datetime
    opens_at: datetime | None = None
    closes_at: datetime | None = None

    @property
    def label(self) -> str:
        return {
            Session.REGULAR: "OPEN",
            Session.PREMARKET: "PRE-MARKET",
            Session.AFTERHOURS: "AFTER-HOURS",
            Session.CLOSED: "CLOSED",
        }[self.session]


def market_status(asset_class: str, dt: datetime | None = None) -> MarketStatus:
    now = dt or datetime.now(UTC)
    sess = session_for(asset_class, now)
    return MarketStatus(
        asset_class=asset_class,
        session=sess,
        now=now,
        opens_at=None if sess.is_tradeable else next_open(asset_class, now),
        closes_at=session_close(asset_class, now) if sess.is_tradeable else None,
    )
