"""Отдельный фронт урока 15: устаревание и конфликты памяти."""

from __future__ import annotations

import streamlit as st
import autoscroll

import enter_submit
import lesson15_page

st.set_page_config(
    page_title="AI Challenge · Память и конфликты",
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="expanded",
)
autoscroll.install()
enter_submit.install()
lesson15_page.render()
