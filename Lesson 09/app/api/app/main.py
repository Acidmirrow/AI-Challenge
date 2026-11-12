"""API урока 09: управление контекстом диалога.

Сервис отдаёт демонстрационный диалог на 25 сообщений, 3 отдельных summary
и показывает, какие сообщения попадут в контекст при выбранной стратегии.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .context import STRATEGY_LABELS, build_context, build_summary_context
from .dialogue import TITLE, demo_messages, demo_summaries
from .history_chat import answer_question
from .schemas import (
    AskOut,
    AskRequest,
    CompressBucket,
    CompressOut,
    CompressRequest,
    ContextOut,
    ContextRequest,
    DemoOut,
    DemoMessage,
    HealthOut,
    SummaryItem,
)
from .tokenizer import count_tokens

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("context-control.api")

app = FastAPI(
    title="Context Control Lab",
    version="1.0.0",
    description="Урок 09: управление контекстом диалога.",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health", response_model=HealthOut)
async def health() -> HealthOut:
    return HealthOut(demo_messages=len(demo_messages()), demo_summaries=len(demo_summaries()))


@app.get("/api/demo-dialogue", response_model=DemoOut)
async def demo_dialogue() -> DemoOut:
    return DemoOut(
        title=TITLE,
        description=(
            "Демонстрационный диалог с вымышленными сроками, суммами, адресом "
            "и параметрами проекта."
        ),
        messages=[DemoMessage(**item) for item in demo_messages()],
        summaries=[SummaryItem(**item) for item in demo_summaries()],
    )


@app.post("/api/context", response_model=ContextOut)
async def context(payload: ContextRequest) -> ContextOut:
    if payload.strategy not in STRATEGY_LABELS:
        raise HTTPException(status_code=400, detail="Неизвестная стратегия контекста")
    items = [item.model_dump() for item in payload.messages]
    summary_items = [item.model_dump() for item in payload.summaries]
    selected = (
        build_summary_context(
            summary_items,
            max_tokens=payload.max_tokens,
            reserve_tokens=payload.reserve_tokens,
            system_tokens=payload.system_tokens,
        )
        if payload.use_summaries
        else build_context(
            items,
            strategy=payload.strategy,
            max_messages=payload.max_messages,
            max_tokens=payload.max_tokens,
            reserve_tokens=payload.reserve_tokens,
            system_tokens=payload.system_tokens,
        )
    )
    return ContextOut(
        strategy=payload.strategy,
        strategy_label=STRATEGY_LABELS[payload.strategy],
        available=selected.available,
        message_budget=selected.message_budget,
        system_tokens=payload.system_tokens,
        included_ids=[item["id"] for item in selected.included],
        dropped_ids=[item["id"] for item in selected.dropped],
        included_tokens=selected.included_tokens,
        context_tokens=selected.context_tokens,
        dropped_tokens=selected.dropped_tokens,
        overflow=selected.overflow,
        fits=selected.fits,
        compressed=payload.use_summaries,
        summary_count=len(payload.summaries),
        message_tokens={
            item["id"]: count_tokens(item.get("content") or "")
            for item in (summary_items if payload.use_summaries else items)
        },
    )


def _space_number(value: int) -> str:
    return f"{value:,}".replace(",", " ")


def _ids_label(ids: list[int]) -> str:
    """Сжать номера сообщений в читаемые диапазоны: 1–12, 15, 20–24."""
    if not ids:
        return "нет"
    ordered = sorted(set(ids))
    ranges: list[str] = []
    start = previous = ordered[0]
    for value in ordered[1:]:
        if value == previous + 1:
            previous = value
            continue
        ranges.append(str(start) if start == previous else f"{start}–{previous}")
        start = previous = value
    ranges.append(str(start) if start == previous else f"{start}–{previous}")
    return ", ".join(f"№{item}" for item in ranges)


def _missing_answer(payload: AskRequest, selected, total: int) -> str:
    included = [item["id"] for item in selected.included]
    dropped = [item["id"] for item in selected.dropped]
    if not total:
        return "История пуста: сначала нажмите «Сформировать диалог»."

    if payload.use_summaries:
        included = [item - 1000 for item in included if item >= 1000]
        dropped = [item - 1000 for item in dropped if item >= 1000]
        details = (
            f"Сжатый контекст: в него вошли summary {_ids_label(included)} "
            f"({len(included)} из {total} summary)"
        )
        if dropped:
            details += f", отброшены summary {_ids_label(dropped)}"
        details += "."
        if not dropped:
            explanation = "Все summary в контексте, но нужного факта в них нет."
        else:
            explanation = (
                "Для сжатия используются summary, а не полные сообщения; "
                "часть summary не помещается в выбранное окно."
            )
        advice = ""
        if dropped:
            advice = (
                f" Увеличьте окно контекста (сейчас {_space_number(payload.max_tokens)} "
                "токенов) или отключите сжатие, чтобы вернуть полные сообщения."
            )
        return f"В контексте нет данных для ответа. {details} {explanation}{advice}"

    label = STRATEGY_LABELS[payload.strategy]
    details = (
        f"Стратегия «{label}»: в контекст вошли {_ids_label(included)} "
        f"({len(included)} из {total} сообщений)"
    )
    if dropped:
        details += f", отброшены {_ids_label(dropped)}"
    details += "."

    if not included:
        explanation = "В контекст не попало ни одного сообщения: лимит или окно токенов слишком малы."
    elif not dropped:
        explanation = "Вся история находится в контексте, но нужного факта в ней нет."
    elif payload.strategy == "budget":
        explanation = (
            "«Бюджет токенов» набирает сообщения с конца диалога, пока хватает "
            "лимита сообщений и окна токенов."
        )
    elif payload.strategy == "last":
        explanation = (
            "«Последние N сообщений» оставляет только хвост истории; всё, что "
            "раньше, в контекст не попадает."
        )
    else:
        explanation = "В выбранной части истории нужного факта нет."

    advice = ""
    if dropped:
        advice = (
            f" Увеличьте «Лимит сообщений» (сейчас {payload.max_messages}) "
            f"или окно контекста (сейчас {_space_number(payload.max_tokens)} токенов) — "
            "либо выберите стратегию «Вся история»."
        )
    return f"В контексте нет данных для ответа. {details} {explanation}{advice}"


@app.post("/api/ask", response_model=AskOut)
async def ask(payload: AskRequest) -> AskOut:
    """Ответить на вопрос только по тем сообщениям, что попали в контекст."""
    if payload.strategy not in STRATEGY_LABELS:
        raise HTTPException(status_code=400, detail="Неизвестная стратегия контекста")
    items = [item.model_dump() for item in payload.messages]
    summary_items = [item.model_dump() for item in payload.summaries]
    selected = (
        build_summary_context(
            summary_items,
            max_tokens=payload.max_tokens,
            reserve_tokens=payload.reserve_tokens,
            system_tokens=payload.system_tokens,
        )
        if payload.use_summaries
        else build_context(
            items,
            strategy=payload.strategy,
            max_messages=payload.max_messages,
            max_tokens=payload.max_tokens,
            reserve_tokens=payload.reserve_tokens,
            system_tokens=payload.system_tokens,
        )
    )
    answer, source_ids = answer_question(payload.question, selected.included)
    if not source_ids:
        answer = _missing_answer(
            payload,
            selected,
            len(payload.summaries) if payload.use_summaries else len(items),
        )
    return AskOut(
        strategy=payload.strategy,
        strategy_label=STRATEGY_LABELS[payload.strategy],
        available=selected.available,
        message_budget=selected.message_budget,
        system_tokens=payload.system_tokens,
        included_ids=[item["id"] for item in selected.included],
        dropped_ids=[item["id"] for item in selected.dropped],
        included_tokens=selected.included_tokens,
        context_tokens=selected.context_tokens,
        dropped_tokens=selected.dropped_tokens,
        overflow=selected.overflow,
        fits=selected.fits,
        compressed=payload.use_summaries,
        summary_count=len(payload.summaries),
        message_tokens={
            item["id"]: count_tokens(item.get("content") or "")
            for item in (summary_items if payload.use_summaries else items)
        },
        question=payload.question,
        answer=answer,
        found=bool(source_ids),
        source_ids=source_ids,
    )


@app.post("/api/compress", response_model=CompressOut)
async def compress(payload: CompressRequest) -> CompressOut:
    """Сравнить полную историю и отдельно хранимые summary по токенам."""
    message_tokens = sum(count_tokens(item.content) for item in payload.messages)
    summary_tokens = sum(
        item.tokens or count_tokens(item.content) for item in payload.summaries
    )
    before = message_tokens + payload.system_tokens
    after = summary_tokens + payload.system_tokens
    available = max(0, payload.max_tokens - payload.reserve_tokens)
    before_fits = before <= available
    after_fits = after <= available
    return CompressOut(
        before=CompressBucket(
            kind="full",
            messages=len(payload.messages),
            summaries=0,
            tokens=before,
            fits=before_fits,
            overflow=max(0, before - available),
        ),
        after=CompressBucket(
            kind="summary",
            messages=0,
            summaries=len(payload.summaries),
            tokens=after,
            fits=after_fits,
            overflow=max(0, after - available),
        ),
        saved_tokens=max(0, before - after),
        saved_percent=round((before - after) / before * 100, 1) if before else 0.0,
    )
