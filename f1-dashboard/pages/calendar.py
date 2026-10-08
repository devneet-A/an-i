"""Calendar page: the full season with every session time in IST."""

from __future__ import annotations

import streamlit as st

from lib import jolpica
from lib.schedule import add_status, weekend_label
from lib.http import APIError
from lib.timeutils import IST, format_countdown, now_utc

FIRST_YEAR = 2023
STATUS_ICON = {"done": "✅", "next": "🔜", "upcoming": "🗓️"}

st.title("Season calendar")
st.caption("All times in IST (Asia/Kolkata).")
now = now_utc()

pick, _ = st.columns([1, 4])
# Next year is listed too: its calendar is published before this season ends.
year = pick.selectbox("Season", list(range(now.year + 1, FIRST_YEAR - 1, -1)), index=1)

try:
    with st.spinner("Loading calendar..."):
        schedule = jolpica.get_schedule(year)
except APIError as exc:
    st.warning(f"Couldn't load the calendar: {exc}")
    st.stop()

if schedule.empty:
    st.info(f"The {year} calendar hasn't been published yet.")
    st.stop()

schedule = add_status(schedule, now)
schedule["ist"] = schedule["start_utc"].dt.tz_convert(IST)

# ---- next-session callout
upcoming = schedule[schedule["status"] == "next"]
if not upcoming.empty:
    nxt = upcoming.iloc[0]
    # "next" includes a session that has started but may not be over yet.
    when = ("on now" if nxt["start_utc"] <= now
            else f"in {format_countdown(nxt['start_utc'] - now)}")
    st.info(f"**Next:** {nxt['race_name']}, {nxt['session']} · "
            f"{nxt['ist']:%a %d %b, %H:%M} IST · {when}", icon="🔜")

by_event, full_table = st.tabs(["By event", "All sessions"])

with by_event:
    show_past = st.toggle("Show completed rounds", value=False)
    for rnd, sessions in schedule.groupby("round", sort=True):
        first = sessions.iloc[0]
        status = first["round_status"]
        if status == "done" and not show_past:
            continue
        sprint = " · ⚡ Sprint" if sessions["session"].eq("Sprint").any() else ""
        label = (f"{STATUS_ICON[status]} R{rnd} · **{first['race_name']}** · "
                 f"{weekend_label(sessions)}{sprint}")
        # Only the upcoming weekend starts open; the rest are one line each.
        with st.expander(label, expanded=status == "next"):
            st.caption(f"{first['circuit_name']} · {first['locality']}, {first['country']}")
            rows = sessions.assign(
                day=sessions["ist"].dt.strftime("%a %d %b"),
                time=sessions["ist"].dt.strftime("%H:%M"),
                state=sessions["status"].map({"done": "Done", "next": "Next", "upcoming": ""}),
            )
            st.dataframe(rows[["session", "day", "time", "state"]], hide_index=True,
                         width="stretch",
                         column_config={"session": "Session", "day": "Day",
                                        "time": "Time (IST)", "state": ""})
    if not show_past and (schedule["round_status"] == "done").all():
        st.info("Season complete. Turn on 'Show completed rounds' to see every event.")

with full_table:
    table = schedule.assign(
        date=schedule["ist"].dt.strftime("%a %d %b %Y"),
        time=schedule["ist"].dt.strftime("%H:%M"),
    )[["round", "race_name", "session", "date", "time", "country", "status"]]
    st.dataframe(table, hide_index=True, width="stretch", column_config={
        "round": st.column_config.NumberColumn("R", width=40),
        "race_name": "Grand Prix", "session": "Session", "date": "Date",
        "time": "Time (IST)", "country": "Country", "status": "Status",
    })
