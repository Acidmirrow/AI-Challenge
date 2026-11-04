from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

from .config import get_settings
from .council import (
    REVIEWERS,
    REVIEWERS_BY_ID,
    SOLVERS,
    SOLVERS_BY_ID,
    expert_id,
    parse_review,
    review_messages,
)
from .models_catalog import ModelInfo, build_catalog
from .properties import loaded_files
from .providers import Provider, ProviderError, ProviderRequest, build_provider
from .schemas import (
    AnswerOut,
    AnswerRequest,
    ChatRequest,
    CompareRequest,
    CouncilOut,
    HealthOut,
    ModelOut,
    ReviewerOut,
    ReviewOut,
    ReviewRequest,
    SolverOut,
    StrategyOut,
)
from .strategies import STRATEGIES, STRATEGIES_BY_ID, Strategy, get_strategy, split_answer

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("reasoning-lab.api")


def create_app() -> FastAPI:
    settings = get_settings()
    catalog = build_catalog(settings)

    app = FastAPI(
        title="AI Reasoning Lab",
        version="1.0.0",
        description="Урок 03: способы рассуждений — от прямого ответа до CoT и самопроверки.",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()] or ["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.settings = settings
    app.state.catalog = catalog

    holder: dict[str, Provider] = {}

    def provider(name: str | None = None) -> Provider:
        key = name or app.state.settings.provider
        if key not in holder:
            holder[key] = build_provider(app.state.settings, key)
        return holder[key]

    @app.exception_handler(ProviderError)
    async def _provider_error(_request, exc: ProviderError) -> JSONResponse:
        logger.warning("provider error (%s): %s", exc.kind, exc)
        return JSONResponse({"detail": str(exc), "kind": exc.kind}, status_code=exc.status)

    # -- routes ---------------------------------------------------------------
    @app.get("/", include_in_schema=False)
    async def index() -> dict:
        return {"service": "ai-reasoning-lab", "docs": "/docs", "health": "/api/health"}

    @app.get("/api/health", response_model=HealthOut)
    async def health() -> HealthOut:
        try:
            provider()
        except ProviderError as exc:
            return HealthOut(
                status="degraded",
                provider=settings.provider_label,
                detail=str(exc),
                strategies=len(STRATEGIES),
                config_files=loaded_files(),
            )
        return HealthOut(
            status="ok",
            provider=settings.provider_label,
            strategies=len(STRATEGIES),
            config_files=loaded_files(),
        )

    @app.get("/api/models", response_model=list[ModelOut])
    async def models() -> list[ModelOut]:
        return [ModelOut(**model.as_dict()) for model in app.state.catalog.all()]

    @app.get("/api/strategies", response_model=list[StrategyOut])
    async def strategies() -> list[StrategyOut]:
        return [StrategyOut(**item.as_dict()) for item in STRATEGIES]

    @app.post("/api/chat")
    async def chat(payload: ChatRequest) -> StreamingResponse:
        model = _model(app, payload.model)
        strategy = _strategy(payload.strategy)
        reasoning = _resolve_reasoning(model, payload.reasoning)
        active = provider(model.provider)
        logger.info(
            "chat strategy=%s model=%s reasoning=%s max_tokens=%s",
            strategy.id,
            model.id,
            reasoning,
            payload.max_tokens,
        )
        messages = [{"role": "system", "content": strategy.system_prompt}]
        messages += [item.model_dump() for item in payload.messages]
        return StreamingResponse(
            _stream_chat(active, strategy, model, messages, payload, reasoning),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
        )

    @app.post("/api/compare")
    async def compare(payload: CompareRequest) -> list[dict]:
        model = _model(app, payload.model)
        reasoning = _resolve_reasoning(model, payload.reasoning)
        active = provider(model.provider)
        chosen: list[Strategy] = (
            [_strategy(item) for item in payload.strategies]
            if payload.strategies
            else STRATEGIES
        )
        results: list[dict] = []
        for strategy in chosen:
            messages = [
                {"role": "system", "content": strategy.system_prompt},
                {"role": "user", "content": payload.prompt},
            ]
            results.append(await _one_shot(active, strategy, model, messages, payload, reasoning))
        return results

    # -- совет экспертов ------------------------------------------------------
    @app.get("/api/council", response_model=CouncilOut)
    async def council() -> CouncilOut:
        return CouncilOut(
            solvers=[SolverOut(**member.as_dict()) for member in SOLVERS],
            reviewers=[ReviewerOut(**member.as_dict()) for member in REVIEWERS],
        )

    @app.post("/api/council/answer", response_model=AnswerOut)
    async def council_answer(payload: AnswerRequest) -> AnswerOut:
        solver = SOLVERS_BY_ID.get(payload.expert)
        if solver is None:
            raise HTTPException(status_code=400, detail=f"Неизвестный эксперт: {payload.expert}")
        model = _model(app, payload.model)
        active = provider(model.provider)
        reasoning = _soft_reasoning(model, solver.reasoning)
        messages = [
            {"role": "system", "content": solver.system_prompt()},
            {"role": "user", "content": payload.prompt},
        ]
        started = time.perf_counter()
        raw, native, finish_reason, usage = "", "", None, {}
        async for event in active.stream(
            ProviderRequest(
                messages=messages,
                model=model.id,
                temperature=solver.temperature if model.supports_temperature else None,
                reasoning=reasoning,
                max_tokens=payload.max_tokens,
                supports_reasoning=model.supports_reasoning,
                supports_temperature=model.supports_temperature,
            )
        ):
            if event.type == "reasoning":
                native += event.text
            elif event.type == "delta":
                raw += event.text
            elif event.type == "done":
                finish_reason = event.data.get("finish_reason")
                usage = {
                    key: event.data[key]
                    for key in ("prompt_tokens", "completion_tokens", "total_tokens")
                    if key in event.data
                }

        strategy = STRATEGIES_BY_ID[solver.strategy]
        head, answer = split_answer(strategy, raw)
        return AnswerOut(
            expert=solver.id,
            label=solver.label,
            strategy=solver.strategy,
            answer=answer or raw.strip(),
            reasoning=head or native,
            usage=usage,
            elapsed_ms=int((time.perf_counter() - started) * 1000),
            finish_reason=finish_reason,
            truncated=finish_reason == "length",
        )

    @app.post("/api/council/review", response_model=ReviewOut)
    async def council_review(payload: ReviewRequest) -> ReviewOut:
        reviewer = REVIEWERS_BY_ID.get(payload.reviewer)
        if reviewer is None:
            raise HTTPException(status_code=400, detail=f"Неизвестный проверяющий: {payload.reviewer}")
        model = _model(app, payload.model)
        active = provider(model.provider)
        reasoning = _soft_reasoning(model, reviewer.reasoning)
        messages = [
            {"role": "system", "content": reviewer.system_prompt([m.as_dict() for m in SOLVERS])},
            *review_messages(payload.prompt, payload.answers),
        ]
        started = time.perf_counter()
        raw, finish_reason, usage = "", None, {}
        async for event in active.stream(
            ProviderRequest(
                messages=messages,
                model=model.id,
                temperature=reviewer.temperature if model.supports_temperature else None,
                reasoning=reasoning,
                max_tokens=payload.max_tokens,
                supports_reasoning=model.supports_reasoning,
                supports_temperature=model.supports_temperature,
            )
        ):
            if event.type == "delta":
                raw += event.text
            elif event.type == "done":
                finish_reason = event.data.get("finish_reason")
                usage = {
                    key: event.data[key]
                    for key in ("prompt_tokens", "completion_tokens", "total_tokens")
                    if key in event.data
                }

        parsed = parse_review(raw, [expert_id(item) for item in payload.answers])
        return ReviewOut(
            reviewer=reviewer.id,
            label=reviewer.label,
            verdicts=parsed["verdicts"],
            final_answer=parsed["final_answer"],
            parsed=parsed["parsed"],
            raw_text=raw.strip(),
            usage=usage,
            elapsed_ms=int((time.perf_counter() - started) * 1000),
        )

    return app


# -- helpers ------------------------------------------------------------------
def _model(app: FastAPI, model_id: str) -> ModelInfo:
    model = app.state.catalog.get(model_id)
    if model is None:
        raise HTTPException(status_code=400, detail=f"Неизвестная модель: {model_id}")
    return model


def _strategy(strategy_id: str) -> Strategy:
    try:
        return get_strategy(strategy_id)
    except KeyError as exc:
        raise HTTPException(status_code=400, detail=str(exc.args[0])) from exc


def _resolve_reasoning(model: ModelInfo, requested: str) -> str:
    if not model.reasoning_levels:
        return "off"
    if requested == "off":
        return "off"
    if requested not in model.reasoning_levels:
        raise HTTPException(
            status_code=400,
            detail=f"Модель {model.id} не поддерживает reasoning={requested!r}. "
            f"Доступно: {', '.join(model.reasoning_levels)}",
        )
    return requested


def _soft_reasoning(model: ModelInfo, wanted: str) -> str:
    """Уровень роли: если модель его не умеет — берём ближайший доступный."""
    levels = list(model.reasoning_levels)
    if not levels:
        return "off"
    if wanted in levels:
        return wanted
    return "none" if "none" in levels else levels[0]


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _request(model: ModelInfo, messages: list[dict], payload, reasoning: str) -> ProviderRequest:
    return ProviderRequest(
        messages=messages,
        model=model.id,
        temperature=payload.temperature if model.supports_temperature else None,
        reasoning=reasoning,
        max_tokens=payload.max_tokens,
        supports_reasoning=model.supports_reasoning,
        supports_temperature=model.supports_temperature,
    )


async def _stream_chat(
    provider_obj: Provider,
    strategy: Strategy,
    model: ModelInfo,
    messages: list[dict],
    payload: ChatRequest,
    reasoning: str,
) -> AsyncIterator[str]:
    raw, native_reasoning = "", ""
    finish_reason: str | None = None
    usage: dict = {}
    started = time.perf_counter()

    try:
        yield _sse(
            "start",
            {
                "strategy": strategy.id,
                "strategy_label": strategy.label,
                "model": model.id,
                "system_prompt": strategy.system_prompt,
                "reasoning": reasoning,
            },
        )
        async for event in provider_obj.stream(_request(model, messages, payload, reasoning)):
            if event.type == "reasoning":
                native_reasoning += event.text
                yield _sse("reasoning", {"text": event.text})
            elif event.type == "delta":
                raw += event.text
                yield _sse("delta", {"text": event.text})
            elif event.type == "done":
                finish_reason = event.data.get("finish_reason")
                usage = {
                    key: event.data[key]
                    for key in ("prompt_tokens", "completion_tokens", "total_tokens")
                    if key in event.data
                }

        reasoning_part, answer_part = split_answer(strategy, raw)
        yield _sse(
            "result",
            {
                "strategy": strategy.id,
                "strategy_label": strategy.label,
                "model": model.id,
                "raw_text": raw,
                "reasoning_part": reasoning_part,
                "answer_part": answer_part,
                "native_reasoning": native_reasoning,
                "shows_reasoning": strategy.shows_reasoning,
                "usage": usage,
                "finish_reason": finish_reason,
                "truncated": finish_reason == "length",
                "elapsed_ms": int((time.perf_counter() - started) * 1000),
                "max_tokens": payload.max_tokens,
            },
        )
    except ProviderError as exc:
        logger.warning("chat error (%s): %s", exc.kind, exc)
        yield _sse("error", {"message": str(exc), "kind": exc.kind})
    except asyncio.CancelledError:
        raise
    except Exception:  # noqa: BLE001 - не светим трейсбек в UI
        logger.exception("unhandled error in chat")
        yield _sse("error", {"message": "Внутренняя ошибка при обработке ответа.", "kind": "internal"})


async def _one_shot(
    provider_obj: Provider,
    strategy: Strategy,
    model: ModelInfo,
    messages: list[dict],
    payload: CompareRequest,
    reasoning: str,
) -> dict:
    raw, native_reasoning = "", ""
    finish_reason: str | None = None
    usage: dict = {}
    started = time.perf_counter()
    try:
        async for event in provider_obj.stream(_request(model, messages, payload, reasoning)):
            if event.type == "reasoning":
                native_reasoning += event.text
            elif event.type == "delta":
                raw += event.text
            elif event.type == "done":
                finish_reason = event.data.get("finish_reason")
                usage = {
                    key: event.data[key]
                    for key in ("prompt_tokens", "completion_tokens", "total_tokens")
                    if key in event.data
                }
    except ProviderError as exc:
        return {
            "strategy": strategy.id,
            "error": str(exc),
            "elapsed_ms": int((time.perf_counter() - started) * 1000),
        }

    reasoning_part, answer_part = split_answer(strategy, raw)
    return {
        "strategy": strategy.id,
        "strategy_label": strategy.label,
        "answer": answer_part or raw.strip(),
        "reasoning": reasoning_part or native_reasoning,
        "usage": usage,
        "elapsed_ms": int((time.perf_counter() - started) * 1000),
        "finish_reason": finish_reason,
        "truncated": finish_reason == "length",
    }


app = create_app()
