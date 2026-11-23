"""Урок 16: чат с автоматически выбранными MCP-инструментами."""

from __future__ import annotations

import os
from typing import Any

import httpx
import streamlit as st

API = os.getenv("LESSON_16_API_BASE_URL", "http://localhost:8016").rstrip("/")
TIMEOUT = httpx.Timeout(180.0, connect=10.0)
YOUGILE_URL = "https://ru.yougile.com/data/ai/mcp"


def _request(method: str, path: str, **kwargs: Any) -> dict[str, Any] | list[Any]:
    try:
        with httpx.Client(timeout=TIMEOUT) as client:
            response = client.request(method, f"{API}{path}", **kwargs)
    except httpx.HTTPError as exc:
        return {"_error": f"API урока 16 недоступен: {exc}"}
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


def _load_backend() -> tuple[
    list[dict[str, Any]], dict[str, Any], dict[str, Any], str, str
]:
    models = _request("GET", "/api/models")
    local = _request("POST", "/api/mcp/inspect")
    external = _request(
        "POST",
        "/api/mcp/external/inspect",
        json={"url": YOUGILE_URL},
    )
    model_error = models.get("_error") if isinstance(models, dict) else ""
    local_error = local.get("_error") if isinstance(local, dict) else ""
    external_error = external.get("_error") if isinstance(external, dict) else ""
    return (
        models if isinstance(models, list) else [],
        local if isinstance(local, dict) and not local_error else {},
        external if isinstance(external, dict) and not external_error else {},
        model_error or local_error,
        external_error,
    )


def _model_options(models: list[dict[str, Any]]) -> tuple[list[str], dict[str, dict[str, Any]]]:
    options: list[str] = []
    mapping: dict[str, dict[str, Any]] = {}
    for model in models:
        model_id = str(model.get("id") or "")
        if not model_id:
            continue
        label = str(model.get("label") or model_id)
        options.append(f"{label}  ·  {model_id}")
        mapping[options[-1]] = model
    return options, mapping


def _brief(text: Any, limit: int = 150) -> str:
    value = " ".join(str(text or "").split())
    return value if len(value) <= limit else value[: limit - 1].rstrip() + "…"


def _tool_rows(local: dict[str, Any], external: dict[str, Any]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for tool in local.get("tools") or []:
        if tool.get("name"):
            rows.append(
                {
                    "Инструмент": str(tool["name"]),
                    "Относится к": "встроенный MCP",
                    "Что делает": _brief(tool.get("description")),
                }
            )
    for tool in external.get("tools") or []:
        if tool.get("name"):
            rows.append(
                {
                    "Инструмент": str(tool["name"]),
                    "Относится к": "YouGile",
                    "Что делает": _brief(tool.get("description")),
                }
            )
    return rows


def _render_steps(result: dict[str, Any]) -> None:
    steps = result.get("steps") or []
    if not steps:
        return
    with st.expander(f"Вызовы MCP · {len(steps)}", expanded=True):
        for step in steps:
            st.markdown(
                f"**{step.get('index')}. {step.get('label') or step.get('tool')}** "
                f"· `{step.get('tool')}` · {step.get('elapsed_ms', 0)} мс"
            )
            st.caption("Аргументы")
            st.json(step.get("arguments") or {})
            st.caption("Наблюдение")
            observation = step.get("result") or {}
            if observation.get("ok"):
                st.json(observation.get("result"))
            else:
                st.error(observation.get("error") or "Ошибка инструмента")


def _render_chat() -> None:
    history = st.session_state.setdefault("l16_history", [])
    for item in history:
        with st.chat_message(item.get("role", "assistant")):
            st.markdown(item.get("content") or "")

    prompt = st.chat_input(
        "Задача для агента: инструменты выбираются автоматически",
        key="l16_chat_input",
    )
    if not prompt:
        return

    history = list(history)
    prior = list(history)
    history.append({"role": "user", "content": prompt})
    st.session_state["l16_history"] = history
    selected = st.session_state.get("l16_model_option") or ""
    model = st.session_state.get("l16_models", {}).get(selected) or {}
    payload = {
        "prompt": prompt,
        "model": model.get("id") or "mock-fast",
        "history": prior,
        "temperature": st.session_state.get("l16_temperature", 0.2),
        "max_steps": 6,
    }
    with st.spinner("Агент выбирает MCP-инструменты…"):
        result = _request("POST", "/api/chat", json=payload)
    if isinstance(result, dict) and result.get("_error"):
        st.session_state["l16_error"] = result["_error"]
        history.append({"role": "assistant", "content": f"Ошибка: {result['_error']}"})
    else:
        st.session_state["l16_error"] = ""
        answer = (result or {}).get("answer") or "Пустой ответ"
        history.append({"role": "assistant", "content": answer})
        st.session_state["l16_last"] = result
    st.session_state["l16_history"] = history
    st.rerun()


def render() -> None:
    st.markdown("## Урок 16. Подключение MCP")
    st.caption(
        "Чат с агентом: встроенные инструменты и YouGile подключены по MCP. "
        "Инструменты выбираются автоматически по задаче."
    )

    if "l16_backend_loaded" not in st.session_state:
        with st.spinner("Подключаю MCP и загружаю модели…"):
            models, local, external, error, external_error = _load_backend()
        st.session_state["l16_models_list"] = models
        st.session_state["l16_local"] = local
        st.session_state["l16_external"] = external
        st.session_state["l16_backend_error"] = error
        st.session_state["l16_external_error"] = external_error
        st.session_state["l16_backend_loaded"] = True
    models = st.session_state.get("l16_models_list") or []
    local = st.session_state.get("l16_local") or {}
    external = st.session_state.get("l16_external") or {}
    error = st.session_state.get("l16_backend_error") or ""
    external_error = st.session_state.get("l16_external_error") or ""

    options, mapping = _model_options(models)
    st.session_state["l16_models"] = mapping
    if not options:
        st.error("API урока 16 не вернул доступные модели.")
        return
    if st.session_state.get("l16_model_option") not in options:
        st.session_state["l16_model_option"] = options[0]

    st.selectbox(
        "Модель",
        options,
        key="l16_model_option",
        label_visibility="collapsed",
    )

    if error:
        st.error(error)
    if external_error:
        st.caption(f"YouGile MCP сейчас недоступен: {external_error}")

    local_count = int(local.get("tool_count") or 0)
    external_count = int(external.get("tool_count") or 0)
    rows = _tool_rows(local, external)
    with st.expander(
        f"Краткая сводка инструментов · {local_count + external_count}",
        expanded=False,
    ):
        st.write(
            f"**{local_count}** встроенных инструментов · "
            f"**{external_count}** инструментов YouGile"
        )
        st.caption("Выбираются моделью автоматически; ручной переключатель не нужен.")
        st.dataframe(rows, use_container_width=True, hide_index=True, height=420)

    with st.expander("Все MCP-серверы", expanded=False):
        st.json(
            [
                {
                    "name": "builtin",
                    "transport": local.get("transport"),
                    "tools": local_count,
                    "status": "ok" if not error else "error",
                },
                {
                    "name": "yougile",
                    "transport": external.get("transport"),
                    "tools": external_count,
                    "status": "ok" if not external_error else "error",
                },
            ]
        )

    if st.button("Очистить чат", key="l16_clear_chat"):
        st.session_state["l16_history"] = []
        st.session_state["l16_last"] = None
        st.session_state["l16_error"] = ""
        st.rerun()

    _render_chat()
    last = st.session_state.get("l16_last")
    if last:
        _render_steps(last)
