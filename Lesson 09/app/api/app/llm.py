"""Минимальный клиент DeepSeek для чата уроков 09/10.

Ключ и base_url читаются только на сервере из смонтированных properties-файлов
или переменных окружения. Если провайдер недоступен, возвращается безопасный
локальный ответ, чтобы интерфейс не падал.
"""

from __future__ import annotations

import json
import os
import re
import ssl
import urllib.request
from pathlib import Path
from typing import Any

DEFAULT_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-flash")
PRO_MODEL = os.getenv("DEEPSEEK_PRO_MODEL", "deepseek-v4-pro")
DEFAULT_BASE_URL = "https://api.deepseek.com/v1"
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
    key = os.getenv("DEEPSEEK_API_KEY", "").strip() or values.get("deepseek_api_key", "")
    base = os.getenv("DEEPSEEK_BASE_URL", "").strip() or values.get(
        "deepseek_base_url", DEFAULT_BASE_URL
    )
    return key, base.rstrip("/")


def fallback_answer() -> str:
    return (
        "DeepSeek сейчас недоступен. Проверьте ключ и соединение; "
        "после восстановления я смогу отвечать по диалогу."
    )


def chat(messages: list[dict[str, Any]], model: str | None = None) -> tuple[str, str]:
    """Вернуть (ответ, модель)."""
    selected_model = model or DEFAULT_MODEL
    key, base = _credentials()
    if not key:
        return fallback_answer(), "fallback"
    payload = {
        "model": selected_model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Ты дружелюбный ИИ-помощник. Отвечай по-русски, кратко "
                    "и по существу. Не выдумывай факты о проекте, которого нет "
                    "в контексте."
                ),
            },
            *messages,
        ],
        "temperature": 0.6,
        # reasoning-модель тратит часть лимита на reasoning_content
        "max_tokens": 2_000 if selected_model == PRO_MODEL else 500,
        "stream": False,
    }
    request = urllib.request.Request(
        base + "/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        context = ssl._create_unverified_context()  # локальный учебный контейнер
        with urllib.request.urlopen(request, timeout=120, context=context) as response:
            data = json.load(response)
        answer = data["choices"][0]["message"]["content"].strip()
        return answer or fallback_answer(), selected_model
    except Exception as exc:
        print(f"deepseek error model={selected_model}: {type(exc).__name__}: {exc}", flush=True)
        return fallback_answer(), "fallback"


def chat_with_context(
    question: str, context: str, model: str | None = None
) -> tuple[str, str]:
    prompt = (
        "Ответь на вопрос пользователя, используя только приведённый контекст. "
        "Если ответа в контексте нет, честно скажи об этом.\n\n"
        f"Контекст:\n{context}\n\nВопрос: {question}"
    )
    return chat([{"role": "user", "content": prompt}], model=model)
