"""Форматы ответа: как просить структуру у модели и как её разбирать.

Урок 02 — один и тот же промпт прогоняется через разные способы задания формата:
обычный текст, Markdown, ``json_object``, strict ``json_schema`` и tool call.
Каждый формат знает, как собрать запрос и как извлечь результат.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class FormatSpec:
    id: str
    label: str
    description: str
    needs_schema: bool = False
    uses_tools: bool = False
    system_hint: str = ""


FORMATS: tuple[FormatSpec, ...] = (
    FormatSpec(
        "text",
        "Текст",
        "Обычный ответ. Ничего не навязываем — базовая линия для сравнения.",
        system_hint="Отвечай кратко и по делу.",
    ),
    FormatSpec(
        "markdown",
        "Markdown",
        "Структура через разметку: заголовки, списки, таблицы.",
        system_hint=(
            "Отвечай в Markdown. Если данных несколько — оформи таблицей "
            "с заголовками столбцов, без вступлений и пояснений."
        ),
    ),
    FormatSpec(
        "json_object",
        "JSON (json_object)",
        "response_format=json_object + проверка схемой. Ключи задаёт схема, "
        "модель может добавить лишние — их ловит валидатор.",
        needs_schema=True,
        system_hint=(
            "Верни ТОЛЬКО JSON-объект, без текста вокруг. "
            "Ключи и типы должны строго соответствовать схеме."
        ),
    ),
    FormatSpec(
        "json_schema",
        "JSON Schema (strict)",
        "Строгий structured output: провайдер сам гарантирует схему. "
        "Не все API это умеют — ошибка провайдера показывается как есть.",
        needs_schema=True,
        system_hint="Верни данные строго по JSON Schema.",
    ),
    FormatSpec(
        "tool_call",
        "Tool call",
        "Function calling: аргументы инструмента приходят строкой JSON по схеме.",
        needs_schema=True,
        uses_tools=True,
        system_hint="Заполни аргументы инструмента данными из запроса.",
    ),
)

FORMATS_BY_ID: dict[str, FormatSpec] = {spec.id: spec for spec in FORMATS}

PRESETS: list[dict[str, Any]] = [
    {
        "id": "movie",
        "label": "Фильмы (список)",
        "schema": {
            "type": "object",
            "properties": {
                "movies": {
                    "type": "array",
                    "minItems": 3,
                    "items": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string"},
                            "year": {"type": "integer", "minimum": 1888},
                            "rating": {"type": "number", "minimum": 0, "maximum": 10},
                            "genres": {"type": "array", "items": {"type": "string"}},
                        },
                        "required": ["title", "year", "rating"],
                        "additionalProperties": False,
                    },
                },
                "count": {"type": "integer", "minimum": 1},
            },
            "required": ["movies"],
            "additionalProperties": False,
        },
    },
    {
        "id": "ticket",
        "label": "Тикеты поддержки (список)",
        "schema": {
            "type": "object",
            "properties": {
                "tickets": {
                    "type": "array",
                    "minItems": 3,
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "integer", "minimum": 1},
                            "summary": {"type": "string"},
                            "priority": {"type": "string", "enum": ["low", "medium", "high"]},
                            "needs_human": {"type": "boolean"},
                            "tags": {"type": "array", "items": {"type": "string"}},
                        },
                        "required": ["id", "summary", "priority", "needs_human"],
                        "additionalProperties": False,
                    },
                },
                "count": {"type": "integer", "minimum": 1},
            },
            "required": ["tickets"],
            "additionalProperties": False,
        },
    },
    {
        "id": "planets",
        "label": "Планеты Солнечной системы",
        "schema": {
            "type": "object",
            "properties": {
                "planets": {
                    "type": "array",
                    "minItems": 1,
                    "items": {
                        "type": "object",
                        "properties": {
                            "position": {"type": "integer", "minimum": 1, "maximum": 8},
                            "name": {"type": "string"},
                            "type": {
                                "type": "string",
                                "enum": ["terrestrial", "gas_giant", "ice_giant"],
                            },
                            "moons": {"type": "integer", "minimum": 0},
                            "distance_au": {"type": "number", "exclusiveMinimum": 0},
                        },
                        "required": ["position", "name", "type"],
                        "additionalProperties": False,
                    },
                },
                "count": {"type": "integer", "minimum": 1},
            },
            "required": ["planets"],
            "additionalProperties": False,
        },
    },
    {
        "id": "product",
        "label": "Товары (список)",
        "schema": {
            "type": "object",
            "properties": {
                "products": {
                    "type": "array",
                    "minItems": 3,
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "price": {"type": "number", "exclusiveMinimum": 0},
                            "currency": {"type": "string", "enum": ["RUB", "USD", "EUR"]},
                            "in_stock": {"type": "boolean"},
                            "weight_g": {"type": "number", "exclusiveMinimum": 0},
                        },
                        "required": ["name", "price", "currency", "in_stock"],
                        "additionalProperties": False,
                    },
                },
                "count": {"type": "integer", "minimum": 1},
            },
            "required": ["products"],
            "additionalProperties": False,
        },
    },
]


@dataclass
class FormatRequest:
    """Всё, что нужно провайдеру для одного формата."""

    messages: list[dict]
    response_format: dict | None = None
    tools: list[dict] | None = None
    tool_choice: Any = None
    schema: dict | None = None
    schema_name: str = "response"
    tool_name: str = "save_result"
    notes: list[str] = field(default_factory=list)


def build_format_request(
    spec: FormatSpec,
    prompt: str,
    schema: dict | None,
    *,
    schema_name: str = "response",
    tool_name: str = "save_result",
    reasoning: str = "off",
    system_prompt: str | None = None,
    supports_json_schema: bool = True,
) -> FormatRequest:
    """Собрать сообщения и параметры формата под конкретный провайдер.

    ``system_prompt`` — явное описание формата от пользователя: если задано,
    заменяет встроенную подсказку формата.
    """
    instruction = (system_prompt or "").strip() or spec.system_hint
    messages = [
        {"role": "system", "content": instruction},
        {"role": "user", "content": prompt},
    ]
    notes: list[str] = []

    if not spec.needs_schema:
        return FormatRequest(messages=messages, schema=schema)

    schema = schema or {}
    if spec.id == "json_object":
        messages[0]["content"] += f"\n\nJSON Schema:\n{json.dumps(schema, ensure_ascii=False)}"
        return FormatRequest(
            messages=messages,
            response_format={"type": "json_object"},
            schema=schema,
            schema_name=schema_name,
        )

    if spec.id == "json_schema":
        if supports_json_schema:
            return FormatRequest(
                messages=messages,
                response_format={
                    "type": "json_schema",
                    "json_schema": {"name": schema_name, "strict": True, "schema": schema},
                },
                schema=schema,
                schema_name=schema_name,
            )
        # Провайдер отвечает 400 на strict json_schema (DeepSeek) — обходим тем же
        # контрактом: json_object + схема в описании + локальная валидация.
        messages[0]["content"] += f"\n\nJSON Schema:\n{json.dumps(schema, ensure_ascii=False)}"
        notes.append(
            "Провайдер не поддерживает strict json_schema: отправлен json_object "
            "со схемой в описании, проверка схемы локальная"
        )
        return FormatRequest(
            messages=messages,
            response_format={"type": "json_object"},
            schema=schema,
            schema_name=schema_name,
            notes=notes,
        )

    # tool_call: схема превращается в parameters инструмента
    tool = {
        "type": "function",
        "function": {
            "name": tool_name,
            "description": "Сохранить структурированный результат",
            "parameters": schema,
        },
    }
    forced = {"type": "function", "function": {"name": tool_name}}
    tool_choice: Any = forced
    if reasoning not in ("off", "none"):
        # DeepSeek: «Thinking mode does not support this tool_choice»
        tool_choice = "auto"
        notes.append(
            "Принудительный tool_choice недоступен в thinking-режиме — отправлен tool_choice=auto"
        )
    return FormatRequest(
        messages=messages,
        tools=[tool],
        tool_choice=tool_choice,
        schema=schema,
        schema_name=schema_name,
        tool_name=tool_name,
        notes=notes,
    )


def parse_payload(
    spec: FormatSpec,
    raw_text: str,
    tool_arguments: str,
    tool_name: str | None,
) -> tuple[Any, dict | None, str | None]:
    """Вернуть (распарсенный результат, tool_call, ошибка разбора)."""
    if spec.uses_tools:
        payload = tool_arguments.strip()
        if not payload:
            return None, None, "Модель не вызвала инструмент (tool_calls пуст)"
        try:
            return json.loads(payload), {"name": tool_name, "arguments": payload}, None
        except json.JSONDecodeError as exc:
            return None, {"name": tool_name, "arguments": payload}, f"Аргументы инструмента не JSON: {exc.msg}"

    text = raw_text.strip()
    if spec.id in ("json_object", "json_schema"):
        cleaned = _strip_code_fence(text)
        try:
            return json.loads(cleaned), None, None
        except json.JSONDecodeError as exc:
            return None, None, f"Ответ не является JSON: {exc.msg} (позиция {exc.pos})"
    return text, None, None


def parse_check(spec: FormatSpec, raw_text: str, tool_call: dict | None) -> dict:
    """Можно ли распарсить ответ кодом: json → markdown-таблица → просто текст."""
    payload = (tool_call or {}).get("arguments") if spec.uses_tools else raw_text
    payload = (payload or "").strip()
    if not payload:
        return {"ok": False, "kind": "empty", "detail": "пустой ответ"}

    try:
        json.loads(_strip_code_fence(payload))
        return {"ok": True, "kind": "json", "detail": "json.loads() без ошибок"}
    except json.JSONDecodeError as exc:
        json_detail = f"json.loads: {exc.msg}"

    rows = _markdown_rows(payload)
    if rows >= 1:
        return {"ok": True, "kind": "markdown_table", "detail": f"разобрана таблица, строк данных: {rows}"}

    return {"ok": False, "kind": "text", "detail": json_detail + "; структуры для разбора нет"}


def _markdown_rows(text: str) -> int:
    """Сколько строк данных в markdown-таблице (без заголовка и разделителя)."""
    rows = [line for line in text.splitlines() if line.strip().startswith("|")]
    return max(len(rows) - 2, 0)


def _strip_code_fence(text: str) -> str:
    """Модели любят оборачивать JSON в ```json … ``` — снимаем обёртку."""
    if text.startswith("```"):
        body = text.split("\n", 1)[1] if "\n" in text else ""
        if body.rstrip().endswith("```"):
            body = body.rstrip()[:-3]
        return body.strip()
    return text
