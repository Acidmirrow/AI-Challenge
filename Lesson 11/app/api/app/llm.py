"""Минимальный клиент OpenCode Go для урока 11.

Ключ и base_url читаются только на сервере из properties-файлов или переменных
окружения. В тестах и без ключа возвращается безопасный локальный ответ.
"""

from __future__ import annotations

import json
import os
import re
import ssl
import urllib.request
from pathlib import Path
from typing import Any

DEFAULT_MODEL = os.getenv("OPENCODE_GO_MODEL", "deepseek-v4.1-flash")
PRO_MODEL = os.getenv("OPENCODE_GO_PRO_MODEL", "deepseek-v4-pro")
DEFAULT_BASE_URL = "https://opencode.ai/zen/go/v1"
APP_FILE = Path(os.getenv("CONFIG_FILE", "/srv/config/app.properties"))
SECRETS_FILE = Path(os.getenv("SECRETS_FILE", "/srv/config/secrets.properties"))


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def _normalize(key: str) -> str:
    return re.sub(r"[.\-\s]+", "_", key.strip()).lower()


def _properties() -> dict[str, str]:
    data: dict[str, str] = {}
    for path in (APP_FILE, SECRETS_FILE):
        if not path.is_file():
            continue
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line[0] in "#!" or "=" not in line:
                continue
            key, value = line.split("=", 1)
            data[_normalize(key)] = _unquote(value)
    return data


def _credentials() -> tuple[str, str]:
    values = _properties()
    key = os.getenv("OPENCODE_GO_API_KEY", "").strip() or values.get(
        "opencode_go_api_key", ""
    )
    base = os.getenv("OPENCODE_GO_BASE_URL", "").strip() or values.get(
        "opencode_go_base_url", DEFAULT_BASE_URL
    )
    return key, base.rstrip("/")


def fallback_answer() -> str:
    return (
        "Модель сейчас недоступна. Проверьте ключ и соединение; "
        "контекст памяти уже собран и сохранён."
    )


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def _usage_from_response(data: dict[str, Any], messages: list[dict[str, Any]], answer: str) -> dict[str, Any]:
    raw = data.get("usage") or {}
    prompt_tokens = raw.get("prompt_tokens")
    completion_tokens = raw.get("completion_tokens")
    total_tokens = raw.get("total_tokens")
    estimated = prompt_tokens is None or completion_tokens is None
    if prompt_tokens is None:
        prompt_tokens = _estimate_tokens(
            json.dumps(messages, ensure_ascii=False, separators=(",", ":"))
        )
    if completion_tokens is None:
        completion_tokens = _estimate_tokens(answer)
    if total_tokens is None:
        total_tokens = int(prompt_tokens) + int(completion_tokens)
    return {
        "prompt_tokens": int(prompt_tokens),
        "completion_tokens": int(completion_tokens),
        "total_tokens": int(total_tokens),
        "estimated": bool(estimated),
    }


def chat_with_usage(
    messages: list[dict[str, Any]], model: str | None = None
) -> tuple[str, str, dict[str, Any]]:
    """Вернуть (ответ, модель, usage) — единый источник токенов для UI."""
    selected_model = model or DEFAULT_MODEL
    key, base = _credentials()
    if not key:
        answer = fallback_answer()
        return answer, "fallback", _usage_from_response({}, messages, answer)
    payload = {
        "model": selected_model,
        "messages": messages,
        "temperature": 0.4,
        "max_tokens": 1_200,
        "stream": False,
    }
    request = urllib.request.Request(
        base + "/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "AIChallenge/1.0",
            "HTTP-Referer": "https://ai-challenge.local",
            "X-Title": "AI Challenge",
            "x-opencode-session": "ai-challenge",
        },
        method="POST",
    )
    try:
        context = ssl._create_unverified_context()  # локальный учебный контейнер
        with urllib.request.urlopen(request, timeout=120, context=context) as response:
            data = json.load(response)
        answer = data["choices"][0]["message"]["content"].strip()
        answer = answer or fallback_answer()
        return answer, selected_model, _usage_from_response(data, messages, answer)
    except Exception as exc:  # noqa: BLE001
        print(f"opencode-go error model={selected_model}: {type(exc).__name__}: {exc}", flush=True)
        answer = fallback_answer()
        return answer, "fallback", _usage_from_response({}, messages, answer)


def chat(messages: list[dict[str, Any]], model: str | None = None) -> tuple[str, str]:
    """Совместимый wrapper: вернуть только (ответ, модель)."""
    answer, selected_model, _ = chat_with_usage(messages, model=model)
    return answer, selected_model
