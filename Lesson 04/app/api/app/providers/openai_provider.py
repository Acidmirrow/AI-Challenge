from __future__ import annotations

import time
from typing import AsyncIterator

import httpx
import openai
from openai import AsyncOpenAI

from ..config import Settings
from .base import Provider, ProviderError, ProviderRequest, StreamEvent


class OpenAIProvider(Provider):
    """Любой OpenAI-совместимый /chat/completions (DeepSeek, OpenAI, шлюзы)."""

    name = "openai"

    def __init__(self, settings: Settings, name: str = ""):
        self.name = name or settings.provider
        api_key, base_url = settings.credentials(self.name)
        if not api_key:
            raise ProviderError(
                f"Не задан ключ `{self.name}.api.key`. Добавь его в config/secrets.properties "
                "и перезапусти контейнер api.",
                kind="not_configured",
                status=503,
            )
        self._settings = settings
        self._base_url = base_url
        extra: dict = {}
        if self.name == "nous" and settings.nous_host_header:
            # broker-прокси отказывает «чужим» Host: подставляем его loopback-имя
            extra["default_headers"] = {"Host": settings.nous_host_header}
        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=settings.http_timeout_s,
            **extra,
        )

    # -- request building -----------------------------------------------------
    def _kwargs(self, request: ProviderRequest) -> dict:
        settings = self._settings
        kwargs: dict = {
            "model": request.model,
            "messages": request.messages,
            "stream": True,
        }

        if request.temperature is not None and request.supports_temperature:
            kwargs["temperature"] = request.temperature

        if request.max_tokens:
            param = settings.max_tokens_param or (
                "max_completion_tokens" if request.supports_reasoning else "max_tokens"
            )
            kwargs[param] = request.max_tokens

        if (
            settings.reasoning_param
            and request.supports_reasoning
            and request.reasoning not in ("", "off")
        ):
            kwargs[settings.reasoning_param] = request.reasoning

        if request.stop:
            kwargs["stop"] = request.stop

        # --- формат ответа ---------------------------------------------------
        if request.response_format:
            kwargs["response_format"] = request.response_format
        if request.tools:
            kwargs["tools"] = request.tools
            if request.tool_choice is not None:
                kwargs["tool_choice"] = request.tool_choice

        if settings.include_usage:
            kwargs["stream_options"] = {"include_usage": True}

        return kwargs

    # -- streaming ------------------------------------------------------------
    async def stream(self, request: ProviderRequest) -> AsyncIterator[StreamEvent]:
        started = time.perf_counter()
        usage: dict = {}
        finish_reason: str | None = None
        tool_name: str | None = None
        try:
            stream = await self._client.chat.completions.create(**self._kwargs(request))
        except openai.APIStatusError as exc:
            raise ProviderError(_humanize(exc), kind=_kind(exc), status=502) from exc
        except openai.APIConnectionError as exc:
            raise ProviderError(
                f"Нет соединения с {self._base_url}: {exc}", kind="connection"
            ) from exc

        try:
            async for chunk in stream:
                if getattr(chunk, "usage", None):
                    usage = {
                        "prompt_tokens": chunk.usage.prompt_tokens,
                        "completion_tokens": chunk.usage.completion_tokens,
                        "total_tokens": chunk.usage.total_tokens,
                    }
                if not getattr(chunk, "choices", None):
                    continue
                choice = chunk.choices[0]
                if choice.finish_reason:
                    finish_reason = choice.finish_reason
                delta = choice.delta

                reasoning_piece = getattr(delta, "reasoning_content", None)
                if reasoning_piece:
                    yield StreamEvent("reasoning", text=reasoning_piece)

                if delta.content:
                    yield StreamEvent("delta", text=delta.content)

                for call in getattr(delta, "tool_calls", None) or []:
                    function = getattr(call, "function", None)
                    if function is None:
                        continue
                    if getattr(function, "name", None):
                        tool_name = function.name
                    if getattr(function, "arguments", None):
                        yield StreamEvent("tool_delta", text=function.arguments)
        except openai.APIError as exc:
            raise ProviderError(_humanize(exc), kind=_kind(exc), status=502) from exc

        yield StreamEvent(
            "done",
            data={
                "model": request.model,
                "elapsed_ms": int((time.perf_counter() - started) * 1000),
                "finish_reason": finish_reason,
                "tool_name": tool_name,
                **usage,
            },
        )

    # -- model discovery ------------------------------------------------------
    async def list_remote_models(self) -> list[str]:
        url = self._base_url.rstrip("/") + "/models"
        headers = {"Authorization": f"Bearer {self._client.api_key}"}
        if self.name == "nous" and self._settings.nous_host_header:
            headers["Host"] = self._settings.nous_host_header
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            payload = response.json()
        return [item["id"] for item in payload.get("data", []) if "id" in item]

    async def close(self) -> None:
        await self._client.close()


def _kind(exc: Exception) -> str:
    status = getattr(exc, "status_code", None)
    if status == 401:
        return "auth"
    if status == 402:
        return "payment"
    if status == 429:
        return "rate_limit"
    if status in (400, 404, 422):
        return "bad_request"
    return "upstream"


def _humanize(exc: Exception) -> str:
    status = getattr(exc, "status_code", None)
    body = getattr(exc, "message", None) or str(exc)
    if status == 401:
        return "Провайдер отклонил ключ (401). Проверь токен в config/secrets.properties."
    if status == 402:
        return (
            "Провайдер вернул 402: запрос без действующего ключа или вне бесплатного "
            "тарифа. Для Nous Portal нужен ключ `nous.api.key` — план Free открывает "
            "модели с суффиксом `:free`."
        )
    if status == 429:
        return "Провайдер вернул 429: лимит запросов или квота исчерпаны."
    if status in (400, 422):
        if "response_format" in str(body):
            return (
                f"Провайдер не поддерживает этот формат ответа: {body}. "
                "Попробуй json_object или tool_call."
            )
        return f"Провайдер отклонил параметры запроса: {body}"
    if status == 404:
        return f"Модель или endpoint не найдены (404): {body}"
    return f"Ошибка провайдера: {body}"
