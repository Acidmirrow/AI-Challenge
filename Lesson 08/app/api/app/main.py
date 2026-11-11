"""API урока 08: оценка токенов и бюджета контекста.

Токенизация учебная (regex-аппроксимация), без обращения к провайдеру.
Сервис показывает, сколько места текст занимает в контексте и что останется
после резерва под ответ.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .models import BY_ID, DEFAULT_MODEL, MODELS
from .schemas import (
    AnalyzeOut,
    CompareOut,
    CompareRequest,
    ContextMetrics,
    DialogueOut,
    DialogueRequest,
    DialogueTurn,
    AnalyzeRequest,
    HealthOut,
    ModelOut,
    PresetsOut,
    PresetOut,
    TokenPreview,
    TruncateOut,
    TruncateRequest,
)
from .tokenizer import repeat_to_tokens, token_stats, truncate_to_tokens

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("token-lab.api")

PRESETS = (
    PresetOut(
        id="russian",
        label="Русский текст",
        text=(
            "Контекстное окно модели — это весь текст, который она может "
            "обработать за один запрос: системная инструкция, история диалога "
            "и место под ответ. Чем длиннее история, тем меньше остаётся "
            "токенов на новый ответ."
        ),
    ),
    PresetOut(
        id="english",
        label="English text",
        text=(
            "A token is not a word. The same sentence can take a different "
            "number of tokens depending on the model, the language and the "
            "amount of punctuation."
        ),
    ),
    PresetOut(
        id="code",
        label="Фрагмент кода",
        text=(
            "def count_tokens(text: str) -> int:\n"
            "    return len(text.split())\n\n"
            "print(count_tokens('hello token world'))"
        ),
    ),
    PresetOut(
        id="long",
        label="Длинный текст",
        text=(
            "Контекст — это ограниченный ресурс. "
            "Каждый вызов инструмента, каждое наблюдение и каждая реплика "
            "диалога занимают место в контекстном окне. "
        ) * 40,
    ),
)

def _context_metrics(
    text: str,
    *,
    kind: str,
    label: str,
    model,
    reserve: int,
    available: int,
) -> ContextMetrics:
    stats = token_stats(text)
    tokens = int(stats["tokens"])
    fits = tokens <= available
    kept_tokens = tokens if fits else min(tokens, available)
    input_cost = kept_tokens / 1_000_000 * model.input_price_per_1m
    output_cost = reserve / 1_000_000 * model.output_price_per_1m
    return ContextMetrics(
        kind=kind,
        label=label,
        chars=int(stats["chars"]),
        words=int(stats["words"]),
        tokens=tokens,
        tokens_per_word=float(stats["tokens_per_word"]),
        input_cost=round(input_cost, 8),
        output_cost=round(output_cost, 8),
        total_cost=round(input_cost + output_cost, 8),
        fits=fits,
        copies=available // tokens if tokens and available else 0,
        overflow=max(0, tokens - available),
        kept_tokens=kept_tokens,
        dropped_tokens=max(0, tokens - kept_tokens),
        truncated_tokens=kept_tokens if not fits else 0,
    )


app = FastAPI(title="Token Lab", version="1.0.0", description="Урок 08: работа с токенами.")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _model(model_id: str):
    model = BY_ID.get(model_id)
    if model is None:
        raise HTTPException(status_code=400, detail=f"Неизвестная модель: {model_id}")
    return model


@app.get("/api/health", response_model=HealthOut)
async def health() -> HealthOut:
    return HealthOut(models=len(MODELS))


@app.get("/api/models", response_model=list[ModelOut])
async def models() -> list[ModelOut]:
    return [model.as_out() for model in MODELS]


@app.get("/api/presets", response_model=PresetsOut)
async def presets() -> PresetsOut:
    return PresetsOut(presets=list(PRESETS))


@app.post("/api/analyze", response_model=AnalyzeOut)
async def analyze(payload: AnalyzeRequest) -> AnalyzeOut:
    model = _model(payload.model)
    stats = token_stats(payload.text)
    available = max(0, model.context_window - payload.output_reserve)
    tokens = int(stats["tokens"])
    fits = tokens <= available
    copies = available // tokens if tokens and available else 0
    overflow = max(0, tokens - available)
    truncated_text, truncated_tokens = ("", 0)
    if not fits:
        truncated_text, truncated_tokens = truncate_to_tokens(payload.text, available)

    kept_tokens = min(tokens, available) if not fits else tokens
    full_input_cost = tokens / 1_000_000 * model.input_price_per_1m
    input_cost = kept_tokens / 1_000_000 * model.input_price_per_1m
    output_cost = payload.output_reserve / 1_000_000 * model.output_price_per_1m
    data = {
        **stats,
        "preview": [TokenPreview(**item) for item in stats["preview"]],
        "input_price_per_1m": model.input_price_per_1m,
        "output_price_per_1m": model.output_price_per_1m,
        "kept_tokens": kept_tokens,
        "dropped_tokens": max(0, tokens - kept_tokens),
        "full_input_cost": round(full_input_cost, 8),
        "input_cost": round(input_cost, 8),
        "output_cost": round(output_cost, 8),
        "total_cost": round(input_cost + output_cost, 8),
    }
    return AnalyzeOut(
        model=model.id,
        label=model.label,
        context_window=model.context_window,
        output_max=model.output_max,
        output_reserve=payload.output_reserve,
        available=available,
        **data,
        fits=fits,
        copies=copies,
        overflow=overflow,
        truncated_text=truncated_text,
        truncated_tokens=truncated_tokens,
    )


@app.post("/api/compare", response_model=CompareOut)
async def compare(payload: CompareRequest) -> CompareOut:
    """Сравнить минимальный, большой и превышающий окно контексты."""
    model = _model(payload.model)
    window = min(model.context_window, payload.demo_window)
    available = max(0, window - payload.output_reserve)
    base = payload.base_text.strip() or PRESETS[0].text

    minimal_text = base
    large_target = max(1, int(available * 0.7))
    maximal_target = max(1, int(available * 1.2))
    large_text = repeat_to_tokens(base, large_target)
    maximal_text = repeat_to_tokens(base, maximal_target)

    contexts = [
        _context_metrics(
            minimal_text,
            kind="minimal",
            label="Минимальный",
            model=model,
            reserve=payload.output_reserve,
            available=available,
        ),
        _context_metrics(
            large_text,
            kind="large",
            label="Большой в пределах окна",
            model=model,
            reserve=payload.output_reserve,
            available=available,
        ),
        _context_metrics(
            maximal_text,
            kind="maximal",
            label="Максимальный с превышением",
            model=model,
            reserve=payload.output_reserve,
            available=available,
        ),
    ]

    dependencies = [
        "Пока текст помещается, токены и стоимость входа растут почти линейно "
        "с объёмом текста; после обрезки оплачивается только помещающаяся часть.",
        "Стоимость выхода зависит от резерва под ответ, а не от размера входа; "
        "у всех трёх вариантов резерв одинаков.",
        "Большой контекст ещё помещается, но оставляет меньше свободного места; "
        "максимальный приходится обрезать, теряя часть текста.",
        f"При доступном бюджете {available:,} токенов превышение максимального "
        f"варианта составляет {contexts[2].overflow:,} токенов.".replace(",", " "),
    ]

    return CompareOut(
        model=model.id,
        label=model.label,
        context_window=model.context_window,
        demo_window=window,
        output_reserve=payload.output_reserve,
        available=available,
        contexts=contexts,
        dependencies=dependencies,
    )


@app.post("/api/dialogue", response_model=DialogueOut)
async def dialogue(payload: DialogueRequest) -> DialogueOut:
    """Показать, как растут prompt-токены и стоимость по ходам диалога."""
    model = _model(payload.model)
    window = min(model.context_window, payload.demo_window)
    history = payload.system_tokens
    cumulative_cost = 0.0
    total_tokens = 0
    first_overflow_turn: int | None = None
    first_overflow_tokens = 0
    turns: list[DialogueTurn] = []

    for turn_no in range(1, payload.turns + 1):
        prompt_tokens = history + payload.user_tokens
        completion_tokens = payload.assistant_tokens
        total = prompt_tokens + completion_tokens
        overflow = max(0, total - window)
        fits = overflow == 0
        if not fits and first_overflow_turn is None:
            first_overflow_turn = turn_no
            first_overflow_tokens = overflow

        input_cost = prompt_tokens / 1_000_000 * model.input_price_per_1m
        output_cost = completion_tokens / 1_000_000 * model.output_price_per_1m
        turn_cost = input_cost + output_cost
        cumulative_cost += turn_cost
        total_tokens += total
        turns.append(
            DialogueTurn(
                turn=turn_no,
                history_tokens=history,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                input_cost=round(input_cost, 8),
                output_cost=round(output_cost, 8),
                total_cost=round(turn_cost, 8),
                cumulative_cost=round(cumulative_cost, 8),
                fits=fits,
                overflow=overflow,
            )
        )
        history += payload.user_tokens + payload.assistant_tokens

    risks = [
        "Системная инструкция и схемы инструментов могут быть отброшены при "
        "наивной обрезке — модель теряет правила и перестаёт вызывать инструменты.",
        "Ранние факты из диалога исчезают: модель повторяет вопросы или противоречит себе.",
        "Если обрезать assistant.tool_calls без role=tool, запрос к API становится "
        "некорректным: вызов остаётся без наблюдения.",
        "Провайдер может отклонить запрос целиком, если prompt + completion больше окна.",
        "Стоимость не исчезает: каждый следующий ход всё равно отправляет всю "
        "оставшуюся историю заново.",
    ]
    return DialogueOut(
        model=model.id,
        label=model.label,
        context_window=model.context_window,
        demo_window=window,
        turns=turns,
        total_cost=round(cumulative_cost, 8),
        total_tokens=total_tokens,
        first_overflow_turn=first_overflow_turn,
        first_overflow_tokens=first_overflow_tokens,
        risks=risks,
    )


@app.post("/api/truncate", response_model=TruncateOut)
async def truncate(payload: TruncateRequest) -> TruncateOut:
    text, tokens = truncate_to_tokens(payload.text, payload.max_tokens)
    original = int(token_stats(payload.text)["tokens"])
    return TruncateOut(
        text=text,
        tokens=tokens,
        chars=len(text),
        original_tokens=original,
        dropped_tokens=max(0, original - tokens),
    )
