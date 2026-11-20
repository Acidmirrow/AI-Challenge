"""Отдельный фронт урока 12: персонализация ассистента."""

from __future__ import annotations

import streamlit as st
import autoscroll

import enter_submit
import personalization_page

st.set_page_config(
    page_title="AI Challenge · Персонализация",
    page_icon="🪪",
    layout="wide",
    initial_sidebar_state="expanded",
)
autoscroll.install()
enter_submit.install()
personalization_page.render()
