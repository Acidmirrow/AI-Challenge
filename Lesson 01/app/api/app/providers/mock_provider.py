from __future__ import annotations

import asyncio
import time
from typing import AsyncGenerator, AsyncIterator

from .base import Provider, ProviderRequest, StreamEvent


class MockProvider(Provider):
    """Offline provider: no network, deterministic output, real streaming.

    Exists so the whole Docker stack (UI → API → SSE) can be demoed and tested
    without an API key. Set PROVIDER=openai to talk to a real model.
    """

    name = "mock"
    chunk_delay_s = 0.02

    async def stream(self, request: ProviderRequest) -> AsyncIterator[StreamEvent]:
        started = time.perf_counter()
        question = request.messages[-1]["content"].strip()

        reasoning_chars = 0
        if request.reasoning != "off":
            plan = self._reasoning_plan(request, question)
            reasoning_chars = len(plan)
            async for piece in self._chunks(plan, 14):
                yield StreamEvent("reasoning", text=piece)

        answer = self._answer(request, question)
        async for piece in self._chunks(answer, 4):
            yield StreamEvent("delta", text=piece)
            await asyncio.sleep(self.chunk_delay_s)

        yield StreamEvent(
            "done",
            data={
                "model": request.model,
                "elapsed_ms": int((time.perf_counter() - started) * 1000),
                "prompt_tokens": sum(len(m["content"]) for m in request.messages) // 4,
                "completion_tokens": (len(answer) + reasoning_chars) // 4,
                "mock": True,
            },
        )

    def _reasoning_plan(self, request: ProviderRequest, question: str) -> str:
        effort = {"low": "быстрый", "medium": "средний", "high": "глубокий"}.get(
            request.reasoning, "обычный"
        )
        return (
            f"Пользователь спрашивает: «{question}».\n"
            f"Выбран режим рассуждений: {effort} (reasoning_effort={request.reasoning}).\n"
            "Шаги: 1) выделить суть вопроса; 2) проверить, каких данных не хватает; "
            "3) сформулировать короткий ответ без лишних деталей; 4) убедиться, что он "
            "не противоречит вопросу.\n\n"
        )

    def _answer(self, request: ProviderRequest, question: str) -> str:
        temperature = (
            f"{request.temperature:.1f}"
            if request.supports_temperature and request.temperature is not None
            else "не поддерживается моделью"
        )
        reasoning = request.reasoning if request.supports_reasoning else "не поддерживается"
        return (
            f"**Демо-ответ (mock-провайдер).**\n\n"
            f"Ты написал: «{question}»\n\n"
            f"- модель: `{request.model}`\n"
            f"- температура: `{temperature}`\n"
            f"- reasoning: `{reasoning}`\n"
            f"- max tokens: `{request.max_tokens}`\n\n"
            "Этот ответ сгенерирован офлайн, без обращения к внешнему API — "
            "стек работает целиком: Streamlit → FastAPI → SSE → браузер. "
            "Чтобы получить ответ настоящей модели, задай `provider` в "
            "`config/app.properties` и токен в `config/secrets.properties`."
        )

    async def _chunks(self, text: str, size: int) -> AsyncGenerator[str, None]:
        for index in range(0, len(text), size):
            yield text[index : index + size]
            await asyncio.sleep(self.chunk_delay_s / 2)
