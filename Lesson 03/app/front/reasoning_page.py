"""Страница «Способы рассуждений» — урок 03 внутри общего интерфейса."""

from __future__ import annotations

import json
import time

import httpx
import streamlit as st

from common import REASONING_API, REASONING_LABELS, nixie_digits, post_stream

DEFAULT_TASK = (
    "В корзине 5 яблок, 3 груши и 2 апельсина. Два яблока съели, "
    "а потом добавили 4 груши. Сколько всего фруктов в корзине?"
)



@st.cache_data(ttl=20, show_spinner=False)
def load_backend() -> dict:
    result: dict = {"health": None, "models": [], "strategies": [], "error": None}
    try:
        with httpx.Client(timeout=10.0) as client:
            result["health"] = client.get(f"{REASONING_API}/api/health").json()
            result["models"] = client.get(f"{REASONING_API}/api/models").json()
            result["strategies"] = client.get(f"{REASONING_API}/api/strategies").json()
    except Exception as exc:  # noqa: BLE001
        result["error"] = f"{type(exc).__name__}: {exc}"
    return result


def _nixie_slider(label, *, min_value, max_value, step, default, key, fmt, help=None):
    readout = st.empty()
    kwargs = dict(label=label, min_value=min_value, max_value=max_value, step=step, key=key, help=help)
    if key not in st.session_state:
        kwargs["value"] = default
    value = st.slider(**kwargs)
    readout.markdown(nixie_digits(fmt(value)), unsafe_allow_html=True)
    return value


def _render_message(message: dict) -> None:
    with st.chat_message(message["role"], avatar="🧑" if message["role"] == "user" else "🤖"):
        if message.get("reasoning"):
            title = f"🧠 {message.get('reasoning_title') or 'Рассуждение'}"
            with st.expander(title, expanded=False):
                st.markdown(f'<div class="reasoning-text">{message["reasoning"]}</div>',
                            unsafe_allow_html=True)
        st.markdown(message.get("content") or "…")
        if message.get("meta"):
            st.markdown(f'<div class="meta-line">{message["meta"]}</div>', unsafe_allow_html=True)


def render() -> None:
    backend = load_backend()

    if backend["error"]:
        st.error("API урока 03 недоступен")
        st.caption(backend["error"])
        st.caption(f"Адрес: `{REASONING_API}`. Поднять: `cd \"Lesson 03/app\" && docker compose up -d`")
        st.stop()

    models = backend["models"]
    strategies = backend["strategies"]
    strategy_by_id = {item["id"]: item for item in strategies}

    st.session_state.setdefault("ui_model", None)
    st.session_state.setdefault("rs_history", [])
    st.session_state.setdefault("rs_compare", None)

    mock_models = [m for m in models if m["provider"] == "mock"]
    api_models = [m for m in models if m["provider"] != "mock"]
    current = next((m for m in models if m["id"] == st.session_state.ui_model), None)
    if current is None:
        current = (api_models or mock_models)[0]
        st.session_state.ui_model = current["id"]

    with st.sidebar:
        health = backend["health"] or {}
        provider_name = health.get("provider", "").partition(" @ ")[0] or "—"
        st.markdown(
            f'<div class="provider-badge">{"🟢" if health.get("status") == "ok" else "🟠"} '
            f"<b>{provider_name}</b></div>",
            unsafe_allow_html=True,
        )

        with st.popover(f"⚙  {current['label']}  ▾", use_container_width=True):
            st.caption("Демо (офлайн)")
            for option in mock_models:
                mark = "✅ " if option["id"] == current["id"] else ""
                if st.button(f"{mark}{option['label']}", key=f"rs_pick::{option['id']}", use_container_width=True):
                    st.session_state.ui_model = option["id"]
                    st.rerun()
            if api_models:
                st.caption("DeepSeek API")
                for option in api_models:
                    mark = "✅ " if option["id"] == current["id"] else ""
                    if st.button(f"{mark}{option['label']}", key=f"rs_pick::{option['id']}", use_container_width=True):
                        st.session_state.ui_model = option["id"]
                        st.rerun()

        st.divider()

        # --- фильтры: только температура, reasoning и лимит токенов -------------
        temperature = _nixie_slider("Температура", min_value=0.0, max_value=2.0, step=0.1,
                                    default=0.3, key="rs_temperature", fmt=lambda v: f"{v:.1f}",
                                    help="Выше — разнообразнее и «смелее», ниже — стабильнее")

        levels = current.get("reasoning_levels") or []
        if levels:
            reasoning = st.selectbox("Reasoning", options=levels,
                                     index=levels.index("none") if "none" in levels else 0,
                                     format_func=lambda k: REASONING_LABELS.get(k, k),
                                     key=f"rs_reasoning::{current['id']}",
                                     help="Встроенные «размышления» модели — отдельно от стратегии")
        else:
            reasoning = "off"
            st.caption("Reasoning: модель без встроенных рассуждений")

        max_tokens = _nixie_slider("Max tokens", min_value=100, max_value=10_000, step=100,
                                   default=1_000, key="rs_max_tokens",
                                   fmt=lambda v: f"{int(v):05d}",
                                   help="Предел длины ответа: до 10 000 токенов")

    st.markdown("## Способы рассуждений")

    tab_chat, tab_compare = st.tabs(["Способы рассуждений", "Сравнение стратегий"])

    # -- чат со стратегией --------------------------------------------------------
    with tab_chat:
        strategy_id = st.radio(
            "Способ рассуждения",
            options=[item["id"] for item in strategies],
            format_func=lambda sid: strategy_by_id[sid]["label"],
            horizontal=True,
            key="rs_strategy",
        )
        spec = strategy_by_id[strategy_id]
        st.markdown(f'<div class="strategy-hint">{spec["description"]}</div>', unsafe_allow_html=True)
        with st.expander("System-промпт стратегии", expanded=False):
            st.code(spec["system_prompt"], language="text")

        for message in st.session_state.rs_history:
            _render_message(message)

        question = st.chat_input("Спроси что-нибудь…")
        if question:
            history = [
                {"role": item["role"], "content": item["content"]}
                for item in st.session_state.rs_history
            ] + [{"role": "user", "content": question}]
            st.session_state.rs_history.append({"role": "user", "content": question})
            _render_message(st.session_state.rs_history[-1])

            payload = {
                "model": current["id"],
                "messages": history,
                "strategy": strategy_id,
                "temperature": temperature,
                "reasoning": reasoning,
                "max_tokens": max_tokens,
            }
            started = time.perf_counter()
            with st.chat_message("assistant", avatar="🤖"):
                reasoning_box = st.expander("🧠 Модель думает…", expanded=True).empty()
                answer_box = st.empty()
                meta_box = st.empty()
                buffer, native = "", ""
                result, error = None, None
                for event, data in post_stream("/api/chat", payload, REASONING_API):
                    if event == "start":
                        answer_box.caption(f"{spec['label']} · {data.get('model')}")
                        buffer = ""
                    elif event == "reasoning":
                        native += data.get("text", "")
                        reasoning_box.markdown(f'<div class="reasoning-text">{native}</div>',
                                               unsafe_allow_html=True)
                    elif event == "delta":
                        buffer += data.get("text", "")
                        answer_box.markdown(buffer)
                    elif event == "result":
                        result = data
                    elif event == "error":
                        error = data

            if error:
                st.error(error.get("message", "ошибка"))
                st.caption(f"kind: `{error.get('kind', '?')}`")
            elif result:
                parts_reasoning = result.get("reasoning_part") or result.get("native_reasoning") or ""
                answer = result.get("answer_part") or result.get("raw_text") or ""
                elapsed = result.get("elapsed_ms") or int((time.perf_counter() - started) * 1000)
                tokens = (result.get("usage") or {}).get("completion_tokens")
                meta = (f"{result['strategy_label']} · {result['model']} · temp {temperature:.1f} · "
                        f"reasoning {reasoning} · {elapsed} ms")
                if tokens:
                    meta += f" · {tokens} tok"
                if result.get("truncated"):
                    meta += " · ⚠️ обрезано по max_tokens"
                st.session_state.rs_history.append({
                    "role": "assistant",
                    "content": answer,
                    "reasoning": parts_reasoning,
                    "reasoning_title": spec.get("reasoning_hint") or "Рассуждение",
                    "meta": meta,
                })
                if result.get("truncated"):
                    st.error(
                        f"Ответ оборван лимитом max_tokens = {result.get('max_tokens')}: "
                        "увеличьте «Max tokens» и повторите."
                    )
                st.rerun()

    # -- сравнение стратегий ------------------------------------------------------
    with tab_compare:
        st.caption("Одна и та же задача прогоняется через все стратегии. Смотрите на токены, "
                   "время и на то, сходится ли итоговый ответ.")
        task = st.text_area("Задача", value=DEFAULT_TASK, height=110, key="rs_compare_task")
        if st.button("⚖  Сравнить стратегии", type="primary", key="rs_compare_run"):
            if not task.strip():
                st.warning("Нужна задача")
            else:
                try:
                    with httpx.Client(timeout=300.0) as client:
                        response = client.post(
                            f"{REASONING_API}/api/compare",
                            json={
                                "model": current["id"],
                                "prompt": task.strip(),
                                "temperature": temperature,
                                "reasoning": reasoning,
                                "max_tokens": max_tokens,
                            },
                        )
                        response.raise_for_status()
                        st.session_state.rs_compare = response.json()
                except Exception as exc:  # noqa: BLE001
                    st.error(f"Не удалось сравнить: {type(exc).__name__}: {exc}")

        rows = st.session_state.rs_compare
        if rows:
            ok_rows = [item for item in rows if not item.get("error")]
            st.dataframe(
                [
                    {
                        "стратегия": item.get("strategy_label") or item["strategy"],
                        "токенов": (item.get("usage") or {}).get("completion_tokens"),
                        "мс": item.get("elapsed_ms"),
                        "рассуждение, симв.": len(item.get("reasoning") or ""),
                        "finish": item.get("finish_reason") or "—",
                        "ответ": (item.get("answer") or item.get("error") or "—")[:120],
                    }
                    for item in rows
                ],
                use_container_width=True,
                hide_index=True,
            )
            if len(ok_rows) > 1:
                answers = {item.get("answer", "").strip() for item in ok_rows}
                if len(answers) == 1:
                    st.success("Все стратегии дали одинаковый итоговый ответ — задача слишком простая, "
                               "чтобы увидеть разницу.")
                else:
                    st.info(f"Стратегии разошлись: {len(answers)} разных ответов из {len(ok_rows)}.")
            for item in rows:
                title = item.get("strategy_label") or item["strategy"]
                with st.expander(f"{title}"):
                    if item.get("error"):
                        st.error(item["error"])
                        continue
                    if item.get("reasoning"):
                        st.markdown(f'<div class="reasoning-text">{item["reasoning"]}</div>',
                                    unsafe_allow_html=True)
                    st.markdown("**Ответ:** " + (item.get("answer") or "—"))
        else:
            st.caption("Нажмите «Сравнить стратегии» — прогон идёт по очереди через все способы.")

    with st.sidebar:
        st.divider()
        st.caption(f"API урока 03: `{REASONING_API}`")
        if st.button("Очистить чат", use_container_width=True, key="rs_clear"):
            st.session_state.rs_history = []
            st.session_state.rs_compare = None
            st.rerun()
        if st.session_state.rs_history:
            with st.expander("Что отправлено в последнем запросе", expanded=False):
                last = [m for m in st.session_state.rs_history if m["role"] == "user"][-1]
                st.code(json.dumps({"system": spec["system_prompt"], "user": last["content"]},
                                   ensure_ascii=False, indent=2), language="json")
