"""Streamlit demo for foretaksrisiko: aggregate patterns, model results and a synthetic company.

Run locally with ``streamlit run app/streamlit_app.py``. The app reads only the public files in
``demo_data/`` and ``figures/`` and never calls the registers or the lakehouse. The assistant
page sends the user's message to Groq, and only when ``GROQ_API_KEY`` is set.
"""

from __future__ import annotations

import streamlit as st
from demo_ui import pages
from demo_ui.texts import LANGUAGE_NAMES, PAGE_KEYS, text

st.set_page_config(page_title="foretaksrisiko", layout="wide")


def _choose_page(nav_key: str) -> None:
    """Radio callback: the page picked in the list becomes the chosen page."""
    st.session_state["page"] = st.session_state[nav_key]


def main() -> None:
    lang = st.sidebar.radio(
        "Språk / Language",
        options=list(LANGUAGE_NAMES),
        format_func=LANGUAGE_NAMES.get,
        horizontal=True,
        key="lang",
    )
    # The chosen page lives in st.session_state["page"]. The page names change with the language,
    # which makes Streamlit treat the list as a new widget, so each language has its own list,
    # set from the chosen page before it is drawn. Buttons that open a page set "page" too.
    page = st.session_state.setdefault("page", PAGE_KEYS[0])
    nav_key = f"nav_{lang}"
    if st.session_state.get(nav_key) != page:
        st.session_state[nav_key] = page
    st.sidebar.radio(
        text("nav.title", lang),
        options=list(PAGE_KEYS),
        format_func=lambda key: text(f"nav.{key}", lang),
        key=nav_key,
        on_change=_choose_page,
        args=(nav_key,),
    )
    page = st.session_state["page"]
    st.sidebar.caption(text("nav.note", lang))
    st.sidebar.markdown(text("nav.author", lang))
    st.sidebar.markdown(text("nav.repo", lang))
    pages.render(page, lang)


main()
