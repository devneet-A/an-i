"""Standings page: drivers' and constructors' championships + points progression."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from lib import charts, jolpica, standings, ui
from lib.http import APIError
from lib.timeutils import now_utc

FIRST_YEAR = 2023  # team colours come from OpenF1, which starts in 2023
PLOTLY_CONFIG = {"displaylogo": False,
                 "modeBarButtonsToRemove": ["lasso2d", "select2d", "autoScale2d"]}


def tidy_points(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    """Show 575 instead of 575.0, but keep real half points (sprint/shortened races)."""
    for c in cols:
        if (df[c] % 1 == 0).all():
            df[c] = df[c].astype(int)
    return df


st.title("Championship standings")
now = now_utc()
pick, _ = st.columns([1, 4])  # keep the dropdown narrow on wide screens
year = pick.selectbox("Season", list(range(now.year, FIRST_YEAR - 1, -1)))

try:
    with st.spinner("Loading standings..."):
        drivers = jolpica.get_driver_standings(year)
        teams = jolpica.get_constructor_standings(year)
        points = jolpica.get_points_by_round(year)
except APIError as exc:
    st.warning(f"Couldn't load standings: {exc}")
    st.stop()

if drivers.empty:
    st.info(f"No championship standings for {year} yet. Check back after the first race.")
    st.stop()

# ---- colours: driver code -> OpenF1 team colour, team -> a driver's colour
by_driver = standings.driver_colours(year)
by_team = standings.team_colours(points if not points.empty else drivers, by_driver)
drivers = tidy_points(standings.with_gap(drivers), ["points", "gap"])
drivers["colour"] = [standings.colour_for_driver(c, t, by_driver, by_team)
                     for c, t in zip(drivers["code"], drivers["team"])]
teams = tidy_points(standings.with_gap(teams), ["points", "gap"])
teams["colour"] = teams["team"].map(by_team).fillna(standings.FALLBACK_COLOUR)
if not by_driver:
    st.caption("Team colours unavailable right now (OpenF1 didn't respond), showing grey.")

# ---- headline numbers
leader, second = drivers.iloc[0], drivers.iloc[1] if len(drivers) > 1 else None
c1, c2, c3 = st.columns(3)
c1.metric("Drivers' leader", f"{leader['code']} · {leader['points']} pts",
          f"+{second['gap']} over {second['code']}" if second is not None else None,
          delta_color="off")
if not teams.empty:
    # Team names are long, so the points go in the label to avoid "Red Bull · 86…".
    c2.metric(f"Constructors' leader · {teams.iloc[0]['points']} pts", teams.iloc[0]["team"])
c3.metric("After round", int(leader["round"]))

tab_drivers, tab_teams, tab_progress = st.tabs(["Drivers", "Constructors", "Points progression"])

with tab_drivers:
    st.html(ui.standings_html(drivers, "driver", sub_col="team"))

with tab_teams:
    if teams.empty:
        st.info("No constructors' standings yet.")
    else:
        st.html(ui.standings_html(teams, "team"))

with tab_progress:
    if points.empty:
        st.info("No race results yet.")
    else:
        mode = st.segmented_control("Show", ["Drivers", "Constructors"], default="Drivers")
        by = "team" if mode == "Constructors" else "code"
        totals = standings.cumulative_points(points, by)
        ranked = (drivers["code"] if by == "code" else teams["team"]).tolist()
        ranked = [x for x in ranked if x in set(totals[by])]
        picked = st.multiselect("Lines", ranked, default=ranked[:10 if by == "code" else len(ranked)])
        if by == "code":
            colours = dict(zip(drivers["code"], drivers["colour"]))
            # Second driver of each team (by standing) dashed, like the Analysis page.
            dashes = {c: "dash" for c in drivers[drivers.duplicated("team")]["code"]}
        else:
            colours, dashes = by_team, {}
        shown = totals[totals[by].isin(picked)]
        if shown.empty:
            st.info("Pick at least one line.")
        else:
            st.plotly_chart(charts.progression_chart(shown, by, colours, dashes),
                            width="stretch", config=PLOTLY_CONFIG)
            with st.expander("Data table"):
                wide = shown.pivot(index=["round", "race_name"], columns=by, values="total")
                st.dataframe(wide[picked].reset_index(), hide_index=True, width="stretch")
