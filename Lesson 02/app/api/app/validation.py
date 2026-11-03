"""Проверка ответа модели по JSON Schema (Draft 2020-12)."""

from __future__ import annotations

import re
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError


class InvalidSchema(ValueError):
    """Схема в запросе сама по себе некорректна."""


def check_schema(schema: dict[str, Any]) -> None:
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise InvalidSchema(f"Некорректная JSON Schema: {exc.message}") from exc


def validate(instance: Any, schema: dict[str, Any]) -> list[dict[str, str]]:
    """Список ошибок вида {path, message, validator}; пусто = валидно.

    ``required`` и ``additionalProperties`` разворачиваются по полям — так в UI
    видно конкретный ключ, а не общее сообщение в корне объекта.
    """
    if not schema:
        return []
    validator = Draft202012Validator(schema)
    errors: list[dict[str, str]] = []

    for err in sorted(validator.iter_errors(instance), key=lambda e: list(e.absolute_path)):
        if err.validator == "required":
            missing = [
                prop
                for prop in (err.validator_value or [])
                if not isinstance(instance, dict) or prop not in instance
            ]
            for prop in missing:
                errors.append(
                    {"path": prop, "message": "обязательное поле отсутствует", "validator": "required"}
                )
            continue

        if err.validator == "additionalProperties":
            extras = re.findall(r"'([^']+)' was unexpected", err.message)
            for prop in extras or ["(root)"]:
                errors.append(
                    {
                        "path": prop,
                        "message": "лишнее поле — схема запрещает дополнительные ключи",
                        "validator": "additionalProperties",
                    }
                )
            continue

        errors.append(
            {
                "path": "/".join(str(part) for part in err.absolute_path) or "(root)",
                "message": err.message,
                "validator": str(err.validator),
            }
        )
    return errors


def error_digest(errors: list[dict[str, str]]) -> str:
    """Компактный текст ошибок для промпта-исправления."""
    return "\n".join(f"- {item['path']}: {item['message']}" for item in errors)


def repair_messages(original: list[dict], raw_answer: str, errors: list[dict[str, str]]) -> list[dict]:
    """Сообщения второго прохода: показать модели её ответ и список нарушений."""
    return [
        *original,
        {"role": "assistant", "content": raw_answer},
        {
            "role": "user",
            "content": (
                "Ответ не прошёл валидацию по JSON Schema:\n"
                f"{error_digest(errors)}\n\n"
                "Верни исправленный JSON-объект целиком, без пояснений и без ```."
            ),
        },
    ]
