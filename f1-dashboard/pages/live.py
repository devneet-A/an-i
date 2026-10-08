"""Live page: session header, countdown, timing tower, weather, race control."""

from __future__ import annotations

from contextlib import nullcontext
from datetime import timedelta

import pandas as pd
import streamlit as st

from lib.http import APIError
from lib.live_feed import Snapshot, get_feed, load_completed
from lib.session_detect import (OVERRUN_ALLOWANCE, SessionInfo, SessionStatus,
                                chequered_flag_shown, detect)
from lib.timeutils import IST, format_countdown, format_ist, now_utc
from lib.timing import FLAG_ICON, build_tower

# A session that ended less than this long ago may still get data corrections,
# so we use the short cache for it instead of the 6-hour one.
RECENTLY_ENDED = timedelta(hours=1)


def render_header(status: SessionStatus) -> None:
    """Event name, session, circuit and a LIVE / LATEST badge."""
    session = status.live or status.data_session
    if session is None:
        st.title("🏎️ F1 Live Dashboard")
        st.info("No sessions found yet for this season.")
        return

    if status.is_live:
        st.badge("LIVE", icon="🔴", color="red")
    else:
        st.badge("LATEST SESSION", icon=":material/history:", color="gray")

    st.title(session.meeting_name)
    when = "Started" if status.is_live else "Ran"
    st.caption(
        f"**{session.session_name}** · {session.circuit}, {session.country} · "
        f"{when} {format_ist(session.start)}"
    )


# A fragment re-runs on its own timer without re-running the whole page.
# The countdown only needs minute precision, so every 30s is plenty, and it
# makes no API calls, so it costs nothing to leave running.
@st.fragment(run_every="30s")
def render_countdown(status: SessionStatus) -> None:
    now = now_utc()

    # When a session starts or the live one ends, re-run the WHOLE page so the
    # header (and later the live widgets) switch mode. We remember which
    # boundary we already reacted to, to avoid re-running in a loop.
    boundaries: list[tuple[str, object]] = []
    if status.next_session is not None:
        boundaries.append(("start", status.next_session.start))
    if status.live is not None:
        boundaries.append(("end", status.live.end + OVERRUN_ALLOWANCE))
    for label, moment in boundaries:
        token = f"{label}:{moment}"
        if now >= moment and st.session_state.get("last_boundary") != token:
            st.session_state["last_boundary"] = token
            st.rerun(scope="app")

    nxt: SessionInfo | None = status.next_session
    if nxt is None:
        st.metric("Next session", "Season complete")
        return
    st.metric(f"Next: {nxt.session_name}", format_countdown(nxt.start - now))
    st.caption(f"{nxt.meeting_name} · {format_ist(nxt.start)}")


# --------------------------------------------------------------------------
# Timing tower, weather, race control
# --------------------------------------------------------------------------

def render_tower(snap: Snapshot) -> None:
    tower = build_tower(snap.drivers, snap.positions, snap.intervals,
                        snap.laps, snap.stints, snap.pit)
    if tower.empty:
        st.info("No timing data for this session yet.")
        return

    # Pandas Styler paints the colour column: background AND text in the team
    # colour, so it reads as a solid stripe and the hex code is invisible.
    styled = tower.style.map(lambda c: f"background-color: {c}; color: {c}",
                             subset=["team_colour"])
    st.dataframe(
        styled,
        hide_index=True,
        width="stretch",
        # Tall enough for every row (~35px each) so the tower never scrolls inside itself.
        height=(len(tower) + 1) * 35 + 3,
        column_config={
            "position": st.column_config.NumberColumn("P", width=40),
            "team_colour": st.column_config.TextColumn("", width=8),
            "name_acronym": st.column_config.TextColumn("Driver", width=64),
            "gap": st.column_config.TextColumn("Gap", help="Gap to the leader"),
            "interval": st.column_config.TextColumn("Int", help="Gap to the car ahead"),
            "last_lap": st.column_config.TextColumn("Last lap"),
            "best_lap": st.column_config.TextColumn("Best"),
            "tyre": st.column_config.TextColumn("Tyre", help="Compound · laps on this set"),
            "pits": st.column_config.NumberColumn("Pits", width=48),
            "team_name": st.column_config.TextColumn("Team"),
        },
    )


def render_weather(weather: pd.DataFrame) -> None:
    if weather.empty:
        st.caption("No weather data.")
        return
    w = weather.iloc[-1]
    # Compare with ~10 minutes ago so the arrows show the trend.
    older = weather[weather["date"] <= w["date"] - timedelta(minutes=10)]
    prev = older.iloc[-1] if not older.empty else None

    def delta(col: str) -> float | None:
        return round(float(w[col] - prev[col]), 1) if prev is not None else None

    c1, c2, c3 = st.columns(3)
    c1.metric("Air", f"{w['air_temperature']:.1f}°C", delta("air_temperature"), delta_color="off")
    c2.metric("Track", f"{w['track_temperature']:.1f}°C", delta("track_temperature"), delta_color="off")
    c3.metric("Humidity", f"{w['humidity']:.0f}%")
    c4, c5, _ = st.columns(3)
    c4.metric("Rain", "Yes 🌧️" if w["rainfall"] else "No")
    c5.metric("Wind", f"{w['wind_speed']:.1f} m/s", help=f"From {w['wind_direction']:.0f}°")


def render_race_control(rc: pd.DataFrame) -> None:
    if rc.empty:
        st.caption("No race control messages.")
        return
    # Fixed-height container = its own scroll area; newest message first.
    with st.container(height=380):
        for _, m in rc.sort_values("date", ascending=False).head(60).iterrows():
            icon = FLAG_ICON.get(str(m.get("flag") or ""), "")
            if not icon:
                icon = "🚗" if m.get("category") == "SafetyCar" else "ℹ️"
            lap = f"L{int(m['lap_number'])} · " if pd.notna(m.get("lap_number")) else ""
            t = m["date"].tz_convert(IST).strftime("%H:%M:%S")
            st.markdown(f"{icon} **{m['message']}**  \n:gray[{lap}{t}]")


def render_session_data(status: SessionStatus) -> None:
    session = status.data_session
    if session is None or session.session_key is None:
        st.info("Timing data isn't available right now.")
        return

    if status.can_stream:
        feed = get_feed(session.session_key)
        # Only show a spinner on the very first load, not on every 5s tick.
        with st.spinner("Connecting to live timing...") if feed.snap.updated_at is None else nullcontext():
            snap = feed.refresh()
        # Chequered flag: reload the whole page so it leaves live mode.
        token = f"ended:{session.session_key}"
        if (chequered_flag_shown(snap.race_control, session.session_type)
                and st.session_state.get("last_boundary") != token):
            st.session_state["last_boundary"] = token
            st.rerun(scope="app")
    else:
        fresh = now_utc() - session.end < RECENTLY_ENDED
        with st.spinner("Loading session data..."):
            snap = load_completed(session.session_key, fresh=fresh)

    if snap.errors:
        st.warning("Some data couldn't be loaded: " + "; ".join(snap.errors))

    left, right = st.columns([3, 2], gap="large")
    with left:
        st.subheader("Timing")
        render_tower(snap)
    with right:
        st.subheader("Weather")
        render_weather(snap.weather)
        st.subheader("Race control")
        render_race_control(snap.race_control)

    if snap.updated_at is not None:
        label = "Live · refreshes every 5s" if status.can_stream else "Final data"
        st.caption(f"{label} · updated {format_ist(snap.updated_at)}")


# --------------------------------------------------------------------------
# Page
# --------------------------------------------------------------------------

try:
    with st.spinner("Checking the F1 schedule..."):
        status = detect()
except APIError as exc:
    st.title("🏎️ F1 Live Dashboard")
    st.error(f"Couldn't load the F1 schedule: {exc}")
    st.button("Try again", on_click=st.cache_data.clear)
    st.stop()

# On a wide screen these sit side by side; on a phone Streamlit stacks them.
left, right = st.columns([3, 1], vertical_alignment="center")
with left:
    render_header(status)
with right:
    render_countdown(status)

if status.note:
    st.info(status.note)

if status.is_live and not status.can_stream and status.data_session:
    d = status.data_session
    st.caption(f"Showing data from: {d.meeting_name}, {d.session_name} ({format_ist(d.start)})")

st.divider()

# Auto-refresh ONLY while we can actually stream a live session. Wrapping the
# function in st.fragment means each 5s tick re-runs just this part of the
# page, not the header above it.
if status.can_stream:
    st.fragment(run_every="5s")(render_session_data)(status)
else:
    render_session_data(status)
