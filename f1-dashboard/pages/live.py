"""Live page: header with live/latest session and a countdown to the next one.

The timing tower, race control and weather are added in step 3.
"""

from __future__ import annotations

import streamlit as st

from lib.http import APIError
from lib.session_detect import OVERRUN_ALLOWANCE, SessionInfo, SessionStatus, detect
from lib.timeutils import format_countdown, format_ist, now_utc


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
st.caption("Timing tower, race control and weather arrive in step 3.")
