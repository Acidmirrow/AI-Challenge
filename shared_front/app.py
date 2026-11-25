"""Общий интерфейс AI Challenge: уроки 01–18 в одном Streamlit-приложении."""

from __future__ import annotations

import re

import streamlit as st
import streamlit.components.v1 as components

import agent_page
import autoscroll
import chat_page
import control_page
import enter_submit
import lesson10_page
import lesson13_page
import lesson14_page
import lesson15_page
import lesson16_page
import lesson17_page
import lesson18_page
import memory_page
import context_page
import format_page
import model_page
import personalization_page
import reasoning_page
import temp_page
import token_page
from common import BASE_CSS, CHAT_API, FORMAT_API, REASONING_API, TEMP_API

st.set_page_config(
    page_title="AI Challenge · UI", page_icon="🧠", layout="wide",
    initial_sidebar_state="expanded",
)
st.markdown(f"<style>{BASE_CSS}</style>", unsafe_allow_html=True)
enter_submit.install()
autoscroll.install()
st.markdown(
    """<style>
    .week-label { display: flex; justify-content: space-between; align-items: baseline;
                  margin: .8rem 0 .1rem 0; font-size: .63rem; letter-spacing: .16em;
                  text-transform: uppercase; opacity: .55; }
    .week-label span { color: #ff9d3d; letter-spacing: .08em; opacity: .9; }
    .week-sub { font-size: .66rem; opacity: .35; margin: 0 0 .35rem 0; }
    /* навигация по урокам — минималистичные строки, без рамок кнопок */
    .st-key-lesson_nav {
        gap: 5.33px !important;
        row-gap: 5.33px !important;
    }
    .st-key-lesson_nav button {
        justify-content: flex-start !important;
        width: 100% !important;
        min-height: 1.85rem !important;
        height: 1.85rem !important;
        padding: 0 .35rem !important;
        background: transparent !important;
        background-image: none !important;
        border: none !important;
        box-shadow: none !important;
        border-radius: .3rem !important;
        font-weight: 400 !important;
        font-size: .84rem !important;
        color: var(--text-color, #e6e8ef) !important;
        opacity: .55;
        transition: opacity .12s ease, background .12s ease;
    }
    .st-key-lesson_nav button:hover {
        opacity: 1;
        background: rgba(128, 128, 128, .10) !important;
    }
    .st-key-lesson_nav button[kind="primary"] {
        opacity: 1;
        font-weight: 600 !important;
        color: #ffb268 !important;
        background: transparent !important;
    }
    .st-key-lesson_nav button > div {
        justify-content: flex-start !important;
        width: 100% !important;
    }
    .st-key-lesson_nav button > div > span {
        width: 100% !important;
        justify-content: flex-start !important;
    }
    .st-key-lesson_nav button [data-testid="stMarkdownContainer"] {
        width: 100% !important;
        text-align: left !important;
    }
    .st-key-lesson_nav button p {
        font-size: .84rem !important;
        margin: 0 !important;
        text-align: left !important;
        width: 100% !important;
    }
    /* переключатель недель — одна строка, минималистично */
    .st-key-week_nav [data-testid="stRadioGroup"] {
        flex-wrap: nowrap !important;
        gap: .08rem !important;
        width: 100% !important;
        justify-content: space-between !important;
    }
    .st-key-week_nav [data-testid="stRadioOption"] {
        margin: 0 !important;
        padding: .08rem .18rem !important;
        opacity: .55;
        white-space: nowrap;
    }
    .st-key-week_nav [data-testid="stRadioOption"]:has(input:checked) {
        opacity: 1;
        color: #ffb268 !important;
    }
    .st-key-week_nav [data-testid="stRadioOption"] p {
        font-size: .78rem !important;
        margin: 0 !important;
    }
    </style>""",
    unsafe_allow_html=True,
)

SECTIONS = {
    "Чат (урок 01)": (chat_page, CHAT_API),
    "Форматы ответа (урок 02)": (format_page, FORMAT_API),
    "Способы рассуждений (урок 03)": (reasoning_page, REASONING_API),
    "Температура (урок 04)": (temp_page, TEMP_API),
    "Сравнение моделей (урок 05)": (model_page, ""),
    "ИИ-агент (урок 06)": (agent_page, ""),
    "Сохранение контекста (урок 07)": (context_page, ""),
    "Работа с токенами (урок 08)": (token_page, ""),
    "Управление контекстом: сжатие истории (урок 09)": (control_page, ""),
    "Управление контекстом: Сравнение стратегий (урок 10)": (lesson10_page, ""),
    "Модель памяти ассистента (урок 11)": (memory_page, ""),
    "Персонализация ассистента (урок 12)": (personalization_page, ""),
    "Состояние задачи (Task state machine) (урок 13)": (lesson13_page, ""),
    "Инварианты и ограничения состояния (урок 14)": (lesson14_page, ""),
    "Устаревание и конфликты памяти (урок 15)": (lesson15_page, ""),
    "Подключение MCP (урок 16)": (lesson16_page, ""),
    "Первый инструмент MCP (урок 17)": (lesson17_page, ""),
    "Планировщик и фоновые задачи (урок 18)": (lesson18_page, ""),
}


def _lesson_no(label: str) -> int:
    match = re.search(r"урок\s+(\d+)", label, flags=re.IGNORECASE)
    return int(match.group(1)) if match else 10_000


# Строгий порядок по номеру урока: новый урок всегда оказывается последним.
SECTIONS = dict(sorted(SECTIONS.items(), key=lambda item: _lesson_no(item[0])))

#: Курс рассчитан на пять недель по пять уроков; будущие недели видны сразу,
#: но показывают заглушку, пока в них нет материалов.
WEEK_COUNT = 5

with st.sidebar:
    st.markdown('<div class="brand">AI <span>Challenge</span></div>', unsafe_allow_html=True)
    st.markdown('<div class="brand-sub">уроки 01–18 · один интерфейс</div>', unsafe_allow_html=True)
    # По умолчанию открываем последний урок; выбор пользователя сохраняется в сессии.
    if "nav_section" not in st.session_state:
        st.session_state["nav_section"] = list(SECTIONS)[-1]
    section = st.session_state["nav_section"]

    weeks: dict[int, list[str]] = {week: [] for week in range(1, WEEK_COUNT + 1)}
    for label in SECTIONS:
        week_no = (_lesson_no(label) - 1) // 5 + 1
        if week_no in weeks:
            weeks[week_no].append(label)
    current_week = max((week for week, labels in weeks.items() if labels), default=1)

    if "nav_week" not in st.session_state:
        st.session_state["nav_week"] = (_lesson_no(section) - 1) // 5 + 1

    def _on_week_change() -> None:
        week_no = int(st.session_state.get("nav_week") or current_week)
        labels = weeks.get(week_no) or []
        if labels:
            st.session_state["nav_section"] = labels[0]

    st.markdown('<div class="week-label">Неделя</div>', unsafe_allow_html=True)
    with st.container(key="week_nav"):
        st.radio(
            "Неделя",
            options=list(range(1, WEEK_COUNT + 1)),
            format_func=lambda week_no: str(week_no),
            horizontal=True,
            key="nav_week",
            on_change=_on_week_change,
            label_visibility="collapsed",
        )

    selected_week = int(st.session_state["nav_week"])
    labels = weeks[selected_week]
    first = (selected_week - 1) * 5 + 1
    last = selected_week * 5
    if selected_week < current_week:
        status = "пройдена"
    elif selected_week == current_week:
        status = "текущая"
    else:
        status = "скоро"
    lesson_range = f"уроки {first:02d}–{last:02d}"
    st.markdown(
        f'<div class="week-sub">{lesson_range} · {status}</div>',
        unsafe_allow_html=True,
    )

    with st.container(key="lesson_nav"):
        for label in labels:
            active = label == section
            if st.button(
                ("●  " if active else "○  ") + label,
                key=f"nav_lesson::{label}",
                type="primary" if active else "secondary",
                use_container_width=True,
            ):
                st.session_state["nav_section"] = label
                st.rerun()
    st.divider()

if not labels:
    st.info(f"Неделя {selected_week}: уроки ещё не добавлены.")
    st.stop()

page, _base = SECTIONS[section]

# При смене урока возвращаем основной скролл к заголовку страницы.
# Повторные rerun-ы (например, после сообщения в чате) не сбрасывают позицию.
if st.session_state.get("_scroll_section") != section:
    st.session_state["_scroll_section"] = section
    components.html(
        """
        <script>
        const scrollToTop = () => {
          try {
            const doc = window.parent.document;
            const main = doc.getElementById("stMain")
              || doc.querySelector('[data-testid="stMain"]');
            if (main) main.scrollTo({top: 0, behavior: "instant"});
          } catch (e) {}
        };
        setTimeout(scrollToTop, 60);
        setTimeout(scrollToTop, 350);
        setTimeout(scrollToTop, 900);
        </script>
        """,
        height=0,
    )

page.render()
