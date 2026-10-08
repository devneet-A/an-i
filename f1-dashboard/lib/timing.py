"""Turn raw OpenF1 tables into display-ready tables. No API calls, no Streamlit.

Keeping this pure (DataFrames in, DataFrame out) means it works the same for
live and historical data, and it can be unit-tested with tiny fake tables.
"""

from __future__ import annotations

import pandas as pd

from lib.timeutils import format_laptime

# Coloured circles stand in for tyre colours: readable on a phone, no images.
COMPOUND_ICON: dict[str, str] = {
    "SOFT": "🔴", "MEDIUM": "🟡", "HARD": "⚪",
    "INTERMEDIATE": "🟢", "WET": "🔵",
}

FLAG_ICON: dict[str, str] = {
    "GREEN": "🟢", "CLEAR": "🟢", "YELLOW": "🟡", "DOUBLE YELLOW": "🟡🟡",
    "RED": "🔴", "BLUE": "🔵", "CHEQUERED": "🏁", "BLACK AND WHITE": "🏳️",
}


def latest_per_driver(df: pd.DataFrame, date_col: str = "date") -> pd.DataFrame:
    """Most recent row for each driver (position and interval feeds are logs).

    drop_duplicates(keep="last") takes the whole newest row. groupby().last()
    would NOT: it skips blanks, so the leader's empty gap would be replaced by
    an older number.
    """
    if df.empty or "driver_number" not in df.columns:
        return df
    return (df.sort_values(date_col).drop_duplicates("driver_number", keep="last")
              .reset_index(drop=True))


def _format_gap(value: object) -> str:
    """Gaps are seconds (float) or text like '+1 LAP'. Leader has 0 or None."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    if isinstance(value, str):
        return value
    return f"+{float(value):.3f}" if float(value) > 0 else ""


def build_tower(drivers: pd.DataFrame, positions: pd.DataFrame, intervals: pd.DataFrame,
                laps: pd.DataFrame, stints: pd.DataFrame, pit: pd.DataFrame) -> pd.DataFrame:
    """One row per driver, ordered by current position.

    Races have an intervals feed (gap to leader, gap to car ahead). Practice and
    qualifying don't, so there we show the gap between best lap times instead.
    """
    if drivers.empty:
        return pd.DataFrame()

    tower = drivers[["driver_number", "name_acronym", "team_name", "team_colour"]].copy()

    pos = latest_per_driver(positions)
    if not pos.empty:
        tower = tower.merge(pos[["driver_number", "position"]], on="driver_number", how="left")
    else:
        tower["position"] = pd.NA

    # ---- lap times -------------------------------------------------------
    current_lap = pd.Series(dtype="float64")
    if not laps.empty:
        timed = laps.dropna(subset=["lap_duration"])
        last = timed.sort_values("lap_number").groupby("driver_number")["lap_duration"].last()
        best = timed.groupby("driver_number")["lap_duration"].min()
        current_lap = laps.groupby("driver_number")["lap_number"].max()
        tower["last_lap_s"] = tower["driver_number"].map(last)
        tower["best_lap_s"] = tower["driver_number"].map(best)
    else:
        tower["last_lap_s"] = tower["best_lap_s"] = float("nan")

    # ---- gaps ------------------------------------------------------------
    ivl = latest_per_driver(intervals)
    if not ivl.empty:
        gaps = ivl.set_index("driver_number")
        tower["gap"] = tower["driver_number"].map(gaps["gap_to_leader"]).map(_format_gap)
        tower["interval"] = tower["driver_number"].map(gaps["interval"]).map(_format_gap)
    else:
        fastest = tower["best_lap_s"].min()
        tower["gap"] = (tower["best_lap_s"] - fastest).map(_format_gap)
        tower["interval"] = ""

    # ---- tyres -----------------------------------------------------------
    tower["tyre"], tower["compound"], tower["tyre_age"] = "", "", 0
    if not stints.empty:
        stint = (stints.sort_values("stint_number")
                       .drop_duplicates("driver_number", keep="last").set_index("driver_number"))
        compound = tower["driver_number"].map(stint["compound"]).fillna("")
        # Tyre age now = age when fitted + laps done since fitting.
        laps_on_set = (tower["driver_number"].map(current_lap)
                       - tower["driver_number"].map(stint["lap_start"])).clip(lower=0)
        age = tower["driver_number"].map(stint["tyre_age_at_start"]) + laps_on_set.fillna(0)
        tower["compound"] = compound.astype(str).str.upper()
        tower["tyre_age"] = age.fillna(0).astype(int)
        tower["tyre"] = [
            f"{COMPOUND_ICON.get(str(c).upper(), '⚫')} {str(c).title()[:1]} · {int(a)}"
            if c else ""
            for c, a in zip(compound, age.fillna(0))
        ]

    stops = pit.groupby("driver_number").size() if not pit.empty else pd.Series(dtype="int64")
    tower["pits"] = tower["driver_number"].map(stops).fillna(0).astype(int)

    tower["last_lap"] = tower["last_lap_s"].map(format_laptime)
    tower["best_lap"] = tower["best_lap_s"].map(format_laptime)
    tower["position"] = pd.to_numeric(tower["position"], errors="coerce")
    tower = tower.sort_values(["position", "best_lap_s"], na_position="last").reset_index(drop=True)
    tower["position"] = tower["position"].astype("Int64")  # whole numbers, blanks allowed
    # Display columns first (team last, so phones show the useful ones), then the
    # raw values the TV-style tower uses for colour coding.
    return tower[["position", "team_colour", "name_acronym", "gap", "interval",
                  "last_lap", "best_lap", "tyre", "pits", "team_name",
                  "compound", "tyre_age", "last_lap_s", "best_lap_s"]]


def track_status(race_control: pd.DataFrame) -> str | None:
    """Current track state from race control, like the TV graphic.

    Returns "CLEAR", "YELLOW", "SC", "VSC", "RED", "FINISHED" or None. Yellow
    flags limited to one sector don't change the whole-track state.
    """
    if race_control.empty:
        return None
    state: str | None = None
    for m in race_control.sort_values("date").itertuples(index=False):
        flag = str(getattr(m, "flag", "") or "")
        msg = str(getattr(m, "message", "") or "").upper()
        scope = str(getattr(m, "scope", "") or "")
        if getattr(m, "category", "") == "SafetyCar":
            if "DEPLOYED" in msg:
                state = "VSC" if "VIRTUAL" in msg else "SC"
            # "ENDING" / "IN THIS LAP": still neutralised until the green flag.
        elif flag == "RED":
            state = "RED"
        elif flag == "CHEQUERED":
            state = "FINISHED"
        elif flag in ("GREEN", "CLEAR") and scope in ("Track", ""):
            state = "CLEAR"
        elif flag in ("YELLOW", "DOUBLE YELLOW") and scope == "Track":
            state = "YELLOW"
    return state


def lap_label(laps: pd.DataFrame, race_control: pd.DataFrame, session_type: str) -> str:
    """'<span>LAP</span> 34' for races, '<span>SESSION</span> Q3' in qualifying."""
    if session_type == "Race" and not laps.empty:
        return f"<span>LAP</span>{int(laps['lap_number'].max())}"
    if "Qualifying" in session_type and "qualifying_phase" in race_control.columns:
        phase = race_control.sort_values("date")["qualifying_phase"].dropna()
        if not phase.empty:
            prefix = "SQ" if session_type.startswith("Sprint") else "Q"
            return f"<span>SESSION</span>{prefix}{int(phase.iloc[-1])}"
    return ""
