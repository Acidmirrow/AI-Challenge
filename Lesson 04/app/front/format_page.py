"""Страница «Форматы ответа» — лаборатория урока 02."""

from __future__ import annotations

import json

import httpx
import streamlit as st

from common import (
    FORMAT_API,
    REASONING_LABELS,
    SOURCE_LABELS,
    nixie_digits,
    post_stream,
    model_picker,
    provider_badges,
    selectable_models,
)

# Готовые промпты под пресеты схем: одна кнопка — и промпт со схемой согласованы
PROMPT_TEMPLATES: dict[str, tuple[str, str]] = {
    "Планеты Солнечной системы": (
        "Перечисли планеты Солнечной системы по порядку от Солнца: Меркурий, Венера, Земля, "
        "Марс, Юпитер, Сатурн, Уран, Нептун. Для каждой укажи номер, название, "
        "тип (terrestrial / gas_giant / ice_giant), число спутников и расстояние от Солнца в а.е.",
        "planets",
    ),
    "Фильмы (список)": (
        "Есть три фильма: Матрица (1999, рейтинг 8.7, фантастика и боевик), "
        "Начало (2010, рейтинг 8.8, фантастика и триллер), "
        "Интерстеллар (2014, рейтинг 8.7, фантастика и драма). "
        "Перечисли их в том же порядке, сохранив название, год, рейтинг и жанры.",
        "movie",
    ),
    "Тикеты поддержки (список)": (
        "В очереди три обращения: 1) оплата картой падает с ошибкой 500, деньги не списались; "
        "2) не приходит письмо с подтверждением регистрации; "
        "3) вход в личный кабинет зависает на загрузке. "
        "Перечисли все три тикета с номером, кратким описанием, приоритетом "
        "(low / medium / high) и признаком, нужен ли человек.",
        "ticket",
    ),
    "Товары (список)": (
        "В наличии на складе: Sony WH-1000XM5 — 34 990 ₽, есть в наличии, 250 г; "
        "Logitech MX Master 3S — 9 490 ₽, есть в наличии, 141 г; "
        "Keychron K8 — 12 500 ₽, нет в наличии, 880 г. "
        "Перечисли все три товара с названием, ценой, валютой, наличием и весом.",
        "product",
    ),
}
INSTRUCTION_TEMPLATES: dict[str, str] = {
    "Встроенное описание формата": "",
    "Три пункта": "Ответь ровно тремя пунктами, каждый не длиннее 90 символов.",
    "Markdown-таблица": "Ответь Markdown-таблицей с колонками «Поле» и «Значение», без вступлений.",
    "JSON без пояснений": "Верни только JSON-объект, без текста вокруг и без ```-обёртки.",
    "Одна строка": "Ответь одной строкой, не длиннее 120 символов, без списков.",
}


@st.cache_data(ttl=30, show_spinner=False)
def load_format_backend() -> dict:
    result: dict = {"health": None, "formats": [], "models": [], "presets": [], "providers": [], "error": None}
    try:
        with httpx.Client(timeout=10.0) as client:
            result["health"] = client.get(f"{FORMAT_API}/api/health").json()
            result["formats"] = client.get(f"{FORMAT_API}/api/formats").json()
            result["models"] = client.get(f"{FORMAT_API}/api/models").json()
            result["presets"] = client.get(f"{FORMAT_API}/api/presets").json()
            result["providers"] = client.get(f"{FORMAT_API}/api/providers/status").json()
    except Exception as exc:  # noqa: BLE001
        result["error"] = f"{type(exc).__name__}: {exc}"
    return result


def _collect(payload: dict) -> tuple[dict | None, dict | None]:
    result, error = None, None
    for event, data in post_stream("/api/format/run", payload, FORMAT_API):
        if event == "result":
            result = data
        elif event == "error":
            error = data
    return result, error


def _nixie_slider(label, *, min_value, max_value, step, default, key, fmt, disabled=False, help=None):
    """Слайдер с табло: значение видно всегда (в т.ч. max tokens)."""
    readout = st.empty()
    kwargs = dict(label=label, min_value=min_value, max_value=max_value, step=step,
                  key=key, disabled=disabled, help=help)
    if key not in st.session_state:
        kwargs["value"] = default
    value = st.slider(**kwargs)
    readout.markdown(nixie_digits(fmt(value)), unsafe_allow_html=True)
    return value


DEFAULT_PROMPT_TEMPLATE = next(iter(PROMPT_TEMPLATES))


def _apply_prompt_template() -> None:
    """Callback: срабатывает ДО перерисовки — можно менять состояние виджетов."""
    name = st.session_state.get("fmt_prompt_template")
    if not name:
        return
    text, preset = PROMPT_TEMPLATES[name]
    st.session_state["fmt_prompt"] = text
    for fmt_id in ("json_object", "json_schema", "tool_call"):
        st.session_state[f"fmt_preset::{fmt_id}"] = preset


def _parse_stop(raw: str) -> list[str] | None:
    items = [chunk.strip(" \t").replace("\\n", "\n") for chunk in raw.split(",")]
    items = [item for item in items if item]
    return items or None


def render() -> None:
    st.session_state.setdefault("ui_model", None)
    st.session_state.setdefault("fmt_result", None)
    st.session_state.setdefault("fmt_error", None)
    st.session_state.setdefault("fmt_comparison", None)

    backend = load_format_backend()
    models = backend["models"]
    formats = backend["formats"]
    presets = backend["presets"]

    schema_mismatch = False
    mismatch_text = ""

    with st.sidebar:
        if backend["error"]:
            st.error("API урока 02 недоступен")
            st.caption(backend["error"])
            return

        health = backend["health"] or {}
        st.markdown(
            provider_badges(backend.get("providers") or []), unsafe_allow_html=True
        )
        if not models or not formats:
            st.error("API вернул пустой каталог")
            return

        models = selectable_models(models)
        current = next((m for m in models if m["id"] == st.session_state.ui_model), models[0])
        picked = model_picker(
            models, current["id"], key="ui_model", caption="Каталог моделей урока 02"
        )
        current = next(item for item in models if item["id"] == picked)
        st.session_state.ui_model = picked

        st.divider()

        format_ids = [item["id"] for item in formats]
        chosen_format = st.selectbox(
            "Формат ответа",
            options=format_ids,
            format_func=lambda fid: next(f["label"] for f in formats if f["id"] == fid),
            key="fmt_format",
        )
        spec = next(f for f in formats if f["id"] == chosen_format)
        st.caption(spec["description"])
        if spec["needs_schema"] and not current.get("supports_json_schema", True):
            st.caption("⚠️ Модель не принимает strict json_schema — схема уйдёт в описании "
                       "(json_object), проверка схемы локальная")

        template = st.selectbox("Шаблон описания", options=list(INSTRUCTION_TEMPLATES),
                                key=f"fmt_tpl::{chosen_format}")
        sys_key = f"fmt_sys::{chosen_format}"
        if template != "Встроенное описание формата":
            st.session_state[sys_key] = INSTRUCTION_TEMPLATES[template]
        elif sys_key not in st.session_state:
            st.session_state[sys_key] = spec.get("default_instruction") or ""

        system_prompt = st.text_area("Описание формата (system)", height=120, key=sys_key,
                                     help="Уходит первым system-сообщением")
        effective = system_prompt.strip() or spec.get("default_instruction") or ""
        st.caption(f"В модель уйдёт: _{effective[:160]}_")

        schema_text, schema_name, tool_name = "", "response", "save_result"
        if spec["needs_schema"]:
            preset_labels = {p["id"]: p["label"] for p in presets}
            # по умолчанию берём пресет, соответствующий выбранному промпту
            template_name = st.session_state.get("fmt_prompt_template", DEFAULT_PROMPT_TEMPLATE)
            template_preset = PROMPT_TEMPLATES.get(template_name, ("", ""))[1]
            preset_options = list(preset_labels)
            preset_index = preset_options.index(template_preset) if template_preset in preset_options else 0
            preset_id = st.selectbox("Пресет схемы", options=preset_options,
                                     index=preset_index,
                                     format_func=lambda pid: preset_labels[pid],
                                     key=f"fmt_preset::{chosen_format}")
            preset = next(p for p in presets if p["id"] == preset_id)
            schema_text = st.text_area("JSON Schema",
                                       value=json.dumps(preset["schema"], ensure_ascii=False, indent=2),
                                       height=230, key=f"fmt_schema::{chosen_format}::{preset_id}")
            schema_name = preset_id
            if preset_id != template_preset:
                expected_label = preset_labels.get(template_preset, template_preset) or "—"
                schema_mismatch = True
                mismatch_text = (
                    f"Пресет схемы «{preset_labels[preset_id]}» не соответствует промпту "
                    f"«{template_name}»: для него нужна схема «{expected_label}». "
                    "Выберите подходящий пресет или смените шаблон промпта."
                )
            if spec["uses_tools"]:
                tool_name = st.text_input("Имя инструмента", value="save_result", key="fmt_tool_name")

        levels = current.get("reasoning_levels") or []
        reasoning = "off"
        if levels:
            # «off» у DeepSeek означает «параметр не передан», т.е. thinking включён —
            # поэтому предлагаем только явные уровни (none = без рассуждений)
            reasoning = st.selectbox("Reasoning", options=levels,
                                     index=levels.index("none") if "none" in levels else 0,
                                     format_func=lambda k: REASONING_LABELS.get(k, k),
                                     key=f"fmt_reasoning::{current['id']}")

        temperature = _nixie_slider("Температура", min_value=0.0, max_value=2.0, step=0.1,
                                    default=0.2, key="fmt_temperature",
                                    fmt=lambda v: f"{v:.1f}",
                                    disabled=not current["supports_temperature"])
        max_tokens = _nixie_slider("Max tokens", min_value=100, max_value=10_000, step=100,
                                   default=1_000, key="fmt_max_tokens",
                                   fmt=lambda v: f"{int(v):05d}",
                                   help="Предел длины ответа: до 10 000 токенов")
        stop_raw = st.text_input("Stop sequence", value="", placeholder="\n\n  или  5, Плутон",
                                 key="fmt_stop",
                                 help="Обрыв генерации на первой из последовательностей (через запятую)")

    payload = {
        "format": chosen_format,
        "model": current["id"],
        "prompt": "",
        "temperature": temperature,
        "reasoning": reasoning,
        "max_tokens": max_tokens,
        "stop": _parse_stop(stop_raw),
        "system_prompt": system_prompt.strip() or None,
    }
    if spec["needs_schema"]:
        payload["schema"] = json.loads(schema_text) if schema_text.strip() else None
        payload["schema_name"] = schema_name or "response"
        payload["tool_name"] = tool_name or "save_result"

    st.markdown("### Промпт")
    st.session_state.setdefault("fmt_prompt", PROMPT_TEMPLATES[DEFAULT_PROMPT_TEMPLATE][0])

    st.selectbox(
        "Шаблон промпта",
        options=list(PROMPT_TEMPLATES),
        key="fmt_prompt_template",
        on_change=_apply_prompt_template,
        help="Подставляет готовый промпт и, если формат требует схему, соответствующий пресет",
    )

    prompt = st.text_area("Данные", height=100, label_visibility="collapsed", key="fmt_prompt")

    if schema_mismatch:
        st.error(f"{mismatch_text} Прогон заблокирован.")

    col_run, col_cmp = st.columns([1, 1])
    run_clicked = col_run.button("▶  Прогнать формат", type="primary", use_container_width=True,
                                 key="fmt_run", disabled=schema_mismatch)
    compare_clicked = col_cmp.button("⚖  Сравнить варианты", use_container_width=True,
                                     key="fmt_compare", disabled=schema_mismatch)


    if run_clicked:
        if not prompt.strip():
            st.warning("Нужен промпт")
        else:
            payload["prompt"] = prompt.strip()
            st.session_state.fmt_result = None
            st.session_state.fmt_error = None
            live = st.empty()
            buffer = ""
            with st.status(f"Формат: {spec['label']}", expanded=True) as status:
                for event, data in post_stream("/api/format/run", payload, FORMAT_API):
                    if event == "start":
                        status.write(f"Модель {data.get('model')}, формат {data.get('format')}")
                        for note in data.get("notes") or []:
                            status.write(f"⚠️ {note}")
                        buffer = ""
                    elif event == "delta":
                        buffer += data.get("text", "")
                        live.code(buffer[-4000:] or "…",
                                  language="json" if spec["needs_schema"] else "markdown")
                    elif event == "run_result":
                        if data.get("truncated"):
                            status.write("⚠️ Ответ обрезан по лимиту max_tokens — он неполный")
                        grade = "✅" if data.get("parse_check", {}).get("ok") else "❌"
                        status.write(f"{grade} ответ разобран")
                    elif event == "result":
                        st.session_state.fmt_result = data
                        status.update(label="Готово", state="complete")
                    elif event == "error":
                        st.session_state.fmt_error = data
                        status.update(label="Ошибка", state="error")
            live.empty()

    if compare_clicked and presets:
        base_schema = presets[0]["schema"]
        variants = [
            ("Без ограничений",
             {"format": "text", "max_tokens": 900, "stop": None, "system_prompt": None,
              "reasoning": "none"}),
            ("С ограничениями",
             {"format": "text", "max_tokens": 200, "stop": ["\n3."],
              "system_prompt": "Ответь ровно тремя пунктами, каждый не длиннее 90 символов.",
              "reasoning": "none"}),
            ("Строгая схема",
             {"format": "json_object", "schema": base_schema, "schema_name": "strict",
              "max_tokens": 900, "stop": None, "system_prompt": None,
              "reasoning": "none"}),
        ]
        rows = []
        progress = st.progress(0.0, text="Сравнение вариантов…")
        done, total = 0, len(variants)
        for title, overrides in variants:
            trial = {**payload, "prompt": prompt.strip(), **overrides}
            result, error = _collect(trial)
            done += 1
            progress.progress(done / total, text=title)
            if result is None:
                rows.append({
                    "вариант": title, "токенов": 0, "finish": "—",
                    "парсится кодом": "нет", "валидна схема": "—",
                    "детали разбора": (error or {}).get("message", "ошибка")[:70],
                })
                continue
            check_row = result.get("parse_check") or {}
            valid_row = result.get("validation") or {}
            usage_row = result.get("usage") or {}
            rows.append({
                "вариант": title,
                "токенов": usage_row.get("completion_tokens") or 0,
                "finish": result.get("finish_reason") or "—",
                "лимит": "обрезан" if result.get("finish_reason") == "length" else "ок",
                "парсится кодом": "да" if check_row.get("ok") else "нет",
                "валидна схема": ("да" if valid_row.get("valid") else "нет")
                if valid_row.get("applicable", True) else "—",
                "детали разбора": (check_row.get("detail") or "—")[:70],
            })
        progress.empty()
        st.session_state.fmt_comparison = rows

    error = st.session_state.fmt_error
    if error:
        st.error(error.get("message", "ошибка"))
        st.caption(f"kind: `{error.get('kind', '?')}`")

    result = st.session_state.fmt_result
    if result:
        results = result.get("results") or []
        summary = result.get("summary") or {}
        first = results[0] if results else result
        validation = first.get("validation") or {}
        check = first.get("parse_check") or {}

        finish_line = ", ".join(summary.get("finish_reasons", {}) or {}) or "—"
        st.markdown(
            f'<div class="meta-line">{result["format"]} · {result["model"]} · '
            f'completion-токенов: {summary.get("avg_completion_tokens", "—")} · finish: {finish_line}</div>',
            unsafe_allow_html=True,
        )
        limit = result.get("limit") or {}
        if first.get("truncated") or limit.get("truncated"):
            st.error(
                f"Ответ оборван лимитом вывода: max_tokens = {limit.get('max_tokens', payload['max_tokens'])} "
                "(finish_reason=length). Модель не успела закончить — текст/JSON неполный. "
                "Это не ошибка формата ответа: увеличьте «Max tokens» и прогоните снова."
            )

        st.markdown(
            f'<div class="{"verdict-ok" if check.get("ok") else "verdict-bad"}">'
            f'{"✅ Парсится кодом" if check.get("ok") else "❌ Не парсится кодом"} — '
            f'{check.get("kind")}: {check.get("detail")}</div>',
            unsafe_allow_html=True,
        )
        if validation.get("applicable", True):
            st.markdown(
                f'<div class="{"verdict-ok" if validation.get("valid") else "verdict-bad"}">'
                f'{"✅ Схема соблюдена" if validation.get("valid") else "❌ Схема нарушена"}</div>',
                unsafe_allow_html=True,
            )
        else:
            st.caption("Схема не применяется: формат неструктурированный")

        tabs = st.tabs(["Результат", "Сырой ответ", "Валидация", "Что отправлено"])
        with tabs[0]:
            parsed = first.get("parsed")
            st.json(parsed) if isinstance(parsed, (dict, list)) else st.markdown(parsed or "—")
        with tabs[1]:
            raw = first.get("raw_text") or ""
            tool_call = first.get("tool_call")
            if tool_call:
                st.caption(f"tool: `{tool_call.get('name')}`")
                st.code(tool_call.get("arguments") or raw or "—", language="json")
            else:
                st.code(raw or "—",
                        language="json" if result["format"].startswith("json") else "markdown")
        with tabs[2]:
            errors = validation.get("errors") or []
            if not errors:
                st.success("Ответ соответствует схеме")
            else:
                st.dataframe(
                    [{"path": e["path"], "validator": e["validator"], "message": e["message"]}
                     for e in errors],
                    use_container_width=True, hide_index=True,
                )
        with tabs[3]:
            st.code(json.dumps(result.get("sent") or {}, ensure_ascii=False, indent=2), language="json")
    elif not st.session_state.fmt_comparison:
        st.caption("Выбери формат, заполни промпт и нажми «Прогнать формат». "
                   "«Сравнить варианты» прогонит три режима и покажет таблицу.")

    if st.session_state.fmt_comparison:
        st.markdown("### Сравнение вариантов")
        st.dataframe(st.session_state.fmt_comparison, use_container_width=True, hide_index=True)
        st.caption("«Парсится кодом» — ответ разобран (JSON или Markdown-таблица). "
                   "«Валидна схема» — прошёл проверку по JSON Schema.")
