"""Отдельный фронт урока 19."""

from __future__ import annotations

import streamlit as st

import lesson19_page

st.set_page_config(
    page_title="AI Challenge · Композиция MCP инструментов",
    page_icon="🔗",
    layout="wide",
    initial_sidebar_state="collapsed",
)
lesson19_page.render()
