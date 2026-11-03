"""Объединённый фронт: чат урока 01 и лаборатория форматов урока 02."""

from __future__ import annotations

import streamlit as st

import chat_page
import format_page
from common import BASE_CSS, CHAT_API, FORMAT_API

st.set_page_config(page_title="AI Challenge · UI", page_icon="🧠", layout="wide")

st.markdown(f"<style>{BASE_CSS}</style>", unsafe_allow_html=True)

with st.sidebar:
    st.markdown('<div class="brand">AI <span>Challenge</span></div>', unsafe_allow_html=True)
    st.markdown('<div class="brand-sub">уроки 01–02 · один интерфейс</div>', unsafe_allow_html=True)
    section = st.radio(
        "Раздел",
        options=["Чат (урок 01)", "Форматы ответа (урок 02)"],
        key="nav_section",
        help=f"Чат → {CHAT_API}, форматы → {FORMAT_API}",
    )
    st.divider()

if section.startswith("Чат"):
    chat_page.render()
else:
    format_page.render()
