"""Отдельный фронт урока 07: один экран сохранения контекста."""

from __future__ import annotations

import context_page
import streamlit as st

from common import BASE_CSS

st.set_page_config(
    page_title="AI Challenge · Контекст",
    page_icon="💾",
    layout="wide",
    initial_sidebar_state="expanded",
)
st.markdown(f"<style>{BASE_CSS}</style>", unsafe_allow_html=True)

with st.sidebar:
    st.markdown('<div class="brand">AI <span>Challenge</span></div>', unsafe_allow_html=True)
    st.markdown('<div class="brand-sub">урок 07 · сохранение контекста</div>', unsafe_allow_html=True)
    st.divider()

context_page.render()
