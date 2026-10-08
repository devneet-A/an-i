"""Data for the Live page, for both live and completed sessions.

Live sessions: ONE shared `LiveFeed` per session polls OpenF1, however many
people have the page open. On Streamlit Cloud every viewer shares the app's IP
address, so per-viewer polling would hit OpenF1's rate limit (30 requests / 10s)
with just a couple of viewers. The feed fetches only rows newer than it already
has (`date>` filters) and keeps the tables small.

Completed sessions: plain cached calls, no polling.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from datetime import timedelta

import pandas as pd
import streamlit as st

from lib import openf1
from lib.http import APIError
from lib.timing import latest_per_driver  # keeps position/interval logs to 1 row per driver
from lib.timeutils import now_utc

# Re-fetch each endpoint at most this often (seconds). Timing changes every
# few seconds, weather about once a minute, the driver list almost never.
REFRESH_EVERY: dict[str, float] = {
    "position": 4, "intervals": 4, "race_control": 4, "laps": 8,
    "stints": 15, "pit": 15, "weather": 60, "drivers": 300,
}

# Re-ask for a few seconds we've already seen: a row can be published slightly
# after its timestamp, and a strict "newer than last seen" would skip it.
OVERLAP = timedelta(seconds=10)
# A lap row is created when the lap STARTS and its lap_duration is filled in
# when it ends (after the next lap's row exists). So for laps we re-ask for
# the last few minutes, which always covers the lap just completed.
LAPS_OVERLAP = timedelta(minutes=4)


@dataclass
class Snapshot:
    """Everything the Live page draws, as plain DataFrames."""

    drivers: pd.DataFrame = field(default_factory=pd.DataFrame)
    positions: pd.DataFrame = field(default_factory=pd.DataFrame)
    intervals: pd.DataFrame = field(default_factory=pd.DataFrame)
    laps: pd.DataFrame = field(default_factory=pd.DataFrame)
    stints: pd.DataFrame = field(default_factory=pd.DataFrame)
    pit: pd.DataFrame = field(default_factory=pd.DataFrame)
    race_control: pd.DataFrame = field(default_factory=pd.DataFrame)
    weather: pd.DataFrame = field(default_factory=pd.DataFrame)
    updated_at: pd.Timestamp | None = None
    errors: list[str] = field(default_factory=list)


def _merge(old: pd.DataFrame, new: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    """Append new rows; where keys repeat, the newer row wins."""
    if new.empty:
        return old
    if old.empty:
        return new
    return pd.concat([old, new], ignore_index=True).drop_duplicates(keys, keep="last")


def _max_time(df: pd.DataFrame, col: str) -> pd.Timestamp | None:
    return df[col].max() if not df.empty and col in df.columns else None


class LiveFeed:
    """Incrementally updated tables for one live session (shared by all viewers)."""

    def __init__(self, session_key: int) -> None:
        self.session_key = session_key
        self.snap = Snapshot()
        self._last_fetch: dict[str, float] = {}
        self._lock = threading.Lock()

    def _due(self, name: str) -> bool:
        return time.monotonic() - self._last_fetch.get(name, 0) >= REFRESH_EVERY[name]

    def refresh(self) -> Snapshot:
        """Fetch whatever is due. If another viewer is already refreshing,
        don't wait: return the current data and let their refresh finish."""
        if not self._lock.acquire(blocking=False):
            return self.snap
        try:
            self._refresh_due()
        finally:
            self._lock.release()
        return self.snap

    def _refresh_due(self) -> None:
        key, s = self.session_key, self.snap
        errors: list[str] = []

        def since(df: pd.DataFrame, col: str = "date", overlap: timedelta = OVERLAP):
            last = _max_time(df, col)
            return last - overlap if last is not None else None

        # Each entry: endpoint -> function that returns the updated table.
        jobs = {
            "drivers": lambda: openf1.get_drivers(key, live=True),
            "position": lambda: latest_per_driver(_merge(
                s.positions, openf1.get_positions(key, live=True, since=since(s.positions)),
                ["driver_number", "date"])),
            # The intervals log is huge (every car, every ~4s), so on the first
            # fetch we only ask for the last 2 minutes.
            "intervals": lambda: latest_per_driver(_merge(
                s.intervals,
                openf1.get_intervals(key, live=True, since=since(s.intervals)
                                     or now_utc() - timedelta(minutes=2)),
                ["driver_number", "date"])),
            "laps": lambda: _merge(
                s.laps, openf1.get_laps(key, live=True, since=since(s.laps, "date_start", LAPS_OVERLAP)),
                ["driver_number", "lap_number"]),
            "race_control": lambda: _merge(
                s.race_control, openf1.get_race_control(key, live=True, since=since(s.race_control)),
                ["date", "message"]),
            "stints": lambda: openf1.get_stints(key, live=True),
            "pit": lambda: openf1.get_pit(key, live=True),
            "weather": lambda: openf1.get_weather(key, live=True),
        }
        attr = {"position": "positions"}  # snapshot field names that differ
        for name, job in jobs.items():
            if not self._due(name):
                continue
            try:
                setattr(s, attr.get(name, name), job())
                self._last_fetch[name] = time.monotonic()
            except APIError as exc:
                errors.append(f"{name}: {exc}")
        s.errors = errors
        s.updated_at = pd.Timestamp(now_utc())


# cache_resource (not cache_data) because the feed is a long-lived object that
# must be SHARED, not copied, between viewers. max_entries drops old sessions.
@st.cache_resource(max_entries=2, ttl=6 * 60 * 60, show_spinner=False)
def get_feed(session_key: int) -> LiveFeed:
    return LiveFeed(session_key)


def load_completed(session_key: int, fresh: bool = False) -> Snapshot:
    """All tables for a finished session. `fresh=True` (just finished) uses the
    short live cache, so late corrections show up instead of being cached for hours."""
    snap = Snapshot()
    loaders = {
        "drivers": lambda: openf1.get_drivers(session_key, live=fresh),
        "positions": lambda: openf1.get_positions(session_key, live=fresh),
        "laps": lambda: openf1.get_laps(session_key, live=fresh),
        "stints": lambda: openf1.get_stints(session_key, live=fresh),
        "pit": lambda: openf1.get_pit(session_key, live=fresh),
        "race_control": lambda: openf1.get_race_control(session_key, live=fresh),
        "weather": lambda: openf1.get_weather(session_key, live=fresh),
    }
    for name, load in loaders.items():
        try:
            setattr(snap, name, load())
        except APIError as exc:
            snap.errors.append(f"{name}: {exc}")

    # Only the final gaps matter, so fetch intervals from just before the last
    # lap started rather than the whole (very large) log.
    last_lap_start = _max_time(snap.laps, "date_start")
    try:
        ivl = openf1.get_intervals(
            session_key, live=fresh,
            since=last_lap_start - timedelta(minutes=5) if last_lap_start is not None else None)
        snap.intervals = latest_per_driver(ivl)
    except APIError as exc:
        snap.errors.append(f"intervals: {exc}")
    snap.updated_at = pd.Timestamp(now_utc())
    return snap
