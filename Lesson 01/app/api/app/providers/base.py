from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import AsyncIterator


class ProviderError(RuntimeError):
    """Error that should be surfaced to the client as a readable message."""

    def __init__(self, message: str, kind: str = "provider_error", status: int = 502):
        super().__init__(message)
        self.kind = kind
        self.status = status


@dataclass
class ProviderRequest:
    messages: list[dict]
    model: str
    temperature: float | None
    reasoning: str
    max_tokens: int | None
    supports_reasoning: bool = False
    supports_temperature: bool = True


@dataclass
class StreamEvent:
    type: str  # "reasoning" | "delta" | "done"
    text: str = ""
    data: dict = field(default_factory=dict)


class Provider(ABC):
    name: str = "base"

    @abstractmethod
    def stream(self, request: ProviderRequest) -> AsyncIterator[StreamEvent]:
        """Async generator yielding reasoning/delta events, then one ``done`` event."""
        raise NotImplementedError


    async def list_remote_models(self) -> list[str]:
        """Models the provider serves (empty by default)."""
        return []

    async def close(self) -> None:  # pragma: no cover - optional cleanup
        return None
