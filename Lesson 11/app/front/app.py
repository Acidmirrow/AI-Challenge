"""Отдельный фронт урока 11: модель памяти ассистента."""

from __future__ import annotations

import streamlit as st
import autoscroll

import enter_submit
import memory_page

st.set_page_config(
    page_title="AI Challenge · Модель памяти",
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="expanded",
)
autoscroll.install()
enter_submit.install()
memory_page.render()
