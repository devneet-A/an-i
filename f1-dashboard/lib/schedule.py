"""Season calendar helpers. Pure pandas: the schedule comes from lib.jolpica."""

from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd

from lib.timeutils import IST

# Jolpica gives start times only; a session counts as done this long after it starts.
SESSION_LENGTH = timedelta(hours=2)


def add_status(schedule: pd.DataFrame, now: datetime) -> pd.DataFrame:
    """Label each session done / next / upcoming, and each round the same way.

    The "next" round is the first one with any session not yet done, so a
    weekend in progress counts as next until its race is over.
    """
    df = schedule.copy()
    done = df["start_utc"] + SESSION_LENGTH <= now
    df["status"] = "upcoming"
    df.loc[done, "status"] = "done"
    if (~done).any():
        df.loc[(~done).idxmax(), "status"] = "next"  # idxmax = first True in time order

    round_done = done.groupby(df["round"]).transform("all")
    df["round_status"] = "upcoming"
    df.loc[round_done, "round_status"] = "done"
    pending_rounds = df.loc[~round_done, "round"]
    if not pending_rounds.empty:
        df.loc[df["round"] == pending_rounds.min(), "round_status"] = "next"
    return df


def weekend_label(sessions: pd.DataFrame) -> str:
    """'10–12 Oct' (or '31 Oct – 2 Nov' across months), in IST."""
    first = sessions["start_utc"].min().tz_convert(IST)
    last = sessions["start_utc"].max().tz_convert(IST)
    if first.month == last.month:
        return f"{first.day}–{last.day} {last:%b}"
    return f"{first.day} {first:%b} – {last.day} {last:%b}"
