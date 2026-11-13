"""API урока 10: сравнение стратегий управления контекстом."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from .agent import ContextAgent
from .llm import PRO_MODEL, chat as model_chat, chat_with_context
from .qa import answer_question, context_text
from .strategies import STRATEGIES, build_strategies

TITLE = "Управление контекстом: Сравнение стратегий"

agent = ContextAgent()

app = FastAPI(
    title="Context Strategy Lab",
    version="0.3.0",
    description="Урок 10: сравнение стратегий управления контекстом.",
)


class Message(BaseModel):
    id: int
    role: str
    content: str
    tokens: int = 0


class Summary(BaseModel):
    id: int
    from_id: int
    to_id: int
    content: str
    tokens: int = 0


class CompareRequest(BaseModel):
    messages: list[Message] = Field(default_factory=list, max_length=60)
    summaries: list[Summary] = Field(default_factory=list, max_length=12)
    sliding_window: int = Field(default=10, ge=1, le=50)
    facts_window: int = Field(default=6, ge=1, le=50)


class AskRequest(CompareRequest):
    strategy: str = "sliding"
    question: str = Field(min_length=1, max_length=1_000)



class AnalyzeRequest(BaseModel):
    strategies: list[dict] = Field(default_factory=list)
    branch: str = ""
    trunk_count: int = 0
    branch_count: int = 0


@app.post("/api/analyze")
async def analyze(payload: AnalyzeRequest) -> dict:
    """Развёрнутый анализ стратегий; для анализа используется deepseek-v4-pro."""
    rows = payload.strategies
    prompt = (
        "Ты аналитик контекстного агента. Ниже результаты сравнения стратегий "
        "управления контекстом для диалога с общим стволом и выбранной веткой. "
        "Дай развёрнутый вывод по каждому сценарию использования: когда выбирать "
        "Sliding window, Sticky facts, Summary блоки и полную историю. Укажи "
        "компромиссы полноты, стоимости и сложности, а также итоговую рекомендацию. "
        "Пиши по-русски, структурированно, без выдуманных чисел.\n\n"
        f"Ствол: {payload.trunk_count} сообщений. Ветка «{payload.branch}»: "
        f"{payload.branch_count} сообщений.\n"
        f"Результаты: {rows}"
    )
    answer, model = await run_in_threadpool(
        model_chat, [{"role": "user", "content": prompt}], model=PRO_MODEL
    )
    if not answer.strip():
        answer = (
            "Не удалось получить текст анализа от deepseek-v4-pro. "
            "Сравнение стратегий доступно в таблице выше."
        )
    return {"analysis": answer, "model": model}


@app.post("/api/chat")
async def chat(payload: dict) -> dict:
    """Свободный чат с моделью без генерации диалога."""
    messages = payload.get("messages") or []
    answer, model = await run_in_threadpool(model_chat, messages)
    return {"answer": answer, "model": model}

@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok", "lesson": 10, "title": TITLE, "agent": agent.name, "strategies": list(agent.strategies)}


@app.get("/api/strategies")
async def strategies() -> dict:
    return {"title": TITLE, "strategies": STRATEGIES}


@app.get("/api/generate")
async def generate() -> dict:
    """Создать новый уникальный диалог: ствол 25 сообщений и три ветки."""
    return agent.generate()


@app.post("/api/compare")
async def compare(payload: CompareRequest) -> dict:
    rows = agent.rows(
        [item.model_dump() for item in payload.messages],
        [item.model_dump() for item in payload.summaries],
        sliding_window=payload.sliding_window,
        facts_window=payload.facts_window,
    )
    return {
        "title": TITLE,
        "sliding_window": payload.sliding_window,
        "facts_window": payload.facts_window,
        "strategies": rows,
    }


@app.post("/api/ask")
async def ask(payload: AskRequest) -> dict:
    return await run_in_threadpool(
        agent.ask,
        [item.model_dump() for item in payload.messages],
        [item.model_dump() for item in payload.summaries],
        payload.strategy,
        payload.question,
        sliding_window=payload.sliding_window,
        facts_window=payload.facts_window,
    )
