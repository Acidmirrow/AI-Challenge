"""Минимальный клиент OpenCode Go для урока 11.

Ключ и base_url читаются только на сервере из properties-файлов или переменных
окружения. В тестах и без ключа возвращается безопасный локальный ответ.
"""

from __future__ import annotations

import json
import os
import re
import socket
import ssl
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

class LLMError(RuntimeError):
    """Ошибка провайдера с причиной и подсказкой по исправлению."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        hint: str | None = None,
        status_code: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.hint = hint
        self.status_code = status_code
        self.details = details or {}


def _http_hint(status: int) -> str:
    if status in (401, 403):
        return (
            "Проверьте OPENCODE_GO_API_KEY / x-opencode-session и права ключа; "
            "после исправления повторите шаг."
        )
    if status == 429:
        return "Слишком много запросов или исчерпана квота. Подождите и повторите шаг."
    if status >= 500:
        return "Провайдер временно недоступен. Повторите шаг через минуту."
    return "Проверьте параметры запроса к провайдеру и повторите шаг."


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
    choices = data.get("choices") or []
    finish_reason = choices[0].get("finish_reason") if choices else None
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
        "finish_reason": finish_reason,
    }


def chat_with_usage(
    messages: list[dict[str, Any]],
    model: str | None = None,
    max_tokens: int = 1_200,
    temperature: float = 0.4,
    reasoning_effort: str | None = None,
    strict: bool = False,
) -> tuple[str, str, dict[str, Any]]:
    """Вернуть (ответ, модель, usage) — единый источник токенов для UI.

    strict=True не подменяет ошибку провайдера fallback-ответом, а бросает
    LLMError с причиной и подсказкой. Это нужно для шагов задачи, где пустой
    ответ нельзя выдавать за результат.
    """
    selected_model = model or DEFAULT_MODEL
    key, base = _credentials()
    if not key:
        error = LLMError(
            "missing_api_key",
            "Ключ OpenCode Go не найден в secrets.properties или переменных окружения.",
            hint=(
                "Добавьте opencode_go.api.key в config/secrets.properties "
                "(файл не коммитится) и перезапустите API."
            ),
        )
        if strict:
            raise error
        answer = fallback_answer()
        return answer, "fallback", _usage_from_response({}, messages, answer)
    # DeepSeek V4.1 сначала расходует токены на reasoning. Без явного low
    # при небольшом max_tokens content часто приходит пустым.
    effort = (
        reasoning_effort
        if reasoning_effort is not None
        else os.getenv("OPENCODE_GO_REASONING_EFFORT", "low").strip()
    )
    payload = {
        "model": selected_model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }
    if effort:
        payload["reasoning_effort"] = effort

    def _send(body: dict[str, Any]) -> dict[str, Any]:
        req = urllib.request.Request(
            base + "/chat/completions",
            data=json.dumps(body).encode("utf-8"),
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
        context = ssl._create_unverified_context()  # локальный учебный контейнер
        try:
            with urllib.request.urlopen(req, timeout=120, context=context) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            raw = ""
            try:
                raw = exc.read().decode("utf-8", errors="replace")[:800]
            except Exception:  # noqa: BLE001
                pass
            detail = raw
            try:
                parsed = json.loads(raw)
                detail = (
                    (parsed.get("error") or {}).get("message")
                    or parsed.get("message")
                    or raw
                )
            except Exception:  # noqa: BLE001
                pass
            raise LLMError(
                f"http_{exc.code}",
                f"Провайдер вернул HTTP {exc.code}: {detail or 'без описания'}",
                hint=_http_hint(exc.code),
                status_code=exc.code,
                details={"body": detail[:500]},
            ) from exc
        except (TimeoutError, socket.timeout, urllib.error.URLError) as exc:
            raise LLMError(
                "network_error",
                f"Не удалось связаться с провайдером: {type(exc).__name__}: {exc}",
                hint=(
                    "Проверьте сеть, OPENCODE_GO_BASE_URL и доступность провайдера; "
                    "затем повторите шаг."
                ),
            ) from exc
        except Exception as exc:  # noqa: BLE001
            raise LLMError(
                "provider_error",
                f"Ошибка провайдера: {type(exc).__name__}: {exc}",
                hint="Повторите шаг; если ошибка повторяется — проверьте ключ и base URL.",
            ) from exc

    try:
        data = _send(payload)
        choices = data.get("choices") or []
        if not choices:
            raise LLMError(
                "empty_response",
                "Провайдер вернул ответ без choices.",
                hint="Повторите шаг; проверьте модель и параметры запроса.",
                details={"response_keys": sorted(data.keys())[:20]},
            )
        choice = choices[0]
        answer = ((choice.get("message") or {}).get("content") or "").strip()
        if not answer:
            # Пустой content обычно означает, что reasoning исчерпал лимит.
            retry = dict(payload)
            retry["max_tokens"] = max(int(max_tokens) * 2, 4_096)
            retry["reasoning_effort"] = "low"
            data = _send(retry)
            choices = data.get("choices") or []
            choice = choices[0] if choices else {}
            answer = ((choice.get("message") or {}).get("content") or "").strip()
        if not answer:
            finish = choice.get("finish_reason")
            usage = data.get("usage") or {}
            raise LLMError(
                "empty_response",
                "Провайдер вернул пустой content даже после повтора.",
                hint=(
                    "Увеличьте max_tokens, оставьте reasoning_effort=low "
                    "или повторите шаг; проверьте finish_reason в деталях."
                ),
                details={"finish_reason": finish, "usage": usage},
            )
        return answer, selected_model, _usage_from_response(data, messages, answer)
    except LLMError as exc:
        if strict:
            raise
        print(
            f"opencode-go error model={selected_model}: {exc.code}: {exc.message}",
            flush=True,
        )
        answer = fallback_answer()
        return answer, "fallback", _usage_from_response({}, messages, answer)
    except Exception as exc:  # noqa: BLE001
        error = LLMError(
            "provider_error",
            f"Ошибка обработки ответа провайдера: {type(exc).__name__}: {exc}",
            hint="Повторите шаг; если ошибка повторяется — проверьте формат ответа провайдера.",
        )
        if strict:
            raise error from exc
        print(f"opencode-go error model={selected_model}: {error.message}", flush=True)
        answer = fallback_answer()
        return answer, "fallback", _usage_from_response({}, messages, answer)


def chat(messages: list[dict[str, Any]], model: str | None = None) -> tuple[str, str]:
    """Совместимый wrapper: вернуть только (ответ, модель)."""
    answer, selected_model, _ = chat_with_usage(messages, model=model)
    return answer, selected_model
