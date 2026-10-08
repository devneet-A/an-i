"""Live page. Step 1: just proves both APIs answer (real page comes in step 2)."""

import streamlit as st

from lib import jolpica, openf1
from lib.http import APIError

st.title("🏎️ F1 Live Dashboard")
st.caption("Step 1: API connection check")

col1, col2 = st.columns(2)

with col1:
    st.subheader("OpenF1")
    try:
        with st.spinner("Asking OpenF1 for the latest session..."):
            session = openf1.get_session("latest")
        if session.empty:
            st.info("OpenF1 returned no session.")
        else:
            s = session.iloc[0]
            st.success(f"{s['session_name']}, {s['location']} {s['year']}")
            st.dataframe(session.T, width="stretch")
    except APIError as exc:
        st.warning(str(exc))
    st.write("Live data credentials:", "✅ configured" if openf1.has_live_access() else "➖ not set (historical mode)")

with col2:
    st.subheader("Jolpica")
    try:
        with st.spinner("Fetching this season's calendar..."):
            schedule = jolpica.get_schedule("current")
        if schedule.empty:
            st.info("Jolpica returned no calendar.")
        else:
            st.success(f"{schedule['round'].max()} rounds, {len(schedule)} sessions")
            st.dataframe(schedule.head(10), width="stretch", hide_index=True)
    except APIError as exc:
        st.warning(str(exc))
