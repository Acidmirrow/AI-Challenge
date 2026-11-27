"""Урок 20: оркестрация нескольких MCP-серверов."""

from __future__ import annotations

import json
import os
from typing import Any

import httpx
import streamlit as st

API = os.getenv("LESSON_20_API_BASE_URL", "http://localhost:8020").rstrip("/")
TIMEOUT = httpx.Timeout(180.0, connect=10.0)
SERVER_LABELS = {
    "orders": "Заказы",
    "analytics": "Аналитика",
    "time": "Time (внешний)",
}


def _request(method: str, path: str, **kwargs: Any) -> dict[str, Any] | list[Any]:
    try:
        with httpx.Client(timeout=TIMEOUT) as client:
            response = client.request(method, f"{API}{path}", **kwargs)
    except httpx.HTTPError as exc:
        return {"_error": f"API урока 20 недоступен: {exc}"}
    if response.status_code >= 400:
        try:
            detail = response.json().get("detail")
        except ValueError:
            detail = response.text
        return {"_error": f"{response.status_code}: {detail}"}
    try:
        return response.json()
    except ValueError:
        return {"_error": "API вернул не JSON"}


def _models() -> tuple[list[str], dict[str, dict[str, Any]]]:
    data = _request("GET", "/api/models")
    options: list[str] = []
    mapping: dict[str, dict[str, Any]] = {}
    if not isinstance(data, list):
        return options, mapping
    for item in data:
        model_id = str(item.get("id") or "")
        if not model_id:
            continue
        label = f"{item.get('label') or model_id}  ·  {model_id}"
        options.append(label)
        mapping[label] = item
    return options, mapping


def _disabled() -> list[str]:
    return list(st.session_state.get("l20_disabled") or [])


def _inspect(disabled: list[str]) -> dict[str, Any]:
    result = _request(
        "POST", "/api/mcp/inspect", json={"disabled_servers": disabled}
    )
    return result if isinstance(result, dict) and not result.get("_error") else {}


def _render_servers(inspect: dict[str, Any]) -> None:
    st.markdown("#### MCP-серверы")
    servers = inspect.get("servers") or []
    if not servers:
        st.info("Статус серверов пока не загружен.")
        return
    columns = st.columns(3)
    for index, server in enumerate(servers):
        with columns[index % 3]:
            name = server.get("name", "—")
            label = SERVER_LABELS.get(name, server.get("label", name))
            if server.get("connected"):
                st.success(f"**{label}** · online")
            else:
                st.error(f"**{label}** · offline")
            st.caption(
                f"`{name}` · инструментов: {server.get('tool_count', 0)}"
                + (" · внешний" if server.get("external") else "")
            )
            if server.get("error"):
                st.caption(f"Причина: {server['error']}")
    tools = inspect.get("tools") or []
    with st.expander(f"Агрегированный каталог инструментов · {len(tools)}", expanded=False):
        for tool in tools:
            collision = " · имя разрешено префиксом" if tool.get("collision") else ""
            st.markdown(
                f"**`{tool.get('name')}`** · сервер `{tool.get('server')}`"
                f" · оригинал `{tool.get('original')}`{collision}"
            )
            st.caption(tool.get("description") or "")


def _render_steps(result: dict[str, Any]) -> None:
    steps = result.get("steps") or []
    if not steps:
        return
    st.markdown("#### Трасса вызовов")
    st.dataframe(
        [
            {
                "шаг": step.get("index"),
                "сервер": step.get("server"),
                "инструмент": step.get("tool"),
                "статус": step.get("status"),
                "мс": step.get("elapsed_ms"),
            }
            for step in steps
        ],
        use_container_width=True,
        hide_index=True,
    )
    for step in steps:
        with st.expander(
            f"{step.get('index')}. {step.get('server')}/{step.get('tool')} · {step.get('status')}",
            expanded=False,
        ):
            st.caption("Аргументы")
            st.json(step.get("arguments") or {})
            st.caption("Результат")
            st.json(step.get("result") or {})


def _render_flow() -> None:
    st.markdown("#### Длинный флоу")
    st.caption(
        "Клиент → прогноз → статус аналитики → статус заказов → текущее время. "
        "Шаги идут через разные MCP-серверы."
    )
    first, second, third = st.columns(3)
    customer = first.text_input("Клиент", value="C-104", key="l20_customer")
    amount = second.number_input(
        "Сумма, ₽", min_value=1, value=100_000, step=1_000, key="l20_amount"
    )
    run = third.button("Запустить длинный флоу", type="primary", key="l20_flow")
    if run:
        with st.spinner("Агент вызывает инструменты с разных серверов…"):
            result = _request(
                "POST",
                "/api/flow/run",
                json={
                    "customer_id": customer,
                    "amount_rub": int(amount),
                    "disabled_servers": _disabled(),
                },
            )
        st.session_state["l20_flow_result"] = result
    result = st.session_state.get("l20_flow_result")
    if not isinstance(result, dict):
        return
    if result.get("_error"):
        st.error(result["_error"])
        return
    if result.get("ok"):
        st.success(result.get("message") or "Флоу завершён.")
    else:
        st.error(result.get("message") or "Флоу остановлен.")
        st.caption(
            f"Остановка: `{result.get('stopped_server')}/{result.get('stopped_at')}` · "
            f"причина: {result.get('reason')}"
        )
    _render_steps(result)
    if result.get("ok"):
        customer_data = result.get("customer") or {}
        forecast = result.get("forecast") or {}
        first, second, third = st.columns(3)
        first.metric("Клиент", customer_data.get("name", "—"))
        second.metric("Риск", f"{forecast.get('risk_pct', '—')}%")
        third.metric(
            "Ожидаемая выручка",
            f"{forecast.get('expected_revenue_rub', '—')} ₽",
        )
        st.json(
            {
                "customer": customer_data,
                "forecast": forecast,
                "current_time": result.get("current_time"),
            }
        )


def _render_chat() -> None:
    st.markdown("#### Чат с агентом")
    options, mapping = _models()
    if not options:
        st.error("API урока 20 не вернул модели.")
        return
    if st.session_state.get("l20_model_option") not in options:
        st.session_state["l20_model_option"] = options[0]
    selected = st.selectbox("Модель", options, key="l20_model_option")
    model = mapping.get(selected) or {}

    history = st.session_state.setdefault("l20_history", [])
    for item in history:
        with st.chat_message(item.get("role", "assistant")):
            st.markdown(item.get("content") or "")

    prompt = st.chat_input(
        "Например: подготовь прогноз для C-104 на 100000 и текущее время",
        key="l20_chat_input",
    )
    if not prompt:
        return
    prior = list(history)
    history.append({"role": "user", "content": prompt})
    st.session_state["l20_history"] = history
    with st.spinner("Агент выбирает инструменты на разных серверах…"):
        result = _request(
            "POST",
            "/api/chat",
            json={
                "prompt": prompt,
                "model": model.get("id") or "mock-fast",
                "history": prior,
                "max_steps": 6,
                "disabled_servers": _disabled(),
            },
        )
    if isinstance(result, dict) and result.get("_error"):
        history.append({"role": "assistant", "content": f"Ошибка: {result['_error']}"})
    elif isinstance(result, dict):
        history.append(
            {"role": "assistant", "content": result.get("answer") or "Пустой ответ"}
        )
        st.session_state["l20_last"] = result
    else:
        history.append({"role": "assistant", "content": "API вернул неожиданный ответ"})
    st.session_state["l20_history"] = history
    st.rerun()


def _render_chat_trace() -> None:
    last = st.session_state.get("l20_last")
    if not isinstance(last, dict):
        return
    steps = last.get("steps") or []
    with st.expander(f"Трасса агента · {len(steps)} вызовов", expanded=False):
        for step in steps:
            st.markdown(
                f"**{step.get('index')}. `{step.get('tool')}`** · "
                f"сервер `{step.get('server')}` · {step.get('elapsed_ms', 0)} мс"
            )
            observation = step.get("result") or {}
            if observation.get("ok"):
                st.json(observation)
            else:
                st.error(observation.get("error") or "Ошибка инструмента")
    servers = last.get("servers") or []
    if servers:
        st.caption(
            " · ".join(
                f"{item.get('name')}: {'online' if item.get('connected') else 'offline'}"
                for item in servers
            )
        )


def render() -> None:
    st.markdown("## Урок 20. Оркестрация MCP")
    st.caption(
        "Три MCP-сервера: собственные «Заказы» и «Аналитика» плюс внешний "
        "Time reference-сервер. Хаб собирает инструменты в один каталог, "
        "маршрутизирует вызовы и переживает отключение одного сервера."
    )

    disabled = st.multiselect(
        "Смоделировать недоступность серверов",
        options=list(SERVER_LABELS),
        format_func=lambda value: SERVER_LABELS[value],
        key="l20_disabled",
    )
    inspect = _inspect(disabled)
    _render_servers(inspect)
    _render_flow()
    _render_chat()
    _render_chat_trace()
