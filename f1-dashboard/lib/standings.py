"""Standings helpers: team colours for Jolpica data, gaps and cumulative points.

Jolpica (standings) has no team colours and uses different team names from
OpenF1 ("Red Bull" vs "Red Bull Racing"). Driver codes like "VER" are the same
in both, so we match on those instead of keeping a hand-written team list.
"""

from __future__ import annotations

import pandas as pd

from lib import openf1
from lib.http import APIError
from lib.timeutils import now_utc

FALLBACK_COLOUR = "#888888"


def driver_colours(year: int) -> dict[str, str]:
    """Driver code -> team colour, from the season's most recent OpenF1 session.
    Returns {} if OpenF1 is unavailable; callers fall back to grey."""
    try:
        sessions = openf1.get_sessions(year=year)
        if sessions.empty:
            return {}
        done = sessions[sessions["date_end"] <= now_utc()]
        if done.empty:
            return {}
        drivers = openf1.get_drivers(int(done.iloc[-1]["session_key"]))
    except APIError:
        return {}
    if drivers.empty:
        return {}
    return dict(zip(drivers["name_acronym"], drivers["team_colour"]))


def team_colours(df: pd.DataFrame, by_driver: dict[str, str]) -> dict[str, str]:
    """Team name (Jolpica's) -> colour, borrowed from any of its drivers.
    `df` needs `code` and `team` columns (driver standings or points by round)."""
    colours: dict[str, str] = {}
    for team, code in zip(df["team"], df["code"]):
        if team not in colours and code in by_driver:
            colours[team] = by_driver[code]
    return colours


def colour_for_driver(code: str, team: str, by_driver: dict[str, str],
                      by_team: dict[str, str]) -> str:
    """Own colour if known; else the team's (a driver who left mid-season
    isn't in the latest session); else grey."""
    return by_driver.get(code) or by_team.get(team) or FALLBACK_COLOUR


def with_gap(standings: pd.DataFrame) -> pd.DataFrame:
    """Add points behind the championship leader."""
    df = standings.sort_values("position", na_position="last").reset_index(drop=True)
    df["gap"] = df["points"].max() - df["points"]
    return df


def cumulative_points(points: pd.DataFrame, by: str) -> pd.DataFrame:
    """Running points total after every round, per driver (`by="code"`) or team.

    Rounds where someone scored nothing still get a row, so every line is
    continuous and they all end on the latest round.
    """
    per_round = points.groupby(["round", by], as_index=False)["points"].sum()
    wide = per_round.pivot(index="round", columns=by, values="points").fillna(0).cumsum()
    long = wide.reset_index().melt(id_vars="round", var_name=by, value_name="total")
    names = points.drop_duplicates("round").set_index("round")["race_name"]
    long["race_name"] = long["round"].map(names)
    return long.sort_values(["round", "total"], ascending=[True, False]).reset_index(drop=True)
