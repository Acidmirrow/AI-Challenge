"""Один запрос к модели без стриминга наружу: текст, reasoning и usage."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from .providers import Provider, ProviderRequest


@dataclass
class Completion:
    text: str = ""
    reasoning: str = ""
    usage: dict[str, int] = field(default_factory=dict)
    finish_reason: str | None = None
    elapsed_ms: int = 0


async def complete(
    provider: Provider,
    *,
    model: str,
    messages: list[dict[str, Any]],
    temperature: float | None,
    reasoning: str,
    max_tokens: int | None,
    supports_reasoning: bool,
    supports_temperature: bool,
) -> Completion:
    """Собрать полный ответ провайдера из SSE-событий."""
    request = ProviderRequest(
        messages=messages,
        model=model,
        temperature=temperature if supports_temperature else None,
        reasoning=reasoning,
        max_tokens=max_tokens,
        supports_reasoning=supports_reasoning,
        supports_temperature=supports_temperature,
    )
    started = time.perf_counter()
    result = Completion()
    async for event in provider.stream(request):
        if event.type == "delta":
            result.text += event.text
        elif event.type == "reasoning":
            result.reasoning += event.text
        elif event.type == "done":
            result.finish_reason = event.data.get("finish_reason")
            result.usage = {
                key: int(event.data[key])
                for key in ("prompt_tokens", "completion_tokens", "total_tokens")
                if event.data.get(key) is not None
            }
    result.elapsed_ms = int((time.perf_counter() - started) * 1000)
    return result
