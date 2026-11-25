"""Отдельный фронт урока 18."""

from __future__ import annotations

import streamlit as st

import lesson18_page

st.set_page_config(
    page_title="AI Challenge · Планировщик и фоновые задачи",
    page_icon="⏱️",
    layout="wide",
    initial_sidebar_state="collapsed",
)
lesson18_page.render()
