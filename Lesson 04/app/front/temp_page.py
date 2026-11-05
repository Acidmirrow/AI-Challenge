"""Страница «Температура» — лаборатория урока 04.

Одна ручка — температура. Один и тот же промпт уходит в модель при нескольких
значениях (по умолчанию 0, 0.7 и 1.2), а результат складывается в сравнительную
таблицу: видно, где ответ остаётся стабильным, а где начинает «плыть».
"""

from __future__ import annotations

import httpx
import pandas as pd
import streamlit as st

from common import (
    REASONING_LABELS,
    TEMP_API,
    nixie_digits,
    post_stream,
    model_picker,
    provider_badges,
)

#: Температуры по умолчанию: детерминированно / баланс / разброс
DEFAULT_TEMPERATURES = (0.0, 0.7, 1.2)

KIND_LABELS = {
    "single-answer": "один правильный ответ",
    "text": "генерация текста",
    "variants": "варианты названий",
}


@st.cache_data(ttl=20, show_spinner=False)
def load_backend() -> dict:
    result: dict = {"health": None, "models": [], "tasks": [], "providers": [], "error": None}
    try:
        with httpx.Client(timeout=10.0) as client:
            result["health"] = client.get(f"{TEMP_API}/api/health").json()
            result["models"] = client.get(f"{TEMP_API}/api/models").json()
            result["tasks"] = client.get(f"{TEMP_API}/api/tasks").json()
            result["providers"] = client.get(f"{TEMP_API}/api/providers/status").json()
    except Exception as exc:  # noqa: BLE001 - показываем в сайдбаре
        result["error"] = f"{type(exc).__name__}: {exc}"
    return result


def _apply_variant() -> None:
    """Callback: подставить текст выбранного варианта сложности."""
    cache = st.session_state.get("t04_variant_cache") or {}
    variant = cache.get(st.session_state.get("t04_variant") or "")
    if variant:
        st.session_state["t04_prompt"] = variant["text"]


def _nixie_slider(label, *, min_value, max_value, step, default, key, fmt, help=None):
    readout = st.empty()
    kwargs = dict(label=label, min_value=min_value, max_value=max_value, step=step,
                  key=key, help=help)
    if key not in st.session_state:
        kwargs["value"] = default
    value = st.slider(**kwargs)
    readout.markdown(nixie_digits(fmt(value)), unsafe_allow_html=True)
    return value


def _send_message(cfg: dict, prompt: str) -> None:
    """Отправить промпт в чат с текущей температурой и собрать ответ потоком."""
    st.session_state.t04_history.append({"role": "user", "content": prompt})
    with st.chat_message("user", avatar="🧑"):
        st.markdown(prompt)

    payload = {
        "model": cfg["model"]["id"],
        "messages": [
            {"role": item["role"], "content": item["content"]}
            for item in st.session_state.t04_history
        ],
        "temperature": cfg["temperature"],
        "reasoning": cfg["reasoning"],
        "max_tokens": cfg["max_tokens"],
    }

    answer, reasoning, meta = "", "", ""
    finish_reason = None
    with st.chat_message("assistant", avatar="🤖"):
        answer_slot = st.empty()
        meta_slot = st.empty()
        answer_slot.markdown("▌")

        for event, data in post_stream("/api/chat", payload, TEMP_API):
            if event == "reasoning":
                reasoning += data.get("text", "")
            elif event == "delta":
                answer += data.get("text", "")
                answer_slot.markdown(answer + " ▌")
            elif event == "done":
                tokens = data.get("completion_tokens")
                finish_reason = data.get("finish_reason")
                meta = (
                    f"temp {payload['temperature']:.1f} · "
                    f"{data.get('elapsed_ms', 0)} ms"
                )
                if tokens:
                    meta += f" · {tokens} tok"
                if finish_reason == "length":
                    meta += " · ⚠️ обрезано по max_tokens"
            elif event == "error":
                answer_slot.error(data.get("message", "ошибка"))

        if answer:
            answer_slot.markdown(answer)
        if meta:
            meta_slot.markdown(f'<div class="meta-line">{meta}</div>', unsafe_allow_html=True)
        if finish_reason == "length":
            st.error(
                f"Ответ не уместился в лимит max_tokens = {payload['max_tokens']} — текст оборван. "
                "Увеличьте «Max tokens» и повторите запрос."
            )

    st.session_state.t04_history.append(
        {
            "role": "assistant",
            "content": answer,
            "reasoning": reasoning,
            "meta": meta,
        }
    )


def _render_history() -> None:
    for message in st.session_state.t04_history:
        with st.chat_message(message["role"], avatar="🧑" if message["role"] == "user" else "🤖"):
            st.markdown(message["content"] or "—")
            if message.get("reasoning"):
                with st.expander("🧠 Размышления модели", expanded=False):
                    st.markdown(message["reasoning"])
            if message.get("meta"):
                st.markdown(f'<div class="meta-line">{message["meta"]}</div>',
                            unsafe_allow_html=True)


def render() -> None:
    backend = load_backend()
    models = [item for item in backend["models"] if item.get("provider") != "mock"] \
        or backend["models"]
    tasks = backend["tasks"]

    st.session_state.setdefault("t04_history", [])
    st.session_state.setdefault("t04_compare", None)
    st.session_state["t04_tasks_cache"] = {item["id"]: item for item in tasks}

    if backend["error"]:
        st.error("API урока 04 недоступен")
        st.caption(backend["error"])
        return

    if not models:
        st.error("API вернул пустой список моделей")
        return

    task_map = {item["id"]: item for item in tasks}
    if tasks and st.session_state.get("t04_task") not in task_map:
        st.session_state["t04_task"] = tasks[0]["id"]
    current_task = task_map.get(st.session_state.get("t04_task") or "")
    current_variants = current_task["variants"] if current_task else []
    variant_ids = [item["id"] for item in current_variants]
    if variant_ids and st.session_state.get("t04_variant") not in variant_ids:
        st.session_state["t04_variant"] = variant_ids[0]
    if current_variants and "t04_prompt" not in st.session_state:
        st.session_state["t04_prompt"] = current_variants[0]["text"]
    st.session_state["t04_variant_cache"] = {item["id"]: item for item in current_variants}

    # --- сайдбар: модель, температура, лимит ------------------------------------
    with st.sidebar:
        st.markdown(provider_badges(backend.get("providers") or []), unsafe_allow_html=True)

        ids = [item["id"] for item in models]
        if st.session_state.get("t04_model") not in ids:
            st.session_state["t04_model"] = ids[0]
        model_id = model_picker(
            models,
            st.session_state["t04_model"],
            key="t04_model",
            caption="Каталог моделей урока 04",
        )
        current = next(item for item in models if item["id"] == model_id)

        temperature = _nixie_slider(
            "Температура", min_value=0.0, max_value=2.0, step=0.1, default=0.7,
            key="t04_temperature", fmt=lambda value: f"{value:.1f}",
            help="0 — почти детерминированно, 1.2 — заметный разброс, выше 1.5 — риск бессвязности",
        )

        levels = list(current.get("reasoning_levels") or [])
        if levels:
            reasoning = st.selectbox(
                "Reasoning",
                options=levels,
                index=levels.index("none") if "none" in levels else 0,
                format_func=lambda key: REASONING_LABELS.get(key, key),
                key=f"t04_reasoning::{current['id']}",
            )
        else:
            reasoning = "off"
            st.caption("Reasoning: модель не поддерживает")

        max_tokens = _nixie_slider(
            "Max tokens", min_value=100, max_value=10_000, step=100, default=1_000,
            key="t04_max_tokens", fmt=lambda value: f"{int(value):05d}",
            help="Предел ответа для чата и для сравнения температур",
        )

        if st.button("Очистить чат", use_container_width=True, key="t04_clear"):
            st.session_state.t04_history = []
            st.session_state.t04_compare = None
            st.rerun()

    cfg = {
        "model": current,
        "temperature": float(temperature),
        "reasoning": reasoning,
        "max_tokens": int(max_tokens),
    }

    st.markdown("## Температура")
    st.caption(
        "Одна и та же модель, один и тот же промпт — разные температуры. "
        "0 — самый стабильный ответ, 0.7 — баланс, 1.2 — разброс и риск выдумки. "
        "Температура в сайдбаре действует на чат, три значения ниже — на сравнение."
    )

    # --- чат --------------------------------------------------------------------
    _render_history()
    prompt = st.chat_input("Спроси что-нибудь…")
    if prompt:
        _send_message(cfg, prompt)
        st.rerun()

    st.divider()

    # --- типовые промпты ---------------------------------------------------------
    st.markdown("### Типовые промпты")
    st.caption("Пять задач разной сложности: от арифметики с единственным ответом до головоломки.")

    if tasks:
        columns = st.columns(len(tasks))
        for column, task in zip(columns, tasks):
            with column:
                mark = "✅ " if task["id"] == st.session_state.get("t04_task") else ""
                if st.button(
                    f"{mark}{task['label']}",
                    key=f"t04_task_btn::{task['id']}",
                    use_container_width=True,
                    help=KIND_LABELS.get(task["kind"], task["kind"]),
                ):
                    first = task["variants"][0]
                    st.session_state["t04_task"] = task["id"]
                    st.session_state["t04_variant"] = first["id"]
                    st.session_state["t04_prompt"] = first["text"]
                    st.session_state["t04_compare"] = None
                    st.session_state["t04_analysis"] = None
                    st.rerun()

        variant_map = {item["id"]: item for item in current_variants}
        if variant_map:
            st.selectbox(
                "Сложность",
                options=list(variant_map),
                format_func=lambda vid: variant_map[vid]["complexity"],
                key="t04_variant",
                on_change=_apply_variant,
                help="Три варианта промпта выбранного типа: от low до high",
            )

    variant = st.session_state.get("t04_variant_cache", {}).get(
        st.session_state.get("t04_variant") or ""
    )
    st.text_area("Промпт", height=120, key="t04_prompt")
    if current_task and variant:
        details = [current_task["label"], f"сложность: {variant['complexity']}"]
        if variant.get("reference"):
            details.append(f"эталон: {variant['reference']}")
        st.caption(" · ".join(details))
        if variant.get("note"):
            st.caption(variant["note"])

    # --- сравнение температур ----------------------------------------------------
    st.markdown("### Сравнение температур")
    cols = st.columns(3)
    temperatures: list[float] = []
    for index, default in enumerate(DEFAULT_TEMPERATURES):
        with cols[index]:
            temperatures.append(
                st.number_input(
                    f"Температура {index + 1}",
                    min_value=0.0, max_value=2.0, step=0.1,
                    value=default,
                    key=f"t04_cmp_temp::{index}",
                )
            )

    repeats = st.slider(
        "Количество повторений",
        min_value=0, max_value=10, value=0, step=1,
        key="t04_cmp_repeats",
        help="0 — по одному запросу на температуру; N — ещё N независимых повторов. "
             "Повторы показывают разброс модели при одной и той же температуре.",
    )
    unique_temperatures = len(sorted({round(float(value), 2) for value in temperatures}))
    total_requests = (repeats + 1) * unique_temperatures
    st.caption(
        f"Запросов к модели: {total_requests} "
        f"({unique_temperatures} температур(ы) × {repeats + 1})"
    )

    if st.button("📊  Сравнить температуры", type="primary", key="t04_compare_run"):
        text = (st.session_state.get("t04_prompt") or "").strip()
        if not text:
            st.warning("Нужен промпт")
        else:
            with st.spinner("Модель отвечает при трёх температурах…"):
                try:
                    response = httpx.post(
                        f"{TEMP_API}/api/temperature/compare",
                        json={
                            "model": cfg["model"]["id"],
                            "prompt": text,
                            "task": st.session_state.get("t04_task") or "",
                            "temperatures": sorted({round(float(value), 2) for value in temperatures}),
                            "repeats": int(repeats),
                            "reasoning": cfg["reasoning"],
                            "max_tokens": cfg["max_tokens"],
                        },
                        timeout=300.0,
                    )
                    response.raise_for_status()
                    st.session_state.t04_compare = response.json()
                    st.session_state["t04_analysis"] = None
                except Exception as exc:  # noqa: BLE001 - показываем в UI
                    st.session_state.t04_compare = None
                    st.error(f"Не удалось получить ответы: {type(exc).__name__}: {exc}")

    compare = st.session_state.get("t04_compare")
    if compare:
        runs = compare.get("runs") or []
        spread = compare.get("spread") or {}

        rows = []
        for run in runs:
            rows.append({
                "Температура": f"{run['temperature']:.1f}",
                "Повтор": int(run.get("repeat") or 0) + 1,
                "Ответ": (run.get("answer") or run.get("error") or "—").replace("\n", " ")[:160],
                "Токены": (run.get("usage") or {}).get("completion_tokens", 0),
                "Время, мс": run.get("elapsed_ms", 0),
                "Лимит": "обрезан" if run.get("truncated") else "ок",
            })
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

        st.caption(
            f"Модель: {compare.get('model')} · разных ответов: "
            f"{spread.get('unique_answers', 0)} из {spread.get('answers', 0)} · "
            f"длина от {spread.get('min_length', 0)} до {spread.get('max_length', 0)} символов"
        )
        per_temperature = spread.get("per_temperature") or {}
        if per_temperature:
            stability = " · ".join(
                f"t={key}: {value.get('unique', 0)} из {value.get('runs', 0)}"
                for key, value in per_temperature.items()
            )
            st.caption(f"Повторы внутри температуры (разных ответов из запросов): {stability}")

        if spread.get("unique_answers", 0) <= 1 and len(runs) > 1:
            st.info("Ответы совпали: на этой задаче температура почти не влияет.")
        if spread.get("truncated"):
            st.warning(
                "Часть ответов оборвана лимитом max_tokens — увеличьте «Max tokens», "
                "иначе сравнение неполное."
            )

        for run in runs:
            title = (
                f"Температура {run['temperature']:.1f} · повтор "
                f"{int(run.get('repeat') or 0) + 1}"
            )
            with st.expander(title, expanded=False):
                if run.get("error"):
                    st.error(run["error"])
                    continue
                st.markdown(run.get("answer") or "—")
                if run.get("reasoning"):
                    st.caption("Размышления модели")
                    st.markdown(run["reasoning"])
                meta = [
                    f"токены: {(run.get('usage') or {}).get('completion_tokens', 0)}",
                    f"время: {run.get('elapsed_ms', 0)} мс",
                    f"finish: {run.get('finish_reason') or '—'}",
                ]
                st.caption(" · ".join(meta))

        # --- анализ ответов другой моделью --------------------------------------
        st.markdown("### Анализ ответов разных температур")
        st.caption(
            "Выберите модель-аналитик и нажмите кнопку: она сравнит ответы выше, "
            "проверит их по эталону (если он есть) и предложит подходящую температуру."
        )

        analyzer_ids = [item["id"] for item in models]
        analyzer_labels = {item["id"]: item["label"] for item in models}
        if st.session_state.get("t04_analyzer") not in analyzer_ids:
            st.session_state["t04_analyzer"] = cfg["model"]["id"]
        analyzer_id = st.selectbox(
            "Модель для анализа",
            options=analyzer_ids,
            format_func=lambda mid: f"{analyzer_labels[mid]} · {mid}",
            key="t04_analyzer",
        )

        if st.button("🔎  Проанализировать ответы", key="t04_analyze_run"):
            answers = [
                {
                    "temperature": run["temperature"],
                    "repeat": int(run.get("repeat") or 0),
                    "answer": run.get("answer") or "",
                }
                for run in runs
                if (run.get("answer") or "").strip()
            ]
            if not answers:
                st.warning("Нет ответов для анализа")
            else:
                with st.spinner("Модель-аналитик читает ответы…"):
                    try:
                        response = httpx.post(
                            f"{TEMP_API}/api/analyze",
                            json={
                                "model": analyzer_id,
                                "prompt": compare.get("prompt") or "",
                                "task": st.session_state.get("t04_task") or "",
                                "variant": st.session_state.get("t04_variant") or "",
                                "reference": (variant or {}).get("reference", ""),
                                "runs": answers,
                                "max_tokens": cfg["max_tokens"],
                            },
                            timeout=300.0,
                        )
                        response.raise_for_status()
                        st.session_state["t04_analysis"] = response.json()
                    except Exception as exc:  # noqa: BLE001 - показываем в UI
                        st.session_state["t04_analysis"] = None
                        st.error(f"Не удалось проанализировать: {type(exc).__name__}: {exc}")

        analysis = st.session_state.get("t04_analysis")
        if analysis:
            st.markdown(analysis.get("text") or "—")
            st.caption(
                f"{analysis.get('model')} · {analysis.get('elapsed_ms', 0)} мс · "
                f"{(analysis.get('usage') or {}).get('completion_tokens', 0)} ток"
            )
            if analysis.get("truncated"):
                st.warning("Анализ оборван лимитом max_tokens — увеличьте «Max tokens».")
