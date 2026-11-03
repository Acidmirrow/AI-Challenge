"""AI Chat — Streamlit frontend.

Sidebar: brand flush to the top, mock/API source switch, model picker in a
modal, Nixie-style sliders, reasoning and web-search controls.
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
LAMP = "#ff9d3d"

REASONING_LABELS = {
    "off": "Выключен",
    "none": "Без рассуждений",
    "minimal": "Минимальный",
    "low": "Низкий",
    "medium": "Средний",
    "high": "Высокий",
    "xhigh": "Очень высокий",
    "ultra": "Ультра",
    "max": "Максимальный",
}
SOURCE_LABELS = {"mock": "Демо (mock)", "deepseek": "DeepSeek API", "openai": "OpenAI API"}
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
    f"""
    <style>
      /* ---------- brand flush to the very top of the sidebar ---------- */
      [data-testid="stSidebarHeader"] {{ height: 0 !important; min-height: 0 !important; padding: 0 !important; }}
      [data-testid="stSidebarHeader"] > div {{ display: none !important; }}
      [data-testid="stSidebarUserContent"] {{ padding-top: 0 !important; }}
      [data-testid="stSidebarUserContent"] > div {{ gap: .55rem !important; }}
      .brand {{ font-size: 1.55rem; font-weight: 800; letter-spacing: .08em; line-height: 1.05;
                margin: -.1rem 0 .05rem 0; text-transform: uppercase; }}
      .brand span {{ color: {LAMP}; text-shadow: 0 0 12px rgba(255,157,61,.6); }}
      .brand-sub {{ font-size: .64rem; letter-spacing: .18em; text-transform: uppercase;
                    opacity: .42; margin: 0 0 .65rem 0; }}
      /* model picker: the popover trigger is the button, panel drops below it */
      [data-testid="stPopover"] button[data-testid="stPopoverButton"] {{
          width: 100%; justify-content: center; font-weight: 600;
          background: linear-gradient(180deg, #8b6bff, #6f4ae6) !important;
          color: #fff !important; border: 1px solid #7a55f0 !important;
          box-shadow: 0 4px 14px rgba(124,92,255,.25);
      }}
      [data-testid="stPopoverBody"], [role="dialog"] {{ min-width: 15rem; max-width: 18rem; }}

      /* status badge: provider name only, never a link */
      .provider-badge {{ font-size: .8rem; opacity: .85; margin: -.15rem 0 .35rem 0; cursor: default; }}
      .provider-badge b {{ font-weight: 600; }}

      /* ---------- Nixie readout ---------- */
      .nixie {{ display: flex; gap: 6px; margin: .05rem 0 .55rem 0;
                filter: drop-shadow(0 0 10px rgba(255,140,40,.18)); }}
      .nixie .tube {{
          position: relative; display: inline-flex; align-items: center; justify-content: center;
          width: 1.6rem; height: 2.2rem; border-radius: .55rem;
          background: radial-gradient(130% 120% at 50% 12%, #26190f 0%, #100b07 55%, #040302 100%);
          border: 1px solid #33261a;
          box-shadow: inset 0 0 14px rgba(255,140,40,.20),
                      inset 0 -8px 12px rgba(0,0,0,.75),
                      0 1px 0 rgba(255,255,255,.05);
      }}
      .nixie .tube::after {{
          content: ""; position: absolute; inset: 2px; border-radius: .42rem;
          background: linear-gradient(180deg, rgba(255,255,255,.07), transparent 45%);
          pointer-events: none;
      }}
      .nixie .glow {{
          font-family: "SF Mono", "Menlo", "Consolas", monospace;
          font-size: 1.12rem; font-weight: 600; color: #ffc078;
          text-shadow: 0 0 4px {LAMP}, 0 0 10px rgba(255,157,61,.6), 0 0 20px rgba(255,110,0,.32);
      }}
      .nixie .dot {{ display: inline-flex; align-items: flex-end; padding-bottom: .45rem;
                     font-family: "SF Mono", monospace; color: #ffc078; font-size: .95rem;
                     text-shadow: 0 0 8px rgba(255,157,61,.7); }}

      /* ---------- sliders: amber track + glowing thumb ---------- */
      [data-testid="stSlider"] {{ padding-bottom: .1rem; }}
      [data-testid="stSliderThumbValue"] {{ display: none !important; }}
      [data-testid="stSliderTickBar"] {{ opacity: .45; font-family: "SF Mono", monospace; }}
      [data-testid="stSlider"] [role="group"] > div > div:first-child {{
          height: 8px !important; border-radius: 6px !important;
          background: linear-gradient(90deg, #3a2410, #14100b) !important;
          box-shadow: inset 0 1px 4px rgba(0,0,0,.9), 0 0 6px rgba(255,140,40,.12);
      }}
      /* thumb: the wrapper carries an inline transform, so only that one is hit */
      [data-testid="stSlider"] [role="group"] > div > div[style*="position: absolute"] {{
          width: 1.2rem !important; height: 1.2rem !important; border-radius: 50% !important;
          background: radial-gradient(circle at 50% 35%, #ffe3bd, {LAMP} 48%, #c9611a 76%, #5c2a06 100%) !important;
          border: 1px solid #63330f !important;
          box-shadow: 0 0 12px rgba(255,157,61,.95), 0 0 26px rgba(255,120,0,.5) !important;
      }}

      /* ---------- misc ---------- */
      .reasoning-text {{ font-size: .86rem; opacity: .85; line-height: 1.45; }}
      .meta-line {{ font-size: .75rem; opacity: .55; }}
      div[data-testid="stChatMessage"] {{ padding-bottom: .25rem; }}
    </style>
    """,
    unsafe_allow_html=True,
)


# --- backend calls -----------------------------------------------------------
@st.cache_data(ttl=30, show_spinner=False)
def load_backend() -> dict:
    """Models + health in one shot; cached so the sidebar is cheap to render."""
    result: dict = {"models": [], "health": None, "search_backends": [], "error": None}
    try:
        with httpx.Client(timeout=10.0) as client:
            result["health"] = client.get(f"{API_BASE}/api/health").json()
            result["models"] = client.get(f"{API_BASE}/api/models").json()
            result["search_backends"] = client.get(f"{API_BASE}/api/search/backends").json()
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
st.session_state.setdefault("selected_model", None)


def nixie_digits(text: str) -> str:
    """Render a value as lamp-clock tubes: one tube per character."""
    cells = []
    for char in text:
        if char in ".,":
            cells.append(f'<span class="dot">{char}</span>')
        else:
            cells.append(f'<span class="tube"><span class="glow">{char}</span></span>')
    return f'<div class="nixie">{"".join(cells)}</div>'


def nixie_slider(
    label: str,
    *,
    min_value,
    max_value,
    step,
    default,
    key: str,
    fmt,
    disabled: bool = False,
    help: str | None = None,
):
    """Streamlit slider with a lamp-clock readout rendered above it."""
    readout = st.empty()
    kwargs = dict(
        label=label,
        min_value=min_value,
        max_value=max_value,
        step=step,
        key=key,
        disabled=disabled,
        help=help,
    )
    if key not in st.session_state:
        kwargs["value"] = default
    value = st.slider(**kwargs)
    readout.markdown(nixie_digits(fmt(value)), unsafe_allow_html=True)
    return value


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


def sources_markdown(sources: list[dict]) -> str:
    lines = []
    for item in sources:
        snippet = (item.get("snippet") or "").strip()
        if len(snippet) > 220:
            snippet = snippet[:220] + "…"
        title = item.get("title") or item.get("url", "")
        line = f"- [{title}]({item.get('url', '')})"
        if snippet:
            line += f" — {snippet}"
        lines.append(line)
    return "\n".join(lines)


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
            if message.get("sources"):
                with st.expander(f"🔎 Источники ({len(message['sources'])})", expanded=False):
                    st.markdown(sources_markdown(message["sources"]))
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
        "web_search": cfg["web_search"],
        "search_backend": cfg["search_backend"],
    }
    started = time.perf_counter()
    answer, reasoning = "", ""
    meta, error = "", None
    sources: list[dict] = []
    search_backend = ""

    with st.chat_message("assistant", avatar="🤖"):
        reasoning_slot = None
        if cfg["reasoning"] != "off" and cfg["model"]["supports_reasoning"]:
            box = st.expander("🧠 Размышления модели", expanded=True)
            reasoning_slot = box.empty()
        search_slot = st.empty()
        answer_slot = st.empty()
        meta_slot = st.empty()
        answer_slot.markdown("▌")

        for event, data in stream_chat(payload):
            if event == "search_start":
                search_slot.caption(f"🔎 Ищу в интернете: {data.get('query', '')}…")
            elif event == "search":
                search_backend = data.get("backend", "")
                sources = data.get("results") or []
                if sources:
                    with search_slot.container():
                        with st.expander(f"🔎 Источники ({len(sources)}) · {search_backend}", expanded=False):
                            st.markdown(sources_markdown(sources))
                else:
                    search_slot.caption(f"⚠️ Поиск без результатов ({data.get('error') or 'пусто'})")
            elif event == "reasoning":
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
                meta = (
                    f"{payload['model']} · temp {payload['temperature']:.1f} · "
                    f"reasoning {payload['reasoning']} · {elapsed} ms"
                )
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
            "sources": sources,
            "search_backend": search_backend,
            "error": bool(error),
            "failed": bool(error),
        }
    )
    if error:
        st.toast(error, icon="⚠️")


def model_picker(options: list[dict], selected_id: str) -> None:
    """Dropdown panel (st.popover) with the models of the current source."""
    st.caption("Каталог из `GET /api/models`")
    for model in options:
        mark = "✅ " if model["id"] == selected_id else ""
        if st.button(
            f"{mark}{model['label']}",
            key=f"pick::{model['id']}",
            use_container_width=True,
            help=model.get("description") or None,
        ):
            st.session_state.selected_model = model["id"]
            st.rerun()
        details = [f"`{model['id']}`"]
        levels = model.get("reasoning_levels") or []
        if levels:
            details.append(f"reasoning: {levels[0]}…{levels[-1]}" if len(levels) > 1 else f"reasoning: {levels[0]}")
        if not model["supports_temperature"]:
            details.append("без temperature")
        st.caption(" · ".join(details))


# --- sidebar -----------------------------------------------------------------
backend = load_backend()
models = backend["models"]

with st.sidebar:
    st.markdown('<div class="brand">AI <span>Chat</span></div>', unsafe_allow_html=True)
    st.markdown('<div class="brand-sub">lesson 01 · chat client</div>', unsafe_allow_html=True)

    if backend["error"]:
        st.error("API недоступен")
        st.caption(backend["error"])
        st.caption(f"Ожидаемый адрес: `{API_BASE}`")
        st.stop()

    health = backend["health"] or {}
    # "deepseek @ https://api.deepseek.com/v1" → just the provider name
    name = health.get("provider", "").partition(" @ ")[0] or "—"
    status_dot = "🟢" if health.get("status") == "ok" else "🟠"
    st.markdown(
        f'<div class="provider-badge">{status_dot} <b>{name}</b></div>',
        unsafe_allow_html=True,
    )
    if health.get("status") != "ok":
        st.warning(health.get("detail", "Провайдер не настроен"))

    if not models:
        st.error("API вернул пустой список моделей")
        st.stop()

    # --- source switch: offline mock vs. the real API -------------------------
    provider_order = sorted(
        {m["provider"] for m in models},
        key=lambda name: (name != "mock", name),
    )
    source = st.radio(
        "Источник модели",
        options=provider_order,
        format_func=lambda name: SOURCE_LABELS.get(name, name),
        horizontal=True,
        key="model_source",
    )
    source_models = [m for m in models if m["provider"] == source]
    if not source_models:
        st.warning("Для этого источника нет моделей")
        st.stop()

    # --- model picker lives in a modal ---------------------------------------
    current = next(
        (m for m in source_models if m["id"] == st.session_state.selected_model),
        source_models[0],
    )
    st.session_state.selected_model = current["id"]
    with st.popover(f"⚙  {current['label']}  ▾", use_container_width=True):
        model_picker(source_models, current["id"])
    if current.get("description"):
        st.caption(current["description"])

    st.divider()

    # --- Nixie sliders --------------------------------------------------------
    temperature = nixie_slider(
        "Температура",
        min_value=0.0,
        max_value=2.0,
        step=0.1,
        default=0.7,
        key="temperature",
        fmt=lambda value: f"{value:.1f}",
        disabled=not current["supports_temperature"],
        help="Выше — креативнее, ниже — стабильнее",
    )
    if not current["supports_temperature"]:
        st.caption("⚠️ Модель не принимает temperature")

    max_tokens = nixie_slider(
        "Max tokens",
        min_value=256,
        max_value=8192,
        step=256,
        default=1024,
        key="max_tokens",
        fmt=lambda value: f"{int(value):04d}",
        help="Предел длины ответа",
    )

    levels = current.get("reasoning_levels") or []
    if levels:
        reasoning = st.selectbox(
            "Reasoning",
            options=levels,
            index=levels.index("high") if "high" in levels else 0,
            format_func=lambda key: REASONING_LABELS.get(key, key),
            key=f"reasoning::{current['id']}",
            help="Глубина «размышлений» — значения из /api/models",
        )
    else:
        reasoning = "off"
        st.caption("Reasoning: модель не поддерживает (параметр не отправляется)")

    search_available = (health or {}).get("web_search", "off")
    backends = backend.get("search_backends") or []
    usable = [b for b in backends if b["available"]]
    web_search = st.toggle(
        "🔎 Искать в интернете",
        value=False,
        disabled=not usable,
        help="Перед ответом API найдёт источники и передаст их модели",
    )

    search_backend = None
    if not usable:
        st.caption("⚠️ Поиск отключён в конфигурации API")
    else:
        default_index = next(
            (i for i, b in enumerate(usable) if b["name"] == search_available),
            0,
        )
        search_backend = st.selectbox(
            "Провайдер поиска",
            options=[b["name"] for b in usable],
            index=default_index,
            format_func=lambda name: next(
                (b["label"] for b in usable if b["name"] == name), name
            ),
            disabled=not web_search,
            key="search_backend_choice",
            help="Кто выполняет поиск. DuckDuckGo и Bing работают без ключа.",
        )
        chosen = next((b for b in usable if b["name"] == search_backend), None)
        st.caption(chosen["note"] if chosen and chosen.get("note") else "")
        missing = [b for b in backends if not b["available"]]
        if missing:
            st.caption("Недоступны без ключа: " + ", ".join(b["label"] for b in missing))

    with st.expander("Системный промпт", expanded=False):
        system_prompt = st.text_area(
            "Инструкция",
            value="Ты — полезный ассистент. Отвечай по делу.",
            height=110,
            label_visibility="collapsed",
        )

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
    "model": current,
    "temperature": temperature,
    "reasoning": reasoning,
    "max_tokens": max_tokens,
    "system_prompt": system_prompt,
    "web_search": bool(web_search),
    "search_backend": search_backend,
}

# --- main area ---------------------------------------------------------------
if not st.session_state.messages:
    st.markdown("### Диалог")
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
