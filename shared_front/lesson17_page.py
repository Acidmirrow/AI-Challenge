"""Урок 17: MCP-инструмент вокруг mock CRM API и агентский чат."""

from __future__ import annotations

import json
import os
from typing import Any

import httpx
import streamlit as st

API = os.getenv("LESSON_17_API_BASE_URL", "http://localhost:8017").rstrip("/")
TIMEOUT = httpx.Timeout(180.0, connect=10.0)


def _request(method: str, path: str, **kwargs: Any) -> dict[str, Any] | list[Any]:
    try:
        with httpx.Client(timeout=TIMEOUT) as client:
            response = client.request(method, f"{API}{path}", **kwargs)
    except httpx.HTTPError as exc:
        return {"_error": f"API урока 17 недоступен: {exc}"}
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


def _payload(result: Any) -> dict[str, Any] | None:
    if not isinstance(result, dict) or result.get("_error"):
        return None
    text = result.get("text")
    if not isinstance(text, str):
        return None
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _call(tool: str, arguments: dict[str, Any], key: str) -> None:
    result = _request(
        "POST",
        "/api/mcp/call",
        json={"tool": tool, "arguments": arguments},
    )
    st.session_state[key] = result


def _show_call_result(result: Any, key: str) -> None:
    if not result:
        return
    if not isinstance(result, dict) or result.get("_error"):
        st.error((result or {}).get("_error", "Неизвестная ошибка"))
        return
    st.caption(f"Результат MCP · {result.get('duration_ms', '—')} мс")
    payload = _payload(result)
    if payload is None:
        st.code(result.get("text") or "", language="json")
    elif not payload.get("ok"):
        st.error(payload.get("error") or "Инструмент вернул ошибку")


def _show_customers(payload: dict[str, Any] | None) -> None:
    if not payload or not payload.get("ok"):
        return
    customers = payload.get("customers") or []
    if not customers:
        st.info("Клиентов пока нет.")
        return
    st.dataframe(customers, use_container_width=True, hide_index=True)


def _inject_button_styles() -> None:
    st.markdown(
        """
        <style>
        .st-key-l17_list button,
        .st-key-l17_call button,
        .st-key-l17_actions [data-testid="stPopover"] button[data-testid="stPopoverButton"] {
            background-color: #262c3a !important;
            border-color: #3a4356 !important;
            color: #f5f7fa !important;
            min-height: 2.5rem !important;
            height: 2.5rem !important;
        }
        .st-key-l17_list button:hover,
        .st-key-l17_call button:hover,
        .st-key-l17_actions [data-testid="stPopover"] button[data-testid="stPopoverButton"]:hover {
            background-color: #303849 !important;
            border-color: #4a556b !important;
            color: #ffffff !important;
        }
        .st-key-l17_delete button {
            background-color: #b42318 !important;
            border-color: #b42318 !important;
            color: #ffffff !important;
            min-height: 2.5rem !important;
        }
        .st-key-l17_delete button:hover {
            background-color: #912018 !important;
            border-color: #912018 !important;
            color: #ffffff !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _render_tool(snapshot: dict[str, Any]) -> None:
    tools = snapshot.get("tools") or []
    with st.expander("Инструменты MCP: регистрация и входные параметры", expanded=False):
        st.caption(
            f"Сервер `{(snapshot.get('server') or {}).get('name', '—')}` · "
            f"транспорт `{snapshot.get('transport', '—')}` · "
            f"инструментов: {len(tools)}"
        )
        for tool in tools:
            st.markdown(f"**`{tool.get('name')}`**")
            st.write(tool.get("description") or "")
            st.json(tool.get("input_schema") or {})
    if not tools:
        st.warning("MCP-сервер не вернул инструменты.")
        return

    st.markdown("#### Вызов из приложения")
    customer_id = st.text_input("ID клиента", value="C-104", key="l17_customer_id")
    with st.container(key="l17_actions"):
        first, second, third, fourth = st.columns(4, gap="small")

        with first:
            with st.popover("Добавить клиента", use_container_width=True):
                st.markdown("#### Новый клиент")
                name = st.text_input("Название клиента", key="l17_new_name")
                email = st.text_input("Email", key="l17_new_email")
                plan = st.selectbox(
                    "Тариф", ["Start", "Pro", "Enterprise"], key="l17_new_plan"
                )
                balance = st.number_input(
                    "Баланс, ₽", min_value=0, step=1000, key="l17_new_balance"
                )
                tickets = st.number_input(
                    "Открытых обращений", min_value=0, step=1, key="l17_new_tickets"
                )
                manager = st.text_input("Менеджер", key="l17_new_manager")
                if st.button("Создать клиента", type="primary", key="l17_create"):
                    _call(
                        "create_customer",
                        {
                            "name": name,
                            "email": email,
                            "plan": plan,
                            "balance_rub": int(balance),
                            "open_tickets": int(tickets),
                            "manager": manager,
                        },
                        "l17_create_result",
                    )
                    st.session_state.pop("l17_list_result", None)

        with second:
            if st.button("Получить всех клиентов", use_container_width=True, key="l17_list"):
                _call("list_customers", {}, "l17_list_result")

        with third:
            if st.button("Вызвать клиента", use_container_width=True, key="l17_call"):
                _call("get_customer", {"customer_id": customer_id}, "l17_tool_result")

        with fourth:
            if st.button("Удалить клиента", use_container_width=True, key="l17_delete"):
                _call("delete_customer", {"customer_id": customer_id}, "l17_delete_result")
                st.session_state.pop("l17_list_result", None)
                st.session_state.pop("l17_tool_result", None)

    result = st.session_state.get("l17_tool_result")
    _show_call_result(result, "l17_tool_result")
    payload = _payload(result)
    if payload and payload.get("ok") and payload.get("customer"):
        st.json(payload["customer"])

    list_result = st.session_state.get("l17_list_result")
    _show_call_result(list_result, "l17_list_result")
    list_payload = _payload(list_result)
    _show_customers(list_payload)
    if list_payload and list_payload.get("ok"):
        st.caption(f"Клиентов в CRM: {list_payload.get('count', 0)}")

    create_result = st.session_state.get("l17_create_result")
    _show_call_result(create_result, "l17_create_result")
    created = _payload(create_result)
    if created and created.get("ok") and created.get("customer"):
        st.success(f"Клиент добавлен: {created['customer'].get('id')}")
        st.json(created["customer"])

    delete_result = st.session_state.get("l17_delete_result")
    _show_call_result(delete_result, "l17_delete_result")
    deleted = _payload(delete_result)
    if deleted and deleted.get("ok") and deleted.get("deleted"):
        st.success(f"Клиент удалён: {deleted['deleted'].get('id')}")


def _render_chat() -> None:
    history = st.session_state.setdefault("l17_history", [])
    for item in history:
        with st.chat_message(item.get("role", "assistant")):
            st.markdown(item.get("content") or "")

    prompt = st.chat_input(
        "Спросите о клиенте, например: Что с клиентом C-104?",
        key="l17_chat_input",
    )
    if not prompt:
        return
    prior = list(history)
    history.append({"role": "user", "content": prompt})
    st.session_state["l17_history"] = history
    selected = st.session_state.get("l17_model_option") or ""
    model = st.session_state.get("l17_models", {}).get(selected) or {}
    payload = {
        "prompt": prompt,
        "model": model.get("id") or "mock-fast",
        "history": prior,
        "max_steps": 4,
    }
    with st.spinner("Агент вызывает MCP-инструмент…"):
        result = _request("POST", "/api/chat", json=payload)
    if isinstance(result, dict) and result.get("_error"):
        history.append({"role": "assistant", "content": f"Ошибка: {result['_error']}"})
    else:
        history.append({"role": "assistant", "content": (result or {}).get("answer") or "Пустой ответ"})
        st.session_state["l17_last"] = result
    st.session_state["l17_history"] = history
    st.rerun()


def render() -> None:
    st.markdown("## Урок 17. Первый инструмент MCP")
    _inject_button_styles()
    st.caption(
        "Свой MCP-сервер вокруг mock CRM API: регистрация инструмента, схема "
        "входных параметров, возврат результата и вызов агентом из чата."
    )

    if "l17_backend_loaded" not in st.session_state:
        models = _request("GET", "/api/models")
        snapshot = _request("POST", "/api/mcp/inspect")
        st.session_state["l17_models_list"] = models if isinstance(models, list) else []
        st.session_state["l17_inspect"] = snapshot if isinstance(snapshot, dict) else {}
        st.session_state["l17_backend_loaded"] = True
    models = st.session_state.get("l17_models_list") or []
    snapshot = st.session_state.get("l17_inspect") or {}

    options, mapping = _model_options(models)
    st.session_state["l17_models"] = mapping
    if not options:
        st.error("API урока 17 не вернул модели.")
        return
    if st.session_state.get("l17_model_option") not in options:
        st.session_state["l17_model_option"] = options[0]
    st.selectbox("Модель", options, key="l17_model_option", label_visibility="collapsed")

    _render_tool(snapshot)

    st.markdown("#### Чат с агентом")
    _render_chat()
    last = st.session_state.get("l17_last")
    if last:
        steps = last.get("steps") or []
        with st.expander(f"Трасса MCP · {len(steps)}", expanded=True):
            for step in steps:
                st.markdown(
                    f"**{step.get('index')}. {step.get('tool') or step.get('label')}** "
                    f"· {step.get('elapsed_ms', 0)} мс"
                )
                st.caption("Аргументы")
                st.json(step.get("arguments") or {})
                st.caption("Результат")
                observation = step.get("result") or {}
                if observation.get("ok"):
                    st.json(observation)
                else:
                    st.error(observation.get("error") or "Ошибка инструмента")
