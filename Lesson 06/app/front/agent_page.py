"""Страница «ИИ-агент» — урок 06.

Пользователь ставит задачу, агент сам выбирает инструменты (калькулятор, время,
статистика текста, курсы валют). Снаружи видны ответ и метрики, полная трасса
шагов с аргументами и наблюдениями — в свёрнутом блоке.
"""

from __future__ import annotations

import json

import httpx
import streamlit as st

from common import AGENT_API, model_sidebar, selectable_models

EXAMPLE_TASK = (
    "Собери отчёт: время в Москве; сколько дней до 2027-01-01; "
    "курс USD/RUB и 250 USD в рублях; 5 км в метрах; 255 в hex; "
    "среднее чисел 2, 4, 6; SHA256 от hello; сколько слов в "
    "«агент вызывает инструменты по шагам»."
)




@st.cache_data(ttl=20, show_spinner=False)
def load_backend() -> dict:
    result: dict = {
        "health": None,
        "models": [],
        "providers": [],
        "tools": [],
        "error": None,
    }
    try:
        with httpx.Client(timeout=10.0) as client:
            result["health"] = client.get(f"{AGENT_API}/api/health").json()
            result["models"] = client.get(f"{AGENT_API}/api/models").json()
            result["providers"] = client.get(f"{AGENT_API}/api/providers/status").json()
            result["tools"] = client.get(f"{AGENT_API}/api/tools").json()
    except Exception as exc:  # noqa: BLE001 - показываем в сайдбаре
        result["error"] = f"{type(exc).__name__}: {exc}"
    return result


def _models_for_ui(models: list[dict]) -> list[dict]:
    return selectable_models(models)


def _use_example() -> None:
    st.session_state["m06_prompt"] = EXAMPLE_TASK


def _render_tools(tools: list[dict]) -> None:
    with st.expander(f"Справка по инструментам · {len(tools)}", expanded=False):
        for tool in tools:
            st.markdown(f"**{tool.get('label') or tool['name']}** · `{tool['name']}`")
            st.caption(tool.get("description") or "")


def _render_steps(result: dict) -> None:
    steps = result.get("steps") or []
    if not steps:
        st.caption("Инструменты не вызывались.")
        return

    # Полная трасса скрыта по умолчанию: снаружи видны только ответ и метрики.
    with st.expander("Полные размышления и вызовы инструментов", expanded=False):
        for step in steps:
            label = step.get("label") or step.get("tool") or "инструмент"
            st.markdown(
                f"**Шаг {step.get('index')} · {label} · {step.get('elapsed_ms', 0)} мс**"
            )
            st.caption("Аргументы")
            st.code(
                json.dumps(step.get("arguments") or {}, ensure_ascii=False, indent=2),
                language="json",
            )
            observation = step.get("result") or {}
            st.caption("Наблюдение")
            if observation.get("ok"):
                st.code(
                    json.dumps(observation.get("result"), ensure_ascii=False, indent=2),
                    language="json",
                )
            else:
                st.error(observation.get("error") or "Инструмент вернул ошибку.")
            st.divider()


def _render_used_tools(result: dict) -> None:
    """Короткий список вызванных инструментов — виден даже при свёрнутой трассе."""
    steps = result.get("steps") or []
    if not steps:
        return
    counts: dict[str, int] = {}
    order: list[str] = []
    for step in steps:
        label = step.get("label") or step.get("tool") or "инструмент"
        if label not in counts:
            order.append(label)
        counts[label] = counts.get(label, 0) + 1
    parts = [f"{label} ×{counts[label]}" if counts[label] > 1 else label for label in order]
    st.markdown(f"**Вызванные инструменты:** {' → '.join(parts)}")


def _render_result(result: dict, tool_labels: dict[str, str] | None = None) -> None:
    st.markdown("### Ответ агента")
    st.markdown(result.get("answer") or "—")

    steps = result.get("steps") or []
    usage = result.get("usage") or {}
    columns = st.columns(4)
    columns[0].metric("Шагов", len(steps))
    columns[1].metric("Время", f"{result.get('elapsed_ms', 0) / 1000:.1f} с")
    columns[2].metric("Токены", usage.get("total_tokens", 0))
    columns[3].metric(
        "Стоимость",
        "0 $" if not result.get("cost_usd") else f"${result['cost_usd']:.6f}",
    )

    st.caption(
        f"{result.get('label') or result.get('model')} · {result.get('provider', '')} · "
        f"причина остановки: {result.get('stopped_reason', 'final')}"
    )
    if result.get("stopped_reason") == "missing_tool":
        missing = result.get("missing_tools") or []
        labels = ", ".join((tool_labels or {}).get(name, name) for name in missing)
        labels = labels or "нужный инструмент"
        st.warning(
            f"Для этой задачи не выбран нужный инструмент: {labels}. "
            "Включите его в сайдбаре и повторите запуск."
        )
    elif result.get("stopped_reason") == "max_steps":
        st.warning(
            "Сработал лимит шагов: агент остановился и попросил модель подвести итог. "
            "Увеличьте «Максимум шагов», если задача сложнее."
        )
    if result.get("truncated"):
        st.warning("Ответ оборван лимитом max_tokens — увеличьте его в сайдбаре.")

    if result.get("stopped_reason") != "missing_tool":
        _render_steps(result)
        _render_used_tools(result)


def render() -> None:
    backend = load_backend()
    st.session_state.setdefault("m06_result", None)
    st.session_state.setdefault("m06_error", None)

    if backend["error"]:
        st.error("API урока 06 недоступен")
        st.caption(backend["error"])
        return

    models = _models_for_ui(backend["models"])
    if not models:
        st.error("API вернул пустой список моделей")
        return

    tools = backend["tools"] or []

    with st.sidebar:
        controls = model_sidebar(
            models,
            backend["providers"],
            st.session_state.get("m06_model"),
            prefix="m06",
            temperature_default=0.2,
            max_tokens_default=1_500,
            model_key="m06_model",
        )
        steps_kwargs = dict(
            label="Максимум шагов",
            min_value=1,
            max_value=10,
            key="m06_max_steps",
            help="Сколько раз агент может вызвать инструмент до финального ответа",
        )
        if "m06_max_steps" not in st.session_state:
            steps_kwargs["value"] = 10
        max_steps = st.slider(**steps_kwargs)

        tool_map = {item["name"]: item.get("label") or item["name"] for item in tools}
        for name in tool_map:
            key = f"m06_tool::{name}"
            if key not in st.session_state:
                st.session_state[key] = True
        chosen = sum(1 for name in tool_map if st.session_state[f"m06_tool::{name}"])
        selected_tools: list[str] = []
        with st.popover(
            f"🧰  Инструменты агента · {chosen}/{len(tool_map)}  ▾",
            use_container_width=True,
        ):
            st.caption(f"Выбрано: {chosen} из {len(tool_map)}")
            for name, label in tool_map.items():
                if st.checkbox(label, key=f"m06_tool::{name}"):
                    selected_tools.append(name)
            if not selected_tools:
                st.caption("Без инструментов агент ответит только на задачу, не требующую расчётов.")

        if st.button("Очистить", key="m06_clear", use_container_width=True):
            st.session_state["m06_result"] = None
            st.session_state["m06_error"] = None
            st.session_state["m06_prompt"] = ""
            st.rerun()

    st.markdown("## ИИ-агент")
    st.caption(
        "Урок 06: модель получает задачу и инструменты, сама решает, что вызвать, "
        "а сервер возвращает результат обратно в диалог. Полная трасса — в свёрнутом блоке."
    )

    _render_tools(tools)

    prompt = st.text_area(
        "Задача агенту",
        height=170,
        key="m06_prompt",
        placeholder=EXAMPLE_TASK,
    )

    st.button(
        "📋  Вставить пример",
        key="m06_example",
        on_click=_use_example,
        help="Заполнить поле примером задачи на все 9 инструментов",
    )
    if not prompt.strip():
        st.caption(
            "Placeholder — это подсказка, а не текст задачи. "
            "Нажмите «Вставить пример» или введите свою задачу."
        )

    if st.button(
        "▶  Запустить агента",
        type="primary",
        key="m06_run",
        disabled=not prompt.strip(),
        help="Введите задачу или нажмите «Вставить пример»",
    ):
        with st.spinner("Агент думает и вызывает инструменты…"):
            try:
                response = httpx.post(
                    f"{AGENT_API}/api/agent",
                    json={
                        "prompt": prompt.strip(),
                        "model": controls["model"]["id"],
                        "temperature": controls["temperature"],
                        "reasoning": controls["reasoning"],
                        "max_tokens": controls["max_tokens"],
                        "max_steps": int(max_steps),
                        "tools": selected_tools,
                    },
                    timeout=600.0,
                )
                response.raise_for_status()
                st.session_state["m06_result"] = response.json()
                st.session_state["m06_error"] = None
            except httpx.HTTPStatusError as exc:
                st.session_state["m06_result"] = None
                st.session_state["m06_error"] = (
                    f"Агент не отработал ({exc.response.status_code}): "
                    f"{exc.response.text[:400]}"
                )
            except Exception as exc:  # noqa: BLE001 - показываем в UI
                st.session_state["m06_result"] = None
                st.session_state["m06_error"] = f"{type(exc).__name__}: {exc}"

    if st.session_state.get("m06_error"):
        st.error(st.session_state["m06_error"])

    result = st.session_state.get("m06_result")
    if result:
        _render_result(result, {item["name"]: item["label"] for item in tools})
