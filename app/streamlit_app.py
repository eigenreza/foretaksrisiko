"""Streamlit demo for foretaksrisiko: aggregate patterns, model results and a synthetic company.

Run locally with ``streamlit run app/streamlit_app.py``. The app reads only the public files in
``demo_data/`` and ``figures/`` and never calls the registers or the lakehouse.
"""

from __future__ import annotations

import streamlit as st
from demo_ui import pages
from demo_ui.texts import LANGUAGE_NAMES, PAGE_KEYS, text

st.set_page_config(page_title="foretaksrisiko", layout="wide")


def main() -> None:
    lang = st.sidebar.radio(
        "Språk / Language",
        options=list(LANGUAGE_NAMES),
        format_func=LANGUAGE_NAMES.get,
        horizontal=True,
        key="lang",
    )
    page = st.sidebar.radio(
        text("nav.title", lang),
        options=list(PAGE_KEYS),
        format_func=lambda key: text(f"nav.{key}", lang),
        key="page",
    )
    st.sidebar.caption(text("nav.note", lang))
    st.sidebar.markdown(text("nav.author", lang))
    st.sidebar.markdown(text("nav.repo", lang))
    pages.render(page, lang)


main()
