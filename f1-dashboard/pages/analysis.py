"""Analysis page: pick a session, compare drivers with interactive charts."""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from typing import Any

import pandas as pd
import streamlit as st

from lib import analysis, charts, openf1
from lib.http import APIError
from lib.timeutils import format_ist, format_laptime, now_utc

# Plotly toolbar: keep zoom/reset, hide the logo and rarely-used buttons.
PLOTLY_CONFIG = {"displaylogo": False,
                 "modeBarButtonsToRemove": ["lasso2d", "select2d", "autoScale2d"]}
FIRST_YEAR = 2023  # OpenF1 data starts in 2023


def safe(fn: Callable[..., pd.DataFrame], *args: Any, **kwargs: Any) -> pd.DataFrame:
    """Call an API function; on failure show a warning and return an empty table."""
    try:
        return fn(*args, **kwargs)
    except APIError as exc:
        st.warning(str(exc))
        return pd.DataFrame()


def show(fig, table: pd.DataFrame) -> None:
    """A chart plus its data as a table: the table is the accessible version
    and lets people read exact values without hovering."""
    st.plotly_chart(fig, width="stretch", config=PLOTLY_CONFIG)
    with st.expander("Data table"):
        st.dataframe(table, hide_index=True, width="stretch")


def with_codes(df: pd.DataFrame, styles: analysis.Styles) -> pd.DataFrame:
    out = df.copy()
    out.insert(0, "driver", out["driver_number"].map(lambda n: styles.get(n, {}).get("code", n)))
    return out.drop(columns=["driver_number"])


st.title("Session analysis")
now = now_utc()

# --------------------------------------------------------------------------
# Sidebar: year -> Grand Prix -> session -> drivers
# --------------------------------------------------------------------------
with st.sidebar:
    st.header("Session")
    year = st.selectbox("Year", list(range(now.year, FIRST_YEAR - 1, -1)))
    meetings = safe(openf1.get_meetings, year)
    if not meetings.empty:
        meetings = meetings[meetings["date_start"] <= now].iloc[::-1]  # newest first
    if meetings.empty:
        st.info(f"No completed events for {year} yet.")
        st.stop()
    meeting_key = st.selectbox(
        "Grand Prix", meetings["meeting_key"].tolist(),
        format_func=dict(zip(meetings["meeting_key"], meetings["meeting_name"])).get)

    sessions = safe(openf1.get_sessions, meeting_key=meeting_key)
    if not sessions.empty:
        sessions = sessions[sessions["date_start"] <= now]
    if sessions.empty:
        st.info("No sessions have started for this event yet.")
        st.stop()
    # Default to the last session of the weekend (usually the race).
    session_key = st.selectbox(
        "Session", sessions["session_key"].tolist(), index=len(sessions) - 1,
        format_func=dict(zip(sessions["session_key"], sessions["session_name"])).get)

session = sessions.set_index("session_key").loc[session_key]
is_race = session["session_type"] == "Race"  # includes Sprints
# Still running or just finished: data can change, so use the short cache.
fresh = now < session["date_end"] + timedelta(hours=1)

with st.spinner("Loading laps and tyre data..."):
    drivers = safe(openf1.get_drivers, session_key, live=fresh)
    laps = safe(openf1.get_laps, session_key, live=fresh)
    stints = safe(openf1.get_stints, session_key, live=fresh)

if drivers.empty or laps.empty:
    st.info("No lap data for this session.")
    st.stop()

styles = analysis.driver_styles(drivers)
order = [n for n in (analysis.finishing_order(laps) if is_race else analysis.best_lap_order(laps))
         if n in styles]

with st.sidebar:
    selected = st.multiselect(
        "Drivers", order, default=order[:5],
        format_func=lambda n: f"{styles[n]['code']} · {styles[n]['team']}")
    st.caption("Teammates share a colour; the second driver is drawn dashed.")

st.caption(f"{meetings.set_index('meeting_key').loc[meeting_key, 'meeting_name']} · "
           f"{session['session_name']} · {format_ist(session['date_start'])}")
if not selected:
    st.info("Pick at least one driver in the sidebar.")
    st.stop()

# --------------------------------------------------------------------------
# Charts
# --------------------------------------------------------------------------
tab_names = ["Lap times", "Tyres", "Telemetry"]
if is_race:
    tab_names[1:1] = ["Positions", "Gap to leader"]
tabs = dict(zip(tab_names, st.tabs(tab_names)))

with tabs["Lap times"]:
    hide_slow = st.toggle("Hide lap 1, pit and slow laps", value=True,
                          help=f"Drops lap 1, pit-out laps and laps over {analysis.SLOW_LAP_FACTOR:.0%} "
                               "of the driver's median (safety car, traffic).")
    lt = analysis.lap_times(laps, hide_slow)
    lt = lt[lt["driver_number"].isin(selected)]
    show(charts.lap_time_chart(lt, styles, selected),
         with_codes(lt.assign(lap_time=lt["lap_duration"].map(format_laptime)), styles))

if is_race:
    with tabs["Positions"]:
        pos = analysis.positions_by_lap(laps)
        pos = pos[pos["driver_number"].isin(selected)]
        show(charts.position_chart(pos, styles, selected), with_codes(pos, styles))
    with tabs["Gap to leader"]:
        gaps = analysis.gaps_by_lap(laps)
        gaps = gaps[gaps["driver_number"].isin(selected)]
        show(charts.gap_chart(gaps, styles, selected), with_codes(gaps.round(3), styles))

with tabs["Tyres"]:
    bars = analysis.stint_bars(stints, laps)
    if bars.empty:
        st.info("No tyre data for this session.")
    else:
        bars = bars[bars["driver_number"].isin(selected)]
        show(charts.stint_chart(bars, styles, selected), with_codes(bars, styles))

with tabs["Telemetry"]:
    st.caption("Fastest-lap telemetry for two drivers, lined up by distance into the lap.")
    choices = selected if len(selected) >= 2 else order
    c1, c2 = st.columns(2)
    fmt = lambda n: styles[n]["code"]  # noqa: E731
    a = c1.selectbox("Driver A", choices, index=0, format_func=fmt)
    b = c2.selectbox("Driver B", choices, index=min(1, len(choices) - 1), format_func=fmt)

    traces: dict[int, pd.DataFrame] = {}
    summary = []
    with st.spinner("Loading telemetry..."):
        for n in dict.fromkeys([a, b]):  # dict.fromkeys = unique, keeps order
            lap = analysis.fastest_lap(laps, n)
            if lap is None:
                st.info(f"No timed lap with telemetry for {styles[n]['code']}.")
                continue
            end = lap["date_start"] + timedelta(seconds=float(lap["lap_duration"]))
            car = analysis.add_distance(safe(openf1.get_car_data, session_key, n, lap["date_start"], end))
            if car.empty:
                continue
            traces[n] = car
            summary.append({"driver": styles[n]["code"], "lap": int(lap["lap_number"]),
                            "lap_time": format_laptime(lap["lap_duration"]),
                            "top_speed_kmh": int(car["speed"].max()),
                            "full_throttle_pct": round((car["throttle"] >= 98).mean() * 100, 1)})
    if traces:
        show(charts.telemetry_chart(traces, styles), pd.DataFrame(summary))
