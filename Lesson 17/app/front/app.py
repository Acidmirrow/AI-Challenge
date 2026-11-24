"""Отдельный фронт урока 17."""

from __future__ import annotations

import streamlit as st

import lesson17_page

st.set_page_config(
    page_title="AI Challenge · Первый инструмент MCP",
    page_icon="🛠️",
    layout="wide",
    initial_sidebar_state="collapsed",
)
lesson17_page.render()
