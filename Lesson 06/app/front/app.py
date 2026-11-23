"""Отдельный фронт урока 06: ИИ-агент с инструментами."""

from __future__ import annotations

import streamlit as st

import agent_page
import autoscroll
import enter_submit

st.set_page_config(
    page_title="AI Challenge · ИИ-агент",
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="expanded",
)
autoscroll.install()
enter_submit.install()
agent_page.render()
