"""Отдельный фронт урока 14: инварианты и ограничения состояния."""

from __future__ import annotations

import streamlit as st
import autoscroll

import enter_submit
import lesson14_page

st.set_page_config(
    page_title="AI Challenge · Инварианты",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded",
)
autoscroll.install()
enter_submit.install()
lesson14_page.render()
