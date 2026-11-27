"""Отдельный фронт урока 20."""

from __future__ import annotations

import streamlit as st

import lesson20_page

st.set_page_config(
    page_title="AI Challenge · Оркестрация MCP",
    page_icon="🧭",
    layout="wide",
    initial_sidebar_state="collapsed",
)
lesson20_page.render()
