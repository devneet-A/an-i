"""Work out which session the dashboard should show.

Rules:
- A session is LIVE from its scheduled start until its scheduled end, plus an
  overrun allowance (red flags, delays) that ends early once the chequered
  flag has been shown.
- If nothing is live, show the most recent completed session.
- Separately, find the next upcoming session for the countdown.

The core logic (`pick_sessions`) is a pure function of a DataFrame and a time,
so it can be tested without any network access.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

import pandas as pd

from lib import jolpica, openf1
from lib.http import APIError
from lib.timeutils import now_utc

# Sessions often run past their scheduled end (red flags, rain delays).
OVERRUN_ALLOWANCE = timedelta(minutes=45)

# Jolpica only gives start times, so for the fallback we assume typical lengths.
_TYPICAL_LENGTH: dict[str, timedelta] = {
    "Practice 1": timedelta(minutes=60),
    "Practice 2": timedelta(minutes=60),
    "Practice 3": timedelta(minutes=60),
    "Sprint Qualifying": timedelta(minutes=45),
    "Sprint Shootout": timedelta(minutes=45),
    "Sprint": timedelta(minutes=60),
    "Qualifying": timedelta(minutes=60),
    "Race": timedelta(minutes=120),
}


@dataclass(frozen=True)
class SessionInfo:
    """Everything the header needs about one session, from either API."""

    session_key: int | None  # None when the info came from Jolpica
    session_name: str        # "Qualifying", "Sprint", "Race", ...
    session_type: str        # "Practice", "Qualifying", "Sprint Qualifying", "Race"
    meeting_name: str        # "Singapore Grand Prix"
    circuit: str
    country: str
    start: pd.Timestamp      # UTC
    end: pd.Timestamp        # UTC (scheduled)


@dataclass(frozen=True)
class SessionStatus:
    live: SessionInfo | None          # session happening right now, if any
    data_session: SessionInfo | None  # session whose data the page shows
    can_stream: bool                  # live AND we have credentials for real-time data
    next_session: SessionInfo | None
    source: str                       # "openf1" or "jolpica" (fallback)
    note: str | None = None           # anything the user should know (shown as st.info)

    @property
    def is_live(self) -> bool:
        return self.live is not None


# --------------------------------------------------------------------------
# Pure logic
# --------------------------------------------------------------------------

def pick_sessions(sessions: pd.DataFrame, now: datetime
                  ) -> tuple[pd.Series | None, pd.Series | None, pd.Series | None]:
    """Return (live, latest_completed, next) rows from a sessions table.

    `sessions` needs date_start and date_end columns (UTC datetimes).
    """
    if sessions.empty:
        return None, None, None
    df = sessions.sort_values("date_start")
    if "is_cancelled" in df.columns:
        # .ne(True) keeps False *and* missing (NaN) values: unknown = not cancelled.
        df = df[df["is_cancelled"].ne(True)]

    started = df[df["date_start"] <= now]
    in_window = started[now < started["date_end"] + OVERRUN_ALLOWANCE]
    completed = started[started["date_end"] <= now]
    upcoming = df[df["date_start"] > now]

    live = in_window.iloc[-1] if not in_window.empty else None
    latest = completed.iloc[-1] if not completed.empty else None
    nxt = upcoming.iloc[0] if not upcoming.empty else None
    return live, latest, nxt


def chequered_flag_shown(race_control: pd.DataFrame, session_type: str) -> bool:
    """Has the session finished according to race control?

    Qualifying shows a chequered flag after Q1 and Q2 too, so there we only
    accept the one tagged qualifying_phase 3.
    """
    if race_control.empty or "flag" not in race_control.columns:
        return False
    cheq = race_control[race_control["flag"] == "CHEQUERED"]
    if "Qualifying" in session_type and "qualifying_phase" in cheq.columns:
        cheq = cheq[cheq["qualifying_phase"] == 3]
    return not cheq.empty


# --------------------------------------------------------------------------
# Converting rows to SessionInfo
# --------------------------------------------------------------------------

def _from_openf1(row: pd.Series | None, meeting_names: dict[int, str]) -> SessionInfo | None:
    if row is None:
        return None
    return SessionInfo(
        session_key=int(row["session_key"]),
        session_name=str(row.get("session_name", "")),
        session_type=str(row.get("session_type", "")),
        meeting_name=meeting_names.get(int(row["meeting_key"]), str(row.get("location", ""))),
        circuit=str(row.get("circuit_short_name", "")),
        country=str(row.get("country_name", "")),
        start=row["date_start"],
        end=row["date_end"],
    )


def _from_jolpica(row: pd.Series | None) -> SessionInfo | None:
    if row is None:
        return None
    name = str(row["session"])
    return SessionInfo(
        session_key=None,
        session_name=name,
        session_type="Race" if name in ("Race", "Sprint") else name,
        meeting_name=str(row["race_name"]),
        circuit=str(row["circuit_name"]),
        country=str(row["country"]),
        start=row["start_utc"],
        end=row["end_utc"],
    )


# --------------------------------------------------------------------------
# Data loading
# --------------------------------------------------------------------------

def _openf1_sessions(year: int) -> tuple[pd.DataFrame, dict[int, str]]:
    """This year's sessions plus last year's (so January still has a "latest")
    and next year's (so December still has a "next"), with meeting names."""
    frames, names = [], {}
    for y in (year - 1, year, year + 1):
        sessions = openf1.get_sessions(year=y)
        if sessions.empty:
            continue
        frames.append(sessions)
        meetings = openf1.get_meetings(y)
        if not meetings.empty:
            names.update(dict(zip(meetings["meeting_key"].astype(int), meetings["meeting_name"])))
    if not frames:
        return pd.DataFrame(), names
    return pd.concat(frames, ignore_index=True), names


def _jolpica_sessions(year: int) -> pd.DataFrame:
    frames = [f for f in (jolpica.get_schedule(y) for y in (year - 1, year)) if not f.empty]
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames, ignore_index=True)
    df["date_start"] = df["start_utc"]
    df["end_utc"] = df["start_utc"] + df["session"].map(_TYPICAL_LENGTH).fillna(timedelta(hours=1))
    df["date_end"] = df["end_utc"]
    return df


def detect(now: datetime | None = None) -> SessionStatus:
    """Decide what to show. Raises APIError only if BOTH APIs fail."""
    now = now or now_utc()
    try:
        sessions, meeting_names = _openf1_sessions(now.year)
        if sessions.empty:
            raise APIError("OpenF1 returned no sessions.")
    except APIError as openf1_error:
        # OpenF1 can be down, or may refuse anonymous users while a session
        # is live. Jolpica's calendar is enough to drive the header.
        sched = _jolpica_sessions(now.year)
        live, latest, nxt = pick_sessions(sched, now)
        return SessionStatus(
            live=_from_jolpica(live),
            data_session=_from_jolpica(latest),
            can_stream=False,
            next_session=_from_jolpica(nxt),
            source="jolpica",
            note=f"OpenF1 is unavailable ({openf1_error}). Showing calendar info only.",
        )

    live, latest, nxt = pick_sessions(sessions, now)

    # Inside the overrun allowance, ask race control whether it's really over.
    # Only possible with credentials, since live race control is paid data.
    if live is not None and now > live["date_end"] and openf1.has_live_access():
        try:
            rc = openf1.get_race_control(int(live["session_key"]), live=True)
            if chequered_flag_shown(rc, str(live["session_type"])):
                latest, live = live, None
        except APIError:
            pass  # can't tell, so keep treating it as live

    can_stream = live is not None and openf1.has_live_access()
    note = None
    if live is not None and not can_stream:
        note = ("Real-time timing needs an OpenF1 account (see README), so the data "
                "below is from the last completed session.")
    # Without credentials we can't stream the live session, so the page shows
    # the latest completed session's data instead.
    return SessionStatus(
        live=_from_openf1(live, meeting_names),
        data_session=_from_openf1(live if can_stream else latest, meeting_names),
        can_stream=can_stream,
        next_session=_from_openf1(nxt, meeting_names),
        source="openf1",
        note=note,
    )
