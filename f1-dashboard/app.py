"""Entry point: `streamlit run app.py`.

st.navigation (instead of the automatic /pages sidebar) lets us choose page
titles, icons and order ourselves, and make the Live page the home page.
More pages get added here in later build steps.
"""

import streamlit as st

st.set_page_config(
    page_title="F1 Live Dashboard",
    page_icon="🏎️",
    layout="wide",  # use the full screen width for timing tables
)

pages = [
    st.Page("pages/live.py", title="Live", icon="🔴", default=True),
]

st.navigation(pages).run()
