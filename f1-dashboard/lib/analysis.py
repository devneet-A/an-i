"""Calculations behind the Analysis page charts. Pure pandas, no API calls.

Positions and gaps per lap are worked out from lap END times (when each car
crossed the line), the same way a "race trace" is built. That needs only the
laps table (~1,200 rows for a race) instead of the position/interval feeds,
which hold tens of thousands of rows per race.
"""

from __future__ import annotations

import pandas as pd

Styles = dict[int, dict[str, str]]  # driver_number -> colour, dash, code, team

# Laps slower than this multiple of a driver's median lap are treated as
# "slow" (safety car, pit in/out, crashes) and can be hidden from lap charts.
SLOW_LAP_FACTOR = 1.07


def driver_styles(drivers: pd.DataFrame) -> Styles:
    """Colour + dash per driver. Teammates share a team colour, so the second
    driver of each team gets a dashed line: identity never relies on colour alone."""
    styles: Styles = {}
    for _, team in drivers.sort_values("driver_number").groupby("team_name", sort=False):
        for i, (_, d) in enumerate(team.iterrows()):
            styles[int(d["driver_number"])] = {
                "colour": str(d["team_colour"]),
                "dash": "solid" if i == 0 else "dash",
                "code": str(d["name_acronym"]),
                "team": str(d["team_name"]),
            }
    return styles


def lap_end_times(laps: pd.DataFrame) -> pd.DataFrame:
    """Add `lap_end` (UTC time the car finished each lap).

    Normally that's date_start + lap_duration. When a lap has no duration
    (e.g. deleted timing, pit lane) the next lap's start time is the same moment.
    """
    df = laps.sort_values(["driver_number", "lap_number"]).copy()
    end = df["date_start"] + pd.to_timedelta(df["lap_duration"], unit="s")
    next_start = df.groupby("driver_number")["date_start"].shift(-1)
    df["lap_end"] = end.fillna(next_start)
    return df


def positions_by_lap(laps: pd.DataFrame) -> pd.DataFrame:
    """Running order at the end of every lap: whoever finished lap N first is P1."""
    df = lap_end_times(laps).dropna(subset=["lap_end"])
    df["position"] = df.groupby("lap_number")["lap_end"].rank(method="first").astype(int)
    return df[["driver_number", "lap_number", "position"]].reset_index(drop=True)


def gaps_by_lap(laps: pd.DataFrame) -> pd.DataFrame:
    """Seconds behind the leader at the end of every lap."""
    df = lap_end_times(laps).dropna(subset=["lap_end"])
    leader_end = df.groupby("lap_number")["lap_end"].transform("min")
    df["gap_s"] = (df["lap_end"] - leader_end).dt.total_seconds()
    return df[["driver_number", "lap_number", "gap_s"]].reset_index(drop=True)


def lap_times(laps: pd.DataFrame, hide_slow: bool) -> pd.DataFrame:
    """Timed laps, optionally without lap 1, pit-out laps and slow laps."""
    df = laps.dropna(subset=["lap_duration"])
    if hide_slow and not df.empty:
        if "is_pit_out_lap" in df.columns:
            df = df[df["is_pit_out_lap"].ne(True)]
        df = df[df["lap_number"] > 1]  # lap 1 includes the standing start
        median = df.groupby("driver_number")["lap_duration"].transform("median")
        df = df[df["lap_duration"] <= median * SLOW_LAP_FACTOR]
    return df[["driver_number", "lap_number", "lap_duration"]].reset_index(drop=True)


def stint_bars(stints: pd.DataFrame, laps: pd.DataFrame) -> pd.DataFrame:
    """One row per stint with a known first and last lap (for the strategy chart).

    The current stint of a live session has no lap_end yet: use the driver's
    latest lap instead.
    """
    if stints.empty:
        return stints
    df = stints.copy()
    last_lap = laps.groupby("driver_number")["lap_number"].max() if not laps.empty else pd.Series(dtype=float)
    df["lap_end"] = df["lap_end"].fillna(df["driver_number"].map(last_lap))
    df = df.dropna(subset=["lap_start", "lap_end"])
    df["laps"] = df["lap_end"] - df["lap_start"] + 1
    df["compound"] = df["compound"].fillna("UNKNOWN").str.upper()
    return df[["driver_number", "stint_number", "compound", "lap_start", "lap_end", "laps",
               "tyre_age_at_start"]].sort_values(["driver_number", "stint_number"]).reset_index(drop=True)


def finishing_order(laps: pd.DataFrame) -> list[int]:
    """Driver numbers by final classification for races (most laps, then
    earliest finish), or by best lap for practice/qualifying."""
    if laps.empty:
        return []
    df = lap_end_times(laps)
    summary = df.groupby("driver_number").agg(laps=("lap_number", "max"),
                                              finished=("lap_end", "max"))
    return list(summary.sort_values(["laps", "finished"], ascending=[False, True]).index)


def best_lap_order(laps: pd.DataFrame) -> list[int]:
    best = laps.dropna(subset=["lap_duration"]).groupby("driver_number")["lap_duration"].min()
    return list(best.sort_values().index)


def fastest_lap(laps: pd.DataFrame, driver_number: int) -> pd.Series | None:
    """A driver's fastest lap that has a start time (needed to fetch telemetry)."""
    df = laps[(laps["driver_number"] == driver_number)].dropna(subset=["lap_duration", "date_start"])
    return df.loc[df["lap_duration"].idxmin()] if not df.empty else None


def add_distance(car_data: pd.DataFrame) -> pd.DataFrame:
    """Distance into the lap in metres, from speed over time.

    OpenF1's car_data has no distance field, so we integrate: each sample adds
    speed (km/h -> m/s) x time since the previous sample. Plotting against
    distance (not time) lines two laps up corner by corner.
    """
    if car_data.empty:
        return car_data
    df = car_data.sort_values("date").copy()
    dt = df["date"].diff().dt.total_seconds().fillna(0)
    df["distance_m"] = (df["speed"] / 3.6 * dt).cumsum()
    return df
