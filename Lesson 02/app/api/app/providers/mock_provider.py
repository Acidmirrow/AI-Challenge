from __future__ import annotations

import asyncio
import json
import time
from typing import Any, AsyncGenerator, AsyncIterator

from .base import Provider, ProviderRequest, StreamEvent


class MockProvider(Provider):
    """Офлайн-провайдер для урока: отдаёт структуру без обращения к API.

    Формат определяется по запросу: есть tools → tool-аргументы, есть
    response_format → JSON, иначе текст/Markdown.
    """

    name = "mock"
    chunk_delay_s = 0.012

    async def stream(self, request: ProviderRequest) -> AsyncIterator[StreamEvent]:
        started = time.perf_counter()
        uses_tools = bool(request.tools)
        is_json = bool(request.response_format) or uses_tools
        # как настоящий провайдер: не отдаём больше бюджета, чем разрешено
        budget_chars = (request.max_tokens or 1024) * 4

        if uses_tools:
            payload = json.dumps(self._sample(request.schema or {}), ensure_ascii=False)[:budget_chars]
            async for piece in self._chunks(payload, 12):
                yield StreamEvent("tool_delta", text=piece)
            finish = "tool_calls"
            text = ""
        elif is_json:
            text = json.dumps(self._sample(request.schema or {}), ensure_ascii=False, indent=2)[:budget_chars]
            async for piece in self._chunks(text, 12):
                yield StreamEvent("delta", text=piece)
            finish = "stop"
        else:
            text = self._prose(request)[:budget_chars]
            async for piece in self._chunks(text, 8):
                yield StreamEvent("delta", text=piece)
            finish = "stop"

        yield StreamEvent(
            "done",
            data={
                "model": request.model,
                "elapsed_ms": int((time.perf_counter() - started) * 1000),
                "finish_reason": finish,
                "tool_name": request.tool_name if uses_tools else None,
                "prompt_tokens": sum(len(m.get("content", "")) for m in request.messages) // 4,
                "completion_tokens": min(len(text) // 4, request.max_tokens or 10_000),
                "mock": True,
            },
        )

    # -- helpers --------------------------------------------------------------
    def _prose(self, request: ProviderRequest) -> str:
        question = request.messages[-1]["content"] if request.messages else ""
        if any("Markdown" in m.get("content", "") for m in request.messages[:1]):
            return (
                "| Поле | Значение |\n|---|---|\n"
                f"| Запрос | {question[:60]} |\n"
                "| Режим | офлайн (mock) |\n"
                "| Формат | Markdown-таблица |"
            )
        # ответ намеренно длинный: видно, как работает max_tokens
        filler = (
            " Модель продолжает перечислять детали: факт за фактом, строка за строкой,"
            " чтобы ответ был достаточно длинным для проверки лимита."
        )
        return (
            f"**Демо-ответ (mock).** Запрос: «{question[:80]}».\n\n"
            "Текст без структуры: модель отвечает как получится, "
            "парсить такое можно только эвристиками." + filler * 10
        )

    def _sample(self, schema: dict[str, Any]) -> Any:
        """Сгенерировать правдоподобный объект по JSON Schema."""
        if schema.get("enum"):
            return schema["enum"][0]
        schema_type = schema.get("type")
        if schema_type == "object" or "properties" in schema:
            return {
                key: self._sample(value)
                for key, value in (schema.get("properties") or {}).items()
            }
        if schema_type == "array":
            return [self._sample(schema.get("items") or {})]
        if schema_type == "integer":
            return int(schema.get("minimum", 2024))
        if schema_type == "number":
            return float(schema.get("minimum", 9.5))
        if schema_type == "boolean":
            return True
        return "пример"

    async def _chunks(self, text: str, size: int) -> AsyncGenerator[str, None]:
        for index in range(0, len(text), size):
            yield text[index : index + size]
            await asyncio.sleep(self.chunk_delay_s)
