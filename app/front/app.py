"""AI Chat — Streamlit frontend.

Renders the chat, the streaming answers and the reasoning trace, and posts to
the FastAPI backend at API_BASE_URL.
"""

from __future__ import annotations

import json
import os
import time
from typing import Iterator

import httpx
import streamlit as st

API_BASE = os.getenv("API_BASE_URL", "http://localhost:8000").rstrip("/")
TIMEOUT = httpx.Timeout(300.0, connect=10.0)

REASONING_LABELS = {
    "off": "Выключен",
    "low": "Низкий",
    "medium": "Средний",
    "high": "Высокий",
}
EXAMPLE_PROMPTS = [
    "Объясни разницу между RAG и fine-tuning",
    "Напиши SQL-запрос: топ-5 клиентов по выручке",
    "Составь план изучения Python на 2 недели",
]

st.set_page_config(
    page_title="AI Chat",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
      .reasoning-text { font-size: 0.86rem; opacity: .85; line-height: 1.45; }
      .meta-line { font-size: 0.75rem; opacity: .55; }
      div[data-testid="stChatMessage"] { padding-bottom: .25rem; }
    </style>
    """,
    unsafe_allow_html=True,
)


# --- backend calls -----------------------------------------------------------
@st.cache_data(ttl=30, show_spinner=False)
def load_backend() -> dict:
    """Models + health in one shot; cached so the sidebar is cheap to render."""
    result = {"models": [], "health": None, "error": None}
    try:
        with httpx.Client(timeout=10.0) as client:
            health = client.get(f"{API_BASE}/api/health").json()
            models = client.get(f"{API_BASE}/api/models").json()
        result["health"] = health
        result["models"] = models
    except Exception as exc:  # noqa: BLE001 - surfaced in the sidebar
        result["error"] = f"{type(exc).__name__}: {exc}"
    return result


def parse_sse(lines: Iterator[str]) -> Iterator[tuple[str, dict]]:
    event, data = None, []
    for line in lines:
        if line == "":
            if event:
                try:
                    yield event, json.loads("".join(data) or "{}")
                except json.JSONDecodeError:
                    yield event, {}
            event, data = None, []
        elif line.startswith("event:"):
            event = line[6:].strip()
        elif line.startswith("data:"):
            data.append(line[5:].strip())
    if event:
        try:
            yield event, json.loads("".join(data) or "{}")
        except json.JSONDecodeError:
            yield event, {}


def stream_chat(payload: dict) -> Iterator[tuple[str, dict]]:
    with httpx.stream("POST", f"{API_BASE}/api/chat", json=payload, timeout=TIMEOUT) as response:
        if response.status_code != 200:
            response.read()
            try:
                detail = response.json().get("detail", response.text)
            except Exception:  # noqa: BLE001
                detail = response.text
            yield "error", {"message": f"API {response.status_code}: {detail}"}
            return
        yield from parse_sse(response.iter_lines())


# --- session state -----------------------------------------------------------
st.session_state.setdefault("messages", [])
st.session_state.setdefault("pending_prompt", None)


def build_history(system_prompt: str, messages: list[dict]) -> list[dict]:
    history: list[dict] = []
    if system_prompt.strip():
        history.append({"role": "system", "content": system_prompt.strip()})
    # keep the tail bounded so very long chats don't trip the API limits
    for message in messages[-40:]:
        if message.get("failed"):
            continue
        history.append({"role": message["role"], "content": message["content"]})
    return history


def model_by_id(models: list[dict], model_id: str) -> dict:
    for model in models:
        if model["id"] == model_id:
            return model
    return models[0]


def render_history() -> None:
    for message in st.session_state.messages:
        avatar = "🧑" if message["role"] == "user" else "🤖"
        with st.chat_message(message["role"], avatar=avatar):
            if message.get("reasoning"):
                with st.expander("🧠 Размышления модели", expanded=False):
                    st.markdown(
                        f'<div class="reasoning-text">{message["reasoning"]}</div>',
                        unsafe_allow_html=True,
                    )
            if message.get("error"):
                st.error(message["content"])
            else:
                st.markdown(message["content"])
            if message.get("meta"):
                st.markdown(f'<div class="meta-line">{message["meta"]}</div>', unsafe_allow_html=True)


def run_turn(cfg: dict) -> None:
    """Stream one assistant answer into the chat and persist it."""
    payload = {
        "model": cfg["model"]["id"],
        "messages": build_history(cfg["system_prompt"], st.session_state.messages),
        "temperature": cfg["temperature"],
        "reasoning": cfg["reasoning"],
        "max_tokens": cfg["max_tokens"],
    }
    started = time.perf_counter()
    answer, reasoning = "", ""
    meta, error = "", None

    with st.chat_message("assistant", avatar="🤖"):
        reasoning_slot = None
        if cfg["reasoning"] != "off" and cfg["model"]["supports_reasoning"]:
            box = st.expander("🧠 Размышления модели", expanded=True)
            reasoning_slot = box.empty()
        answer_slot = st.empty()
        meta_slot = st.empty()
        answer_slot.markdown("▌")

        for event, data in stream_chat(payload):
            if event == "reasoning":
                reasoning += data.get("text", "")
                if reasoning_slot is not None:
                    reasoning_slot.markdown(
                        f'<div class="reasoning-text">{reasoning}</div>', unsafe_allow_html=True
                    )
            elif event == "delta":
                answer += data.get("text", "")
                answer_slot.markdown(answer + " ▌")
            elif event == "done":
                elapsed = data.get("elapsed_ms") or int((time.perf_counter() - started) * 1000)
                tokens = data.get("completion_tokens")
                meta = f"{payload['model']} · temp {payload['temperature']:.1f} · reasoning {payload['reasoning']} · {elapsed} ms"
                if tokens:
                    meta += f" · {tokens} tok"
            elif event == "error":
                error = data.get("message", "неизвестная ошибка")

        if error:
            answer_slot.error(error)
        else:
            answer_slot.markdown(answer)
        if meta:
            meta_slot.markdown(f'<div class="meta-line">{meta}</div>', unsafe_allow_html=True)

    st.session_state.messages.append(
        {
            "role": "assistant",
            "content": answer,
            "reasoning": reasoning,
            "meta": meta,
            "error": bool(error),
            "failed": bool(error),
        }
    )
    if error:
        st.toast(error, icon="⚠️")


# --- sidebar -----------------------------------------------------------------
backend = load_backend()
models = backend["models"]

with st.sidebar:
    st.title("🤖 AI Chat")
    if backend["error"]:
        st.error("API недоступен")
        st.caption(backend["error"])
        st.caption(f"Ожидаемый адрес: `{API_BASE}`")
        st.stop()
    else:
        health = backend["health"] or {}
        if health.get("status") == "ok":
            st.caption(f"🟢 {health.get('provider', '')}")
        else:
            st.caption(f"🟠 {health.get('provider', '')}")
            st.warning(health.get("detail", "Провайдер не настроен"))

    if not models:
        st.error("API вернул пустой список моделей")
        st.stop()

    st.divider()
    st.subheader("Параметры")

    model_id = st.selectbox(
        "Модель",
        options=[m["id"] for m in models],
        format_func=lambda mid: model_by_id(models, mid)["label"],
        help="Список приходит из /api/models",
    )
    model = model_by_id(models, model_id)
    if model.get("description"):
        st.caption(model["description"])

    temperature = st.slider(
        "Температура",
        min_value=0.0,
        max_value=2.0,
        value=0.7,
        step=0.1,
        disabled=not model["supports_temperature"],
        help="Выше — креативнее, ниже — стабильнее",
    )
    if not model["supports_temperature"]:
        st.caption("⚠️ Эта модель не принимает temperature — параметр не отправляется")

    reasoning = st.selectbox(
        "Reasoning",
        options=list(REASONING_LABELS),
        index=0,
        format_func=lambda key: REASONING_LABELS[key],
        disabled=not model["supports_reasoning"],
        help="Глубина «размышлений» (reasoning_effort)",
    )
    if not model["supports_reasoning"]:
        st.caption("⚠️ Модель не поддерживает reasoning")

    max_tokens = st.slider("Max tokens", 256, 8192, 1024, step=256)
    system_prompt = st.text_area(
        "Системный промпт",
        value="Ты — полезный ассистент. Отвечай по делу.",
        height=90,
    )

    st.divider()
    col_a, col_b = st.columns(2)
    with col_a:
        if st.button("Очистить", use_container_width=True):
            st.session_state.messages = []
            st.rerun()
    with col_b:
        st.download_button(
            "Экспорт",
            data=json.dumps(st.session_state.messages, ensure_ascii=False, indent=2),
            file_name="chat.json",
            mime="application/json",
            use_container_width=True,
            disabled=not st.session_state.messages,
        )

cfg = {
    "model": model,
    "temperature": temperature,
    "reasoning": reasoning,
    "max_tokens": max_tokens,
    "system_prompt": system_prompt,
}

# --- main area ---------------------------------------------------------------
st.markdown("### Диалог")

if not st.session_state.messages:
    st.caption("Начни с примера или напиши свой вопрос.")
    cols = st.columns(len(EXAMPLE_PROMPTS))
    for column, example in zip(cols, EXAMPLE_PROMPTS):
        with column:
            if st.button(example, use_container_width=True):
                st.session_state.pending_prompt = example
                st.rerun()

render_history()

prompt = st.chat_input("Спроси что-нибудь…")

if prompt is None and st.session_state.pending_prompt:
    prompt = st.session_state.pending_prompt
    st.session_state.pending_prompt = None

if prompt:
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user", avatar="🧑"):
        st.markdown(prompt)
    run_turn(cfg)
