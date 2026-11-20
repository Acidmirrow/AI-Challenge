"""Отдельный фронт урока 10: сравнение стратегий управления контекстом."""

from __future__ import annotations

import streamlit as st
import autoscroll

import lesson10_page

st.set_page_config(
    page_title="AI Challenge · Сравнение стратегий",
    page_icon="🧭",
    layout="wide",
    initial_sidebar_state="expanded",
)
autoscroll.install()

lesson10_page.render()
