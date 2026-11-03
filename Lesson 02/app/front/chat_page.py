"""Страница «Чат» — фронт урока 01 внутри объединённого приложения.

Код урока 01 не меняется: страница ходит в его API по адресу CHAT_API_BASE_URL.
"""

from __future__ import annotations

import json
import time

import httpx
import streamlit as st

from common import (
    CHAT_API,
    REASONING_LABELS,
    SOURCE_LABELS,
    nixie_digits,
    post_stream,
)

EXAMPLE_PROMPTS = [
    "Объясни разницу между RAG и fine-tuning",
    "Напиши SQL-запрос: топ-5 клиентов по выручке",
    "Составь план изучения Python на 2 недели",
]


@st.cache_data(ttl=20, show_spinner=False)
def load_chat_backend() -> dict:
    result: dict = {"models": [], "health": None, "search_backends": [], "error": None}
    try:
        with httpx.Client(timeout=10.0) as client:
            result["health"] = client.get(f"{CHAT_API}/api/health").json()
            result["models"] = client.get(f"{CHAT_API}/api/models").json()
            result["search_backends"] = client.get(f"{CHAT_API}/api/search/backends").json()
    except Exception as exc:  # noqa: BLE001
        result["error"] = f"{type(exc).__name__}: {exc}"
    return result


def _nixie_slider(label, *, min_value, max_value, step, default, key, fmt, disabled=False, help=None):
    readout = st.empty()
    kwargs = dict(label=label, min_value=min_value, max_value=max_value, step=step,
                  key=key, disabled=disabled, help=help)
    if key not in st.session_state:
        kwargs["value"] = default
    value = st.slider(**kwargs)
    readout.markdown(nixie_digits(fmt(value)), unsafe_allow_html=True)
    return value


def _sources_md(sources: list[dict]) -> str:
    lines = []
    for item in sources:
        snippet = (item.get("snippet") or "").strip()
        if len(snippet) > 200:
            snippet = snippet[:200] + "…"
        title = item.get("title") or item.get("url", "")
        line = f"- [{title}]({item.get('url', '')})"
        if snippet:
            line += f" — {snippet}"
        lines.append(line)
    return "\n".join(lines)


def _history(system_prompt: str, messages: list[dict]) -> list[dict]:
    history = []
    if system_prompt.strip():
        history.append({"role": "system", "content": system_prompt.strip()})
    for message in messages[-40:]:
        if message.get("failed"):
            continue
        history.append({"role": message["role"], "content": message["content"]})
    return history


def _render_history() -> None:
    for message in st.session_state.chat_messages:
        avatar = "🧑" if message["role"] == "user" else "🤖"
        with st.chat_message(message["role"], avatar=avatar):
            if message.get("reasoning"):
                with st.expander("🧠 Размышления модели", expanded=False):
                    st.markdown(f'<div class="reasoning-text">{message["reasoning"]}</div>',
                                unsafe_allow_html=True)
            if message.get("sources"):
                with st.expander(f"🔎 Источники ({len(message['sources'])})", expanded=False):
                    st.markdown(_sources_md(message["sources"]))
            if message.get("error"):
                st.error(message["content"])
            else:
                st.markdown(message["content"])
            if message.get("meta"):
                st.markdown(f'<div class="meta-line">{message["meta"]}</div>', unsafe_allow_html=True)


def _run_turn(cfg: dict) -> None:
    payload = {
        "model": cfg["model"]["id"],
        "messages": _history(cfg["system_prompt"], st.session_state.chat_messages),
        "temperature": cfg["temperature"],
        "reasoning": cfg["reasoning"],
        "max_tokens": cfg["max_tokens"],
        "web_search": cfg["web_search"],
        "search_backend": cfg["search_backend"],
    }
    started = time.perf_counter()
    answer, reasoning, meta, error = "", "", "", None
    sources: list[dict] = []
    search_backend = ""

    with st.chat_message("assistant", avatar="🤖"):
        reasoning_slot = None
        if cfg["reasoning"] != "off" and cfg["model"]["supports_reasoning"]:
            reasoning_slot = st.expander("🧠 Размышления модели", expanded=True).empty()
        search_slot = st.empty()
        answer_slot = st.empty()
        meta_slot = st.empty()
        answer_slot.markdown("▌")

        for event, data in post_stream("/api/chat", payload, CHAT_API):
            if event == "search_start":
                search_slot.caption(f"🔎 Ищу в интернете: {data.get('query', '')}…")
            elif event == "search":
                search_backend = data.get("backend", "")
                sources = data.get("results") or []
                if sources:
                    with search_slot.container():
                        with st.expander(f"🔎 Источники ({len(sources)}) · {search_backend}", expanded=False):
                            st.markdown(_sources_md(sources))
                else:
                    search_slot.caption(f"⚠️ Поиск без результатов ({data.get('error') or 'пусто'})")
            elif event == "reasoning":
                reasoning += data.get("text", "")
                if reasoning_slot is not None:
                    reasoning_slot.markdown(f'<div class="reasoning-text">{reasoning}</div>',
                                            unsafe_allow_html=True)
            elif event == "delta":
                answer += data.get("text", "")
                answer_slot.markdown(answer + " ▌")
            elif event == "done":
                elapsed = data.get("elapsed_ms") or int((time.perf_counter() - started) * 1000)
                tokens = data.get("completion_tokens")
                meta = (f"{payload['model']} · temp {payload['temperature']:.1f} · "
                        f"reasoning {payload['reasoning']} · {elapsed} ms")
                if tokens:
                    meta += f" · {tokens} tok"
            elif event == "error":
                error = data.get("message", "неизвестная ошибка")

        answer_slot.error(error) if error else answer_slot.markdown(answer)
        if meta:
            meta_slot.markdown(f'<div class="meta-line">{meta}</div>', unsafe_allow_html=True)

    st.session_state.chat_messages.append(
        {
            "role": "assistant",
            "content": answer,
            "reasoning": reasoning,
            "meta": meta,
            "sources": sources,
            "search_backend": search_backend,
            "error": bool(error),
            "failed": bool(error),
        }
    )
    if error:
        st.toast(error, icon="⚠️")


def render() -> None:
    st.session_state.setdefault("chat_messages", [])
    st.session_state.setdefault("chat_pending", None)
    st.session_state.setdefault("ui_model", None)

    backend = load_chat_backend()
    models = backend["models"]

    with st.sidebar:
        if backend["error"]:
            st.error("API урока 01 недоступен")
            st.caption(backend["error"])
            st.caption(f"Адрес: `{CHAT_API}`")
            return

        health = backend["health"] or {}
        name = health.get("provider", "").partition(" @ ")[0] or "—"
        st.markdown(
            f'<div class="provider-badge">{"🟢" if health.get("status") == "ok" else "🟠"} <b>{name}</b></div>',
            unsafe_allow_html=True,
        )
        if not models:
            st.error("API вернул пустой список моделей")
            return

        providers = sorted({m["provider"] for m in models}, key=lambda p: (p != "mock", p))
        source = st.radio("Источник модели", options=providers,
                          format_func=lambda p: SOURCE_LABELS.get(p, p),
                          horizontal=True, key="ui_source")
        source_models = [m for m in models if m["provider"] == source]
        current = next((m for m in source_models if m["id"] == st.session_state.ui_model),
                       source_models[0])
        st.session_state.ui_model = current["id"]

        with st.popover(f"⚙  {current['label']}  ▾", use_container_width=True):
            st.caption("Каталог моделей урока 01")
            for option in source_models:
                mark = "✅ " if option["id"] == current["id"] else ""
                if st.button(f"{mark}{option['label']}", key=f"chat_pick::{option['id']}",
                             use_container_width=True):
                    st.session_state.ui_model = option["id"]
                    st.rerun()
                st.caption(f"`{option['id']}`")

        st.divider()

        temperature = _nixie_slider("Температура", min_value=0.0, max_value=2.0, step=0.1,
                                    default=0.7, key="chat_temperature",
                                    fmt=lambda v: f"{v:.1f}",
                                    disabled=not current["supports_temperature"])
        max_tokens = _nixie_slider("Max tokens", min_value=100, max_value=10_000, step=100,
                                   default=1_000, key="chat_max_tokens",
                                   fmt=lambda v: f"{int(v):05d}",
                                   help="Предел длины ответа: до 10 000 токенов")

        levels = current.get("reasoning_levels") or []
        if levels:
            # без «off»: у DeepSeek это «параметр не передан» → thinking включается сам
            reasoning = st.selectbox("Reasoning", options=levels,
                                     index=levels.index("none") if "none" in levels else 0,
                                     format_func=lambda k: REASONING_LABELS.get(k, k),
                                     key=f"chat_reasoning::{current['id']}")
        else:
            reasoning = "off"
            st.caption("Reasoning: модель не поддерживает")

        backends = backend["search_backends"] or []
        usable = [b for b in backends if b["available"]]
        web_search = st.toggle("🔎 Искать в интернете", value=False, disabled=not usable,
                               key="chat_web_search")
        search_backend = None
        if usable:
            default_index = next((i for i, b in enumerate(usable)
                                  if b["name"] == health.get("web_search")), 0)
            search_backend = st.selectbox(
                "Провайдер поиска",
                options=[b["name"] for b in usable],
                index=default_index,
                format_func=lambda n: next(b["label"] for b in usable if b["name"] == n),
                disabled=not web_search,
                key="chat_search_backend",
            )

        with st.expander("Системный промпт", expanded=False):
            system_prompt = st.text_area("Инструкция", value="Ты — полезный ассистент. Отвечай по делу.",
                                         height=100, label_visibility="collapsed",
                                         key="chat_system_prompt")

        col_a, col_b = st.columns(2)
        if col_a.button("Очистить", use_container_width=True, key="chat_clear"):
            st.session_state.chat_messages = []
            st.rerun()
        col_b.download_button(
            "Экспорт",
            data=json.dumps(st.session_state.chat_messages, ensure_ascii=False, indent=2),
            file_name="chat.json",
            mime="application/json",
            use_container_width=True,
            disabled=not st.session_state.chat_messages,
            key="chat_export",
        )

    cfg = {
        "model": current,
        "temperature": temperature,
        "reasoning": reasoning,
        "max_tokens": max_tokens,
        "system_prompt": system_prompt,
        "web_search": bool(web_search),
        "search_backend": search_backend,
    }

    if not st.session_state.chat_messages:
        st.markdown("### Диалог")
        st.caption("Начни с примера или напиши свой вопрос.")
        cols = st.columns(len(EXAMPLE_PROMPTS))
        for column, example in zip(cols, EXAMPLE_PROMPTS):
            if column.button(example, use_container_width=True, key=f"chat_ex::{example[:12]}"):
                st.session_state.chat_pending = example
                st.rerun()

    _render_history()

    prompt = st.chat_input("Спроси что-нибудь…", key="chat_input")
    if prompt is None and st.session_state.chat_pending:
        prompt = st.session_state.chat_pending
        st.session_state.chat_pending = None

    if prompt:
        st.session_state.chat_messages.append({"role": "user", "content": prompt})
        with st.chat_message("user", avatar="🧑"):
            st.markdown(prompt)
        _run_turn(cfg)
