"""Entry point: `streamlit run app.py`.

st.navigation sets up the pages; position="hidden" turns off Streamlit's
sidebar menu because we draw our own floating pill navigation (lib/ui.py).
"""

import streamlit as st

from lib import ui

st.set_page_config(
    page_title="F1 Live Dashboard",
    page_icon="🏎️",
    layout="wide",  # use the full screen width for timing tables
    initial_sidebar_state="collapsed",
)

pages = [
    st.Page("pages/live.py", title="Live", icon="🔴", default=True),
    st.Page("pages/analysis.py", title="Analysis", icon="📈"),
    st.Page("pages/standings.py", title="Standings", icon="🏆"),
    st.Page("pages/calendar.py", title="Calendar", icon="🗓️"),
]

page = st.navigation(pages, position="hidden")
ui.inject_css()
ui.pill_nav(pages, current=page)
page.run()
