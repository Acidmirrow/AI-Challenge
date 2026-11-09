from __future__ import annotations

import asyncio
import json
import re
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

        tool_name: str | None = None
        if uses_tools and self._is_agent(request):
            call = self._agent_call(request)
            if call is None:
                full = self._agent_final(request)
                text = full[:budget_chars]
                async for piece in self._chunks(text, 8):
                    yield StreamEvent("delta", text=piece)
                finish = "length" if len(full) > budget_chars else "stop"
            else:
                tool_name, arguments = call
                full = json.dumps(arguments, ensure_ascii=False)
                text = full[:budget_chars]
                async for piece in self._chunks(text, 12):
                    yield StreamEvent("tool_delta", text=piece)
                finish = "length" if len(full) > budget_chars else "tool_calls"
        elif uses_tools:
            full = json.dumps(self._sample(request.schema or {}), ensure_ascii=False)
            text = full[:budget_chars]
            async for piece in self._chunks(text, 12):
                yield StreamEvent("tool_delta", text=piece)
            finish = "length" if len(full) > budget_chars else "tool_calls"
        elif is_json:
            full = json.dumps(self._sample(request.schema or {}), ensure_ascii=False, indent=2)
            text = full[:budget_chars]
            async for piece in self._chunks(text, 12):
                yield StreamEvent("delta", text=piece)
            finish = "length" if len(full) > budget_chars else "stop"
        else:
            full = self._prose(request)
            text = full[:budget_chars]
            async for piece in self._chunks(text, 8):
                yield StreamEvent("delta", text=piece)
            finish = "length" if len(full) > budget_chars else "stop"

        yield StreamEvent(
            "done",
            data={
                "model": request.model,
                "elapsed_ms": int((time.perf_counter() - started) * 1000),
                "finish_reason": finish,
                "tool_name": tool_name if uses_tools and self._is_agent(request) else (
                    request.tool_name if uses_tools else None
                ),
                "prompt_tokens": sum(len(m.get("content", "")) for m in request.messages) // 4,
                "completion_tokens": min(len(text) // 4, request.max_tokens or 10_000),
                "mock": True,
            },
        )

    # -- helpers --------------------------------------------------------------
    @staticmethod
    def _is_agent(request: ProviderRequest) -> bool:
        """Агентские инструменты узнаём по именам функций."""
        names = {
            (item.get("function") or {}).get("name")
            for item in request.tools or []
            if isinstance(item, dict)
        }
        return bool(names & {
            "calculator", "current_time", "text_stats", "currency_rates",
            "unit_converter", "date_diff", "number_base", "number_stats", "text_hash",
        })

    def _agent_call(self, request: ProviderRequest) -> tuple[str, dict[str, Any]] | None:
        """Демо-выбор инструмента: после наблюдения модель уже даёт итог."""
        if any(message.get("role") == "tool" for message in request.messages):
            return None
        question = next(
            (m.get("content", "") for m in reversed(request.messages) if m.get("role") == "user"),
            "",
        )
        low = question.lower()
        if any(token in low for token in ("sha256", "sha-256", "md5", "хеш", "хэш")):
            return "text_hash", {"text": question, "algorithm": "sha256"}
        if any(token in low for token in ("шестнадцатерич", "двоичн", "hex", "binary")):
            return "number_base", {"value": "255", "from_base": 10, "to_base": 16}
        if any(token in low for token in ("сколько дней", "разница дат", "через")):
            return "date_diff", {"start": "2026-01-01", "end": "2026-11-09"}
        if any(token in low for token in ("километр", "метр", "кг", "фунт", "литр")):
            return "unit_converter", {"value": 5, "from_unit": "km", "to_unit": "m"}
        if any(token in low for token in ("среднее", "медиан", "статистика чисел")):
            return "number_stats", {"numbers": [2, 4, 6]}
        if any(token in low for token in ("курс", "валют", "доллар", "евро", "рубл")):
            return "currency_rates", {"base": "USD", "targets": ["RUB", "EUR"]}
        if "слов" in low:
            return "text_stats", {"text": question}
        if "врем" in low or "час" in low:
            return "current_time", {"timezone": "Europe/Moscow"}
        return "calculator", {"expression": "17 * 4"}

    @staticmethod
    def _agent_final(request: ProviderRequest) -> str:
        observation = next(
            (m.get("content", "") for m in reversed(request.messages) if m.get("role") == "tool"),
            "{}",
        )
        return (
            "**Демо-агент (mock).** Задача выполнена без внешней модели. "
            f"Наблюдение инструмента: `{observation[:300]}`"
        )

    def _prose(self, request: ProviderRequest) -> str:
        question = request.messages[-1]["content"] if request.messages else ""
        # проверяющий совет возвращает JSON — демо тоже должно его отдавать
        if "verdicts" in question or "верни json" in question.lower():
            ids = re.findall(r"id=([A-Za-z_]+)", question)
            verdicts = [
                {
                    "expert": expert_id,
                    "verdict": "ok" if index % 2 == 0 else "wrong",
                    "comment": "демо-проверка: арифметика сходится"
                    if index % 2 == 0 else "демо-проверка: расхождение в счёте",
                }
                for index, expert_id in enumerate(ids)
            ]
            return json.dumps({"verdicts": verdicts, "final_answer": "демо-ответ совета"},
                              ensure_ascii=False)
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
            # держим minItems, иначе демо-ответ не проходит схему списков
            count = max(int(schema.get("minItems", 1) or 1), 1)
            return [self._sample(schema.get("items") or {}) for _ in range(min(count, 10))]
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
