"""Общий интерфейс AI Challenge: чат урока 01, форматы урока 02, рассуждения урока 03."""

from __future__ import annotations

import streamlit as st

import chat_page
import format_page
import model_page
import reasoning_page
import temp_page
from common import BASE_CSS, CHAT_API, FORMAT_API, REASONING_API, TEMP_API

st.set_page_config(page_title="AI Challenge · UI", page_icon="🧠", layout="wide")
st.markdown(f"<style>{BASE_CSS}</style>", unsafe_allow_html=True)

SECTIONS = {
    "Чат (урок 01)": (chat_page, CHAT_API),
    "Форматы ответа (урок 02)": (format_page, FORMAT_API),
    "Способы рассуждений (урок 03)": (reasoning_page, REASONING_API),
    "Температура (урок 04)": (temp_page, TEMP_API),
    "Сравнение моделей (урок 05)": (model_page, ""),
}

with st.sidebar:
    st.markdown('<div class="brand">AI <span>Challenge</span></div>', unsafe_allow_html=True)
    st.markdown('<div class="brand-sub">уроки 01–05 · один интерфейс</div>', unsafe_allow_html=True)
    section = st.radio(
        "Раздел",
        options=list(SECTIONS),
        key="nav_section",
        help="Чат → урок 01, форматы → урок 02, рассуждения → урок 03, "
             "температура → урок 04, сравнение моделей → урок 05",
    )
    st.divider()

page, _base = SECTIONS[section]
page.render()
