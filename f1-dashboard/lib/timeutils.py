"""Time helpers. All API times are UTC; everything shown to users is IST."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pandas as pd

IST = ZoneInfo("Asia/Kolkata")


def now_utc() -> datetime:
    """Current time, timezone-aware. Comparing aware with naive datetimes raises."""
    return datetime.now(timezone.utc)


def to_ist(ts: datetime | pd.Timestamp) -> datetime:
    return pd.Timestamp(ts).tz_convert(IST).to_pydatetime()


def format_ist(ts: datetime | pd.Timestamp | None) -> str:
    """e.g. 'Sun 12 Oct, 17:30 IST'."""
    if ts is None or pd.isna(ts):
        return "TBC"
    return to_ist(ts).strftime("%a %d %b, %H:%M IST")


def format_countdown(delta: timedelta) -> str:
    """Compact countdown: '2d 4h 13m', '4h 13m', '13m'. Minute precision is
    enough for a header and lets us refresh it only every 30 seconds."""
    total_minutes = max(0, int(delta.total_seconds() // 60))
    days, rem = divmod(total_minutes, 24 * 60)
    hours, minutes = divmod(rem, 60)
    if days:
        return f"{days}d {hours}h {minutes}m"
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m" if minutes else "< 1m"
