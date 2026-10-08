"""Jolpica F1 client (Ergast-compatible): https://github.com/jolpica/jolpica-f1

Used for the season calendar, championship standings and race results.
Ergast returns everything as strings inside deeply nested JSON, so each
function flattens that into a typed DataFrame with snake_case columns.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
import streamlit as st

from lib.http import Throttle, build_session, get_json

BASE_URL = "https://api.jolpi.ca/ergast/f1"

# Jolpica allows 4 requests/second and 500/hour without a token. Caching
# (below) is what keeps us under the hourly limit.
_session = build_session("f1-dashboard (streamlit)")
_throttle = Throttle(max_per_second=3)

STATIC_TTL = 3 * 60 * 60  # standings/calendar only change after a session ends
PAGE_SIZE = 100           # the API's maximum page size

# Ergast's names for each session object on a race, and our labels.
_SESSION_FIELDS: dict[str, str] = {
    "FirstPractice": "Practice 1",
    "SecondPractice": "Practice 2",
    "ThirdPractice": "Practice 3",
    "SprintQualifying": "Sprint Qualifying",
    "SprintShootout": "Sprint Shootout",  # 2023 name for sprint qualifying
    "Sprint": "Sprint",
    "Qualifying": "Qualifying",
}


def _get(path: str, offset: int = 0) -> dict[str, Any]:
    """Fetch one page and return the inner "MRData" object."""
    data = get_json(_session, _throttle, f"{BASE_URL}/{path}.json",
                    params={"limit": PAGE_SIZE, "offset": offset})
    return data.get("MRData", {}) if isinstance(data, dict) else {}


def _get_all_races(path: str) -> list[dict[str, Any]]:
    """Follow pagination for endpoints that return a RaceTable.

    Pages count result rows, not races, so one race's results can be split
    across two pages. We merge those back together by round number.
    """
    races: dict[str, dict[str, Any]] = {}
    offset, total = 0, 1
    while offset < total:
        mr = _get(path, offset)
        total = int(mr.get("total", 0))
        for race in mr.get("RaceTable", {}).get("Races", []):
            key = race["round"]
            if key in races:
                for list_key in ("Results", "SprintResults"):
                    races[key].setdefault(list_key, []).extend(race.get(list_key, []))
            else:
                races[key] = race
        offset += PAGE_SIZE
    return list(races.values())


def _utc(date: str | None, time: str | None) -> pd.Timestamp:
    """Ergast splits date and time ("2025-03-16", "04:00:00Z"); join them as UTC."""
    if not date:
        return pd.NaT
    return pd.to_datetime(f"{date}T{time or '00:00:00Z'}", utc=True)


@st.cache_data(ttl=STATIC_TTL, show_spinner=False)
def get_schedule(season: int | str = "current") -> pd.DataFrame:
    """One row per session (FP1 ... Race) for every round of a season, in UTC."""
    rows: list[dict[str, Any]] = []
    for race in _get_all_races(f"{season}/races"):
        circuit = race.get("Circuit", {})
        base = {
            "season": int(race["season"]),
            "round": int(race["round"]),
            "race_name": race["raceName"],
            "circuit_name": circuit.get("circuitName", ""),
            "locality": circuit.get("Location", {}).get("locality", ""),
            "country": circuit.get("Location", {}).get("country", ""),
        }
        for field, label in _SESSION_FIELDS.items():
            if field in race:
                s = race[field]
                rows.append({**base, "session": label, "start_utc": _utc(s.get("date"), s.get("time"))})
        rows.append({**base, "session": "Race", "start_utc": _utc(race.get("date"), race.get("time"))})
    df = pd.DataFrame(rows)
    return df.sort_values("start_utc").reset_index(drop=True) if not df.empty else df


@st.cache_data(ttl=STATIC_TTL, show_spinner=False)
def get_driver_standings(season: int | str = "current", round_: int | None = None) -> pd.DataFrame:
    """Drivers' championship after a given round (latest round if None)."""
    path = f"{season}/{round_}/driverstandings" if round_ else f"{season}/driverstandings"
    lists = _get(path).get("StandingsTable", {}).get("StandingsLists", [])
    rows = []
    for lst in lists:
        for s in lst.get("DriverStandings", []):
            d = s["Driver"]
            teams = s.get("Constructors", [])
            rows.append({
                "round": int(lst["round"]),
                # "position" is missing for drivers who were excluded/DSQ'd.
                "position": int(s["position"]) if s.get("position") else None,
                "driver_id": d["driverId"],
                "code": d.get("code", d["familyName"][:3].upper()),
                "driver": f'{d["givenName"]} {d["familyName"]}',
                "number": d.get("permanentNumber"),
                "team": teams[-1]["name"] if teams else "",  # current team = last listed
                "points": float(s["points"]),
                "wins": int(s["wins"]),
            })
    return pd.DataFrame(rows)


@st.cache_data(ttl=STATIC_TTL, show_spinner=False)
def get_constructor_standings(season: int | str = "current", round_: int | None = None) -> pd.DataFrame:
    """Constructors' championship after a given round (latest round if None)."""
    path = f"{season}/{round_}/constructorstandings" if round_ else f"{season}/constructorstandings"
    lists = _get(path).get("StandingsTable", {}).get("StandingsLists", [])
    rows = []
    for lst in lists:
        for s in lst.get("ConstructorStandings", []):
            rows.append({
                "round": int(lst["round"]),
                "position": int(s["position"]) if s.get("position") else None,
                "constructor_id": s["Constructor"]["constructorId"],
                "team": s["Constructor"]["name"],
                "points": float(s["points"]),
                "wins": int(s["wins"]),
            })
    return pd.DataFrame(rows)


@st.cache_data(ttl=STATIC_TTL, show_spinner=False)
def get_points_by_round(season: int | str = "current") -> pd.DataFrame:
    """Points each driver scored per round (Grand Prix + Sprint combined).

    Two paginated calls for the whole season, instead of one standings call
    per round, keeps us well inside Jolpica's hourly limit.
    """
    rows: list[dict[str, Any]] = []
    for path, key in ((f"{season}/results", "Results"), (f"{season}/sprint", "SprintResults")):
        for race in _get_all_races(path):
            for r in race.get(key, []):
                d = r["Driver"]
                rows.append({
                    "round": int(race["round"]),
                    "race_name": race["raceName"],
                    "driver_id": d["driverId"],
                    "code": d.get("code", d["familyName"][:3].upper()),
                    "team": r["Constructor"]["name"],
                    "points": float(r["points"]),
                })
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    return (df.groupby(["round", "race_name", "driver_id", "code", "team"], as_index=False)["points"]
              .sum().sort_values(["round", "points"], ascending=[True, False])
              .reset_index(drop=True))
