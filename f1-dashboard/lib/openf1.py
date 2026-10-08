"""OpenF1 API client: https://openf1.org

Every public function returns a pandas DataFrame (possibly empty) and raises
lib.http.APIError on failure, so pages only need one try/except.

Field names are kept exactly as OpenF1 documents them (they are already clean
snake_case) so you can cross-check against the docs. We only fix types: date
strings become timezone-aware datetimes and team colours get a leading "#".
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pandas as pd
import streamlit as st

from lib.http import APIError, AuthRequiredError, Throttle, build_session, get_json

BASE_URL = "https://api.openf1.org/v1"
TOKEN_URL = "https://api.openf1.org/token"

# OpenF1's server allows 30 requests per 10 seconds per IP. 2.5/s keeps us
# safely below that even when several pages load at once.
_session = build_session("f1-dashboard (streamlit)")
_throttle = Throttle(max_per_second=2.5)

# Cache lifetimes (seconds). Historical data never changes, live data changes
# every few seconds.
STATIC_TTL = 6 * 60 * 60
LIVE_TTL = 4

# Columns that hold ISO-8601 timestamps in OpenF1 responses.
_DATE_COLUMNS = ("date", "date_start", "date_end")

# A query filter is a (key, value) pair. Using a tuple of tuples (instead of
# a dict) lets us repeat a key, e.g. driver_number=1 & driver_number=44, and
# keeps it hashable so st.cache_data can use it as a cache key.
Params = tuple[tuple[str, str], ...]
SessionKey = int | str  # an int, or the special string "latest"


# --------------------------------------------------------------------------
# Authentication (optional, only needed for real-time data)
# --------------------------------------------------------------------------

def _secret(name: str) -> str:
    """Read a value from st.secrets, returning "" if it (or the file) is missing."""
    try:
        return str(st.secrets.get(name, "") or "")
    except Exception:  # No secrets.toml at all raises, we treat it as "not set".
        return ""


@st.cache_data(ttl=50 * 60, show_spinner=False)  # tokens last 60 min; renew early
def _fetch_token(username: str, password: str) -> str:
    """Swap username/password for an OAuth2 access token."""
    _throttle.wait()
    resp = _session.post(
        TOKEN_URL,
        data={"username": username, "password": password},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=(5, 15),
    )
    if not resp.ok:
        raise AuthRequiredError("OpenF1 login failed. Check OPENF1_USERNAME / OPENF1_PASSWORD.")
    return str(resp.json()["access_token"])


def _auth_headers() -> dict[str, str]:
    """Bearer header if credentials are configured, otherwise no header."""
    token = _secret("OPENF1_API_KEY")
    username, password = _secret("OPENF1_USERNAME"), _secret("OPENF1_PASSWORD")
    if username and password:
        try:
            token = _fetch_token(username, password)
        except Exception:
            # Bad login or network blip: fall back to anonymous access so
            # historical data still works.
            return {}
    return {"Authorization": f"Bearer {token}"} if token else {}


def has_live_access() -> bool:
    """True when credentials are configured (and, for a login, accepted)."""
    return bool(_auth_headers())


# --------------------------------------------------------------------------
# Low-level fetch + DataFrame cleaning
# --------------------------------------------------------------------------

def _filter(field: str, op: str, value: Any) -> tuple[str, str]:
    """Build a comparison filter such as date>2024-05-01T13:00:00+00:00.

    OpenF1 rebuilds each filter as "key=value". Passing "date>" as the key
    would therefore turn into "date>=" on the server. Putting the whole
    expression in the key with an empty value keeps the operator exact.
    """
    if isinstance(value, datetime):
        value = value.isoformat()
    return (f"{field}{op}{value}", "")


def _clean(records: list[dict[str, Any]]) -> pd.DataFrame:
    """Turn raw JSON records into a typed DataFrame."""
    df = pd.DataFrame.from_records(records)
    if df.empty:
        return df
    for col in _DATE_COLUMNS:
        if col in df.columns:
            # format="ISO8601" copes with OpenF1 mixing timestamps with and
            # without fractional seconds in one response.
            df[col] = pd.to_datetime(df[col], utc=True, format="ISO8601", errors="coerce")
    return df


def _fetch(endpoint: str, params: Params) -> pd.DataFrame:
    data = get_json(_session, _throttle, f"{BASE_URL}/{endpoint}", params=list(params),
                    headers=_auth_headers())
    if isinstance(data, dict):
        # Errors/empty results come back as {"detail": "..."} instead of a list.
        detail = str(data.get("detail", ""))
        if "no results" in detail.lower() or not detail:
            return pd.DataFrame()
        raise APIError(f"OpenF1: {detail}")
    return _clean(data)


# Two cached wrappers around the same fetch, differing only in TTL.
# st.cache_data hashes the arguments, so each distinct query is cached
# separately and identical queries from different users share one call.
@st.cache_data(ttl=STATIC_TTL, show_spinner=False)
def _fetch_static(endpoint: str, params: Params) -> pd.DataFrame:
    return _fetch(endpoint, params)


@st.cache_data(ttl=LIVE_TTL, show_spinner=False)
def _fetch_live(endpoint: str, params: Params) -> pd.DataFrame:
    return _fetch(endpoint, params)


def _query(endpoint: str, params: list[tuple[str, Any]], live: bool) -> pd.DataFrame:
    """Normalise params to strings and dispatch to the right cache."""
    clean: Params = tuple((k, str(v)) for k, v in params if v is not None)
    return (_fetch_live if live else _fetch_static)(endpoint, clean)


def _session_params(session_key: SessionKey, driver_numbers: list[int] | None,
                    since: datetime | None, date_field: str = "date") -> list[tuple[str, Any]]:
    params: list[tuple[str, Any]] = [("session_key", session_key)]
    params += [("driver_number", n) for n in (driver_numbers or [])]
    if since is not None:
        params.append(_filter(date_field, ">", since))  # only rows newer than we have
    return params


# --------------------------------------------------------------------------
# Calendar-ish endpoints
# --------------------------------------------------------------------------

def get_meetings(year: int) -> pd.DataFrame:
    """All Grand Prix weekends (and tests) of a season."""
    df = _query("meetings", [("year", year)], live=False)
    return df.sort_values("date_start").reset_index(drop=True) if not df.empty else df


def get_sessions(year: int | None = None, meeting_key: SessionKey | None = None,
                 live: bool = False) -> pd.DataFrame:
    """Sessions (FP1, Qualifying, Race...) filtered by year and/or meeting."""
    df = _query("sessions", [("year", year), ("meeting_key", meeting_key)], live=live)
    return df.sort_values("date_start").reset_index(drop=True) if not df.empty else df


def get_session(session_key: SessionKey, live: bool = False) -> pd.DataFrame:
    """A single session; pass "latest" for the current/most recent one."""
    return _query("sessions", [("session_key", session_key)], live=live)


# --------------------------------------------------------------------------
# Per-session endpoints
# --------------------------------------------------------------------------

def get_drivers(session_key: SessionKey, live: bool = False) -> pd.DataFrame:
    """Drivers in a session: number, acronym, name, team, team_colour, headshot."""
    df = _query("drivers", [("session_key", session_key)], live=live)
    if df.empty:
        return df
    # The feed can repeat a driver, sometimes with blank fields. groupby().last()
    # keeps the most recent *non-empty* value of each column per driver.
    df = df.groupby("driver_number", as_index=False).last()
    # API gives "3671C6"; Plotly wants "#3671C6". Unknown -> neutral grey.
    df["team_colour"] = "#" + df["team_colour"].fillna("888888").astype(str).str.lstrip("#")
    return df


def get_laps(session_key: SessionKey, driver_numbers: list[int] | None = None,
             live: bool = False, since: datetime | None = None) -> pd.DataFrame:
    """Lap-by-lap timing (lap_duration, sectors, speed traps).

    `since` filters on date_start (laps have no "date" column).
    """
    return _query("laps", _session_params(session_key, driver_numbers, since, "date_start"),
                  live=live)


def get_positions(session_key: SessionKey, live: bool = False,
                  since: datetime | None = None) -> pd.DataFrame:
    """Every position change. Use `since` during live sessions to fetch only new rows."""
    return _query("position", _session_params(session_key, None, since), live=live)


def get_intervals(session_key: SessionKey, live: bool = False,
                  since: datetime | None = None) -> pd.DataFrame:
    """gap_to_leader / interval (races only). Values are seconds, or text like "+1 LAP"."""
    return _query("intervals", _session_params(session_key, None, since), live=live)


def get_pit(session_key: SessionKey, live: bool = False) -> pd.DataFrame:
    return _query("pit", [("session_key", session_key)], live=live)


def get_stints(session_key: SessionKey, live: bool = False) -> pd.DataFrame:
    """Tyre stints: compound, lap_start, lap_end, tyre_age_at_start."""
    return _query("stints", [("session_key", session_key)], live=live)


def get_weather(session_key: SessionKey, live: bool = False) -> pd.DataFrame:
    df = _query("weather", [("session_key", session_key)], live=live)
    return df.sort_values("date").reset_index(drop=True) if not df.empty else df


def get_race_control(session_key: SessionKey, live: bool = False,
                     since: datetime | None = None) -> pd.DataFrame:
    """Flags, safety car, penalties, track limits..."""
    df = _query("race_control", _session_params(session_key, None, since), live=live)
    return df.sort_values("date").reset_index(drop=True) if not df.empty else df


def get_team_radio(session_key: SessionKey, live: bool = False) -> pd.DataFrame:
    """Radio clip URLs. Often empty: F1 publishes little radio since 2026."""
    return _query("team_radio", [("session_key", session_key)], live=live)


def get_session_result(session_key: SessionKey) -> pd.DataFrame:
    return _query("session_result", [("session_key", session_key)], live=False)


def get_starting_grid(session_key: SessionKey) -> pd.DataFrame:
    return _query("starting_grid", [("session_key", session_key)], live=False)


# --------------------------------------------------------------------------
# Telemetry (~3.7 samples/second per car, so always narrow the time window)
# --------------------------------------------------------------------------

def _window_params(session_key: SessionKey, driver_number: int,
                   start: datetime, end: datetime) -> list[tuple[str, Any]]:
    return [("session_key", session_key), ("driver_number", driver_number),
            _filter("date", ">=", start), _filter("date", "<=", end)]


def get_car_data(session_key: SessionKey, driver_number: int,
                 start: datetime, end: datetime) -> pd.DataFrame:
    """speed, throttle, brake, n_gear, rpm, drs for one car between two times."""
    return _query("car_data", _window_params(session_key, driver_number, start, end), live=False)


def get_location(session_key: SessionKey, driver_number: int,
                 start: datetime, end: datetime) -> pd.DataFrame:
    """x, y, z track position for one car between two times."""
    return _query("location", _window_params(session_key, driver_number, start, end), live=False)
