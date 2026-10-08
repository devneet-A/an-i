"""Live page, laid out like the F1 TV timing screen: banner, lap/track status,
timing tower on the left, weather and race control on the right."""

from __future__ import annotations

from contextlib import nullcontext
from datetime import timedelta

import streamlit as st

from lib.http import APIError
from lib.live_feed import Snapshot, get_feed, load_completed
from lib.session_detect import (OVERRUN_ALLOWANCE, SessionInfo, SessionStatus,
                                chequered_flag_shown, detect)
from lib import ui
from lib.timeutils import format_countdown, format_ist, now_utc
from lib.timing import build_tower, lap_label, track_status

# A session that ended less than this long ago may still get data corrections,
# so we use the short cache for it instead of the 6-hour one.
RECENTLY_ENDED = timedelta(hours=1)


def render_header(status: SessionStatus) -> None:
    """Broadcast-style banner: LIVE / LATEST chip, event name, session line."""
    session = status.live or status.data_session
    if session is None:
        st.title("F1 Live Dashboard")
        st.info("No sessions found yet for this season.")
        return
    when = "Started" if status.is_live else "Ran"
    st.html(ui.banner_html(
        event=session.meeting_name,
        meta=f"{session.session_name} · {session.circuit}, {session.country} · "
             f"{when} {format_ist(session.start)}",
        chip="Live" if status.is_live else "Latest session",
        live=status.is_live,
    ))


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
        st.html(ui.next_session_html("Next session", "Season complete", ""))
        return
    st.html(ui.next_session_html(f"Next · {nxt.session_name}", format_countdown(nxt.start - now),
                                 f"{nxt.meeting_name} · {format_ist(nxt.start)}"))


# --------------------------------------------------------------------------
# Timing tower, weather, race control
# --------------------------------------------------------------------------

def render_tower(snap: Snapshot) -> None:
    tower = build_tower(snap.drivers, snap.positions, snap.intervals,
                        snap.laps, snap.stints, snap.pit)
    if tower.empty:
        st.info("No timing data for this session yet.")
        return
    st.html(ui.tower_html(tower))


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

    # Lap counter + track status, like the strip under the TV timing graphic.
    st.html(ui.status_html(lap_label(snap.laps, snap.race_control, session.session_type),
                           track_status(snap.race_control)))

    left, right = st.columns([3, 2], gap="large")
    with left:
        render_tower(snap)
    with right:
        st.html(ui.weather_html(snap.weather))
        st.html(ui.race_control_html(snap.race_control))

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
    st.title("F1 Live Dashboard")
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

# Auto-refresh ONLY while we can actually stream a live session. Wrapping the
# function in st.fragment means each 5s tick re-runs just this part of the
# page, not the header above it.
if status.can_stream:
    st.fragment(run_every="5s")(render_session_data)(status)
else:
    render_session_data(status)
