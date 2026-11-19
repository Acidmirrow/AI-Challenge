"""Отдельный фронт урока 13: состояние задачи."""

from __future__ import annotations

import streamlit as st

import lesson13_page

st.set_page_config(
    page_title="AI Challenge · Состояние задачи",
    page_icon="🧭",
    layout="wide",
    initial_sidebar_state="expanded",
)
lesson13_page.render()
