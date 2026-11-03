from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, AsyncIterator


class ProviderError(RuntimeError):
    """Ошибка провайдера в виде, понятном пользователю."""

    def __init__(self, message: str, kind: str = "provider_error", status: int = 502):
        super().__init__(message)
        self.kind = kind
        self.status = status


@dataclass
class ProviderRequest:
    messages: list[dict]
    model: str
    temperature: float | None = None
    reasoning: str = "off"
    max_tokens: int | None = None
    supports_reasoning: bool = False
    supports_temperature: bool = True

    # --- формат ответа ------------------------------------------------------
    response_format: dict | None = None
    stop: list[str] | None = None
    tools: list[dict] | None = None
    tool_choice: Any = None
    schema: dict | None = None
    schema_name: str = "response"
    tool_name: str = "save_result"


@dataclass
class StreamEvent:
    """delta — текст ответа, tool_delta — фрагмент аргументов инструмента."""

    type: str  # "delta" | "tool_delta" | "done"
    text: str = ""
    data: dict = field(default_factory=dict)


class Provider(ABC):
    name: str = "base"

    @abstractmethod
    def stream(self, request: ProviderRequest) -> AsyncIterator[StreamEvent]:
        """Асинхронный генератор: delta/tool_delta … и одно событие done."""
        raise NotImplementedError

    async def close(self) -> None:  # pragma: no cover - опционально
        return None
