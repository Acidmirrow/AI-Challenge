"""Отдельный фронт урока 08: работа с токенами."""

from __future__ import annotations

import streamlit as st

import token_page
from common import BASE_CSS

st.set_page_config(
    page_title="AI Challenge · Токены",
    page_icon="🔢",
    layout="wide",
    initial_sidebar_state="expanded",
)
st.markdown(f"<style>{BASE_CSS}</style>", unsafe_allow_html=True)

with st.sidebar:
    st.markdown('<div class="brand">AI <span>Challenge</span></div>', unsafe_allow_html=True)
    st.markdown('<div class="brand-sub">урок 08 · работа с токенами</div>', unsafe_allow_html=True)
    st.divider()

token_page.render()
