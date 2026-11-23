"""Отдельный фронт урока 16: подключение MCP и чат."""

from __future__ import annotations

import streamlit as st

import autoscroll
import lesson16_page

st.set_page_config(
    page_title="AI Challenge · MCP",
    page_icon="🔌",
    layout="wide",
    initial_sidebar_state="collapsed",
)
autoscroll.install()
lesson16_page.render()
