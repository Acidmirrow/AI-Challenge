"""API урока 05: одна задача — несколько моделей, параллельно, с ценой прогона.

Отличие от урока 04: там крутили температуру одной модели, здесь сравниваем
сами модели. Один и тот же промпт уходит в выбранные модели одновременно
(`asyncio.gather`), каждая отвечает своим провайдером, а рядом с ответом едут
время, токены и стоимость по прайсу (`config/pricing.properties`).
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

from .checker import answer_is_correct
from .config import get_settings
from .models_catalog import FREE_PROVIDERS, ModelInfo, build_catalog, free_models_from
from .pricing import cost_of, load_prices
from .properties import loaded_files
from .providers import Provider, ProviderError, ProviderRequest, build_provider
from .schemas import (
    AnalyzeOut,
    AnalyzeRequest,
    BenchmarkAnalyzeOut,
    BenchmarkAnalyzeRequest,
    BenchmarkModel,
    BenchmarkOut,
    BenchmarkRequest,
    BenchmarkRun,
    ChatRequest,
    CompareOut,
    CompareRequest,
    CompareRun,
    HealthOut,
    ModelOut,
    TaskOut,
)
from .tasks import TASKS, TASKS_BY_ID

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("models-lab.api")


#: Подписи провайдеров для индикаторов доступности
PROVIDER_LABELS = {
    "openai": "OpenAI",
    "deepseek": "DeepSeek",
    "gemini": "Gemini",
    "openrouter": "OpenRouter",
    "nous": "Nous Portal",
    "mock": "Демо",
}


async def _load_free_models(settings, catalog) -> None:
    """Список бесплатных моделей берём из /models провайдера при старте."""
    for name in FREE_PROVIDERS:
        api_key, _ = settings.credentials(name)
        if not api_key:
            continue
        try:
            remote = await build_provider(settings, name).list_remote_models()
        except Exception as exc:  # noqa: BLE001 - провайдер не отвечает
            logger.warning("free provider %s недоступен: %s", name, exc)
            # не выходим: для OpenRouter и Nous Portal есть запасные списки, остальные пропускаем
            remote = []
        models = free_models_from(name, remote)
        if models:
            catalog.extend(models)
            logger.info("free provider %s: %d моделей", name, len(models))


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _model(app: FastAPI, model_id: str) -> ModelInfo:
    model = app.state.catalog.get(model_id)
    if model is None:
        raise HTTPException(status_code=400, detail=f"Неизвестная модель: {model_id}")
    return model


def _soft_reasoning(model: ModelInfo, wanted: str) -> str:
    """Уровень reasoning, который модель реально понимает (иначе off)."""
    levels = list(model.reasoning_levels or ())
    if not levels:
        return "off"
    if wanted in levels:
        return wanted
    return "none" if "none" in levels else levels[0]


def _text_of(messages: list[dict]) -> list[dict]:
    return [{"role": item["role"], "content": item["content"]} for item in messages]


async def _collect(active: Provider, request: ProviderRequest) -> tuple[str, str, str | None, dict]:
    """Слить поток провайдера в текст: (ответ, reasoning, finish_reason, usage)."""
    raw, native, finish_reason, usage = "", "", None, {}
    async for event in active.stream(request):
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
    return raw, native, finish_reason, usage


def _usage_total(usage: dict) -> int:
    """Всего токенов прогона: провайдер может не прислать total_tokens — считаем сумму частей."""
    total = int(usage.get("total_tokens") or 0)
    if total:
        return total
    return int(usage.get("prompt_tokens") or 0) + int(usage.get("completion_tokens") or 0)


def _verdicts(raw: str) -> dict[tuple[str, str], bool]:
    """Разобрать JSON судьи: (task, model) → верно/неверно."""
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text.split("\n", 1)[1] if "\n" in text else text
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return {}
    try:
        payload = json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return {}
    result: dict[tuple[str, str], bool] = {}
    for item in payload.get("verdicts") or []:
        task = str(item.get("task") or "")
        model = str(item.get("model") or "")
        correct = item.get("correct")
        if task and model and isinstance(correct, bool):
            result[(task, model)] = correct
    return result


def create_app() -> FastAPI:
    settings = get_settings()
    catalog = build_catalog(settings)
    prices = load_prices(settings.pricing_file)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        await _load_free_models(settings, catalog)
        yield

    app = FastAPI(
        title="AI Models Lab",
        version="1.0.0",
        description="Урок 05: одна задача на нескольких моделях — параллельные ответы, время, токены, стоимость.",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()] or ["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.settings = settings
    app.state.catalog = catalog
    app.state.prices = prices

    holder: dict[str, Provider] = {}

    def provider(name: str | None = None) -> Provider:
        key = name or app.state.settings.provider
        if key not in holder:
            holder[key] = build_provider(app.state.settings, key)
        return holder[key]

    @app.exception_handler(ProviderError)
    async def _provider_error(_request, exc: ProviderError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status,
            content={"detail": str(exc), "kind": exc.kind},
        )

    @app.get("/api/health", response_model=HealthOut)
    async def health() -> HealthOut:
        try:
            provider().name  # провайдер строится без сети: проверяем только наличие ключа
        except ProviderError as exc:
            return HealthOut(
                status="degraded",
                provider=settings.provider_label,
                detail=str(exc),
                tasks=len(TASKS),
                config_files=loaded_files(),
            )
        return HealthOut(
            status="ok",
            provider=settings.provider_label,
            tasks=len(TASKS),
            config_files=loaded_files(),
        )

    @app.get("/api/tasks", response_model=list[TaskOut])
    async def tasks() -> list[TaskOut]:
        return [TaskOut(**task.as_dict()) for task in TASKS]

    @app.get("/api/providers/status")
    async def providers_status() -> list[dict]:
        """Живая проверка доступности провайдеров — с кешем на минуту."""
        now = time.time()
        cached = getattr(app.state, "provider_status", None)
        if cached and now - cached["at"] < 60:
            return cached["data"]

        names = [settings.provider] if settings.provider != "mock" else []
        names += [name for name in FREE_PROVIDERS if name not in names]
        rows: list[dict] = []
        for name in names:
            api_key, _ = settings.credentials(name)
            row = {
                "provider": name,
                "label": PROVIDER_LABELS.get(name, name.title()),
                "configured": bool(api_key),
                "available": False,
                "models": sum(1 for model in catalog.all() if model.provider == name),
                "latency_ms": 0,
                "error": "",
            }
            if api_key and name != "mock":
                started = time.perf_counter()
                try:
                    await build_provider(settings, name).list_remote_models()
                    row["available"] = True
                except Exception as exc:  # noqa: BLE001 - статус и есть ответ
                    row["error"] = str(exc)[:200]
                row["latency_ms"] = int((time.perf_counter() - started) * 1000)
            rows.append(row)

        app.state.provider_status = {"at": now, "data": rows}
        return rows

    @app.post("/api/models/refresh")
    async def refresh_models() -> dict:
        """Перечитать список бесплатных моделей без перезапуска контейнера."""
        await _load_free_models(settings, catalog)
        return {"models": len(catalog.all())}

    @app.get("/api/models", response_model=list[ModelOut])
    async def models() -> list[ModelOut]:
        return [ModelOut(**model.as_dict()) for model in app.state.catalog.all()]

    @app.post("/api/chat")
    async def chat(payload: ChatRequest) -> StreamingResponse:
        model = _model(app, payload.model)
        active = provider(model.provider)
        request = ProviderRequest(
            messages=_text_of([item.model_dump() for item in payload.messages]),
            model=model.id,
            temperature=payload.temperature if model.supports_temperature else None,
            reasoning=_soft_reasoning(model, payload.reasoning),
            max_tokens=payload.max_tokens,
            supports_reasoning=model.supports_reasoning,
            supports_temperature=model.supports_temperature,
        )

        async def stream():
            started = time.perf_counter()
            done_sent = False
            yield _sse("start", {"model": model.id, "temperature": payload.temperature})
            try:
                async for event in active.stream(request):
                    if event.type == "done":
                        done_sent = True
                        yield _sse("done", {**event.data, "temperature": payload.temperature})
                    else:
                        yield _sse(event.type, {"text": event.text})
                if not done_sent:
                    yield _sse(
                        "done",
                        {
                            "model": model.id,
                            "elapsed_ms": int((time.perf_counter() - started) * 1000),
                            "temperature": payload.temperature,
                        },
                    )
            except ProviderError as exc:
                logger.warning("stream error (%s): %s", exc.kind, exc)
                yield _sse("error", {"message": str(exc), "kind": exc.kind})
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                logger.exception("unhandled error while streaming")
                yield _sse("error", {"message": "Внутренняя ошибка сервера.", "kind": "internal"})

        return StreamingResponse(stream(), media_type="text/event-stream")

    @app.post("/api/compare", response_model=CompareOut)
    async def compare(payload: CompareRequest) -> CompareOut:
        """Один промпт — три модели одновременно; у каждой свои токены, время и цена."""
        chosen = [_model(app, model_id) for model_id in payload.models]

        async def run_one(model: ModelInfo) -> CompareRun:
            request = ProviderRequest(
                messages=[{"role": "user", "content": payload.prompt}],
                model=model.id,
                temperature=payload.temperature if model.supports_temperature else None,
                reasoning=_soft_reasoning(model, payload.reasoning),
                max_tokens=payload.max_tokens,
                supports_reasoning=model.supports_reasoning,
                supports_temperature=model.supports_temperature,
            )
            started = time.perf_counter()
            try:
                raw, native, finish_reason, usage = await _collect(
                    provider(model.provider), request
                )
            except ProviderError as exc:
                return CompareRun(
                    model=model.id,
                    label=model.label,
                    provider=model.provider,
                    tier=model.tier,
                    error=str(exc),
                    elapsed_ms=int((time.perf_counter() - started) * 1000),
                )
            price_in, price_out, cost, note = cost_of(
                app.state.prices, model.id, model.provider, usage
            )
            return CompareRun(
                model=model.id,
                label=model.label,
                provider=model.provider,
                tier=model.tier,
                answer=raw.strip(),
                reasoning=native.strip(),
                usage=usage,
                elapsed_ms=int((time.perf_counter() - started) * 1000),
                finish_reason=finish_reason,
                truncated=finish_reason == "length",
                price_in=price_in,
                price_out=price_out,
                cost_usd=cost,
                cost_note=note,
            )

        runs = list(await asyncio.gather(*(run_one(model) for model in chosen)))
        totals = {
            "models": len(runs),
            "failed": sum(1 for run in runs if run.error),
            "truncated": sum(1 for run in runs if run.truncated),
            "prompt_tokens": sum(int((run.usage or {}).get("prompt_tokens") or 0) for run in runs),
            "completion_tokens": sum(
                int((run.usage or {}).get("completion_tokens") or 0) for run in runs
            ),
            "total_tokens": sum(_usage_total(run.usage or {}) for run in runs),
            "cost_usd": round(sum(run.cost_usd for run in runs), 6),
            # модели отвечали параллельно: общее время — самое долгое ожидание
            "elapsed_ms": max((run.elapsed_ms for run in runs), default=0),
        }
        return CompareOut(
            prompt=payload.prompt,
            task=payload.task,
            complexity=payload.complexity,
            reference=payload.reference,
            runs=runs,
            totals=totals,
        )

    @app.post("/api/benchmark", response_model=BenchmarkOut)
    async def benchmark(payload: BenchmarkRequest) -> BenchmarkOut:
        """Все задачи на всех моделях: верные ответы, время, токены, стоимость."""
        chosen = [_model(app, model_id) for model_id in payload.models]
        task_ids = payload.tasks or [task.id for task in TASKS]
        unknown = [task_id for task_id in task_ids if task_id not in TASKS_BY_ID]
        if unknown:
            raise HTTPException(status_code=400, detail=f"Неизвестная задача: {unknown[0]}")
        selected = [TASKS_BY_ID[task_id] for task_id in dict.fromkeys(task_ids)]

        async def run_one(model: ModelInfo, task) -> BenchmarkRun:
            request = ProviderRequest(
                messages=[{"role": "user", "content": task.text}],
                model=model.id,
                temperature=payload.temperature if model.supports_temperature else None,
                reasoning=_soft_reasoning(model, payload.reasoning),
                max_tokens=payload.max_tokens,
                supports_reasoning=model.supports_reasoning,
                supports_temperature=model.supports_temperature,
            )
            started = time.perf_counter()
            try:
                raw, _, finish_reason, usage = await _collect(provider(model.provider), request)
            except ProviderError as exc:
                return BenchmarkRun(
                    task=task.id,
                    task_title=task.title,
                    complexity=task.complexity,
                    reference=task.reference,
                    model=model.id,
                    label=model.label,
                    provider=model.provider,
                    tier=model.tier,
                    error=str(exc),
                    elapsed_ms=int((time.perf_counter() - started) * 1000),
                )
            answer = raw.strip()
            _, _, cost, _ = cost_of(app.state.prices, model.id, model.provider, usage)
            return BenchmarkRun(
                task=task.id,
                task_title=task.title,
                complexity=task.complexity,
                reference=task.reference,
                model=model.id,
                label=model.label,
                provider=model.provider,
                tier=model.tier,
                answer=answer,
                correct=answer_is_correct(answer, task.reference),
                elapsed_ms=int((time.perf_counter() - started) * 1000),
                usage=usage,
                finish_reason=finish_reason,
                truncated=finish_reason == "length",
                cost_usd=cost,
            )

        runs: list[BenchmarkRun] = []
        # Задачи идём по одной, модели внутри задачи — параллельно:
        # так бесплатные провайдеры не получают весь залп сразу.
        for task in selected:
            runs.extend(await asyncio.gather(*(run_one(model, task) for model in chosen)))

        judged = False
        if payload.judge:
            judge_model = _model(app, payload.judge)
            review: list[str] = []
            for task in selected:
                review.append(f"Задача {task.id} ({task.title}). Эталон: {task.reference}")
                for run in runs:
                    if run.task != task.id:
                        continue
                    answer = (run.answer or run.error or "").strip().replace("\n", " ")[:1200]
                    review.append(f"  - {run.model}: {answer or '(пусто)'}")
                review.append("")
            system = (
                "Ты — строгий проверяющий ответов. Тебе дают задачи с эталонами и ответы моделей. "
                "Проверь итоговый ответ каждой модели: верно только если итог совпадает с эталоном; "
                "рассуждения не важны, ответ с другим числом — неверный, пустой или ошибка — неверный. "
                "Верни строго JSON без текста вокруг:\n"
                '{"verdicts": [{"task": "<id>", "model": "<id>", "correct": true|false, '
                '"reason": "<до 80 символов>"}]}'
            )
            try:
                raw, _, _, _ = await _collect(
                    provider(judge_model.provider),
                    ProviderRequest(
                        messages=[
                            {"role": "system", "content": system},
                            {"role": "user", "content": "\n".join(review)},
                        ],
                        model=judge_model.id,
                        temperature=0.0 if judge_model.supports_temperature else None,
                        reasoning=_soft_reasoning(judge_model, "off"),
                        max_tokens=2_000,
                        supports_reasoning=judge_model.supports_reasoning,
                        supports_temperature=judge_model.supports_temperature,
                    ),
                )
                verdicts = _verdicts(raw)
                if verdicts:
                    for run in runs:
                        key = (run.task, run.model)
                        if key in verdicts:
                            run.correct = verdicts[key]
                    judged = True
                else:
                    logger.warning("benchmark judge returned no verdicts")
            except Exception as exc:  # noqa: BLE001 - судья не должен ломать бенчмарк
                logger.warning("benchmark judge failed: %s", exc)

        summary: list[BenchmarkModel] = []
        for model in chosen:
            own = [run for run in runs if run.model == model.id]
            correct = sum(1 for run in own if run.correct)
            total = len(own)
            elapsed = sum(run.elapsed_ms for run in own)
            summary.append(
                BenchmarkModel(
                    model=model.id,
                    label=model.label,
                    provider=model.provider,
                    tier=model.tier,
                    correct=correct,
                    total=total,
                    accuracy=round(correct / total, 4) if total else 0.0,
                    elapsed_ms=elapsed,
                    avg_elapsed_ms=int(elapsed / total) if total else 0,
                    prompt_tokens=sum(int((run.usage or {}).get("prompt_tokens") or 0) for run in own),
                    completion_tokens=sum(
                        int((run.usage or {}).get("completion_tokens") or 0) for run in own
                    ),
                    total_tokens=sum(_usage_total(run.usage or {}) for run in own),
                    cost_usd=round(sum(run.cost_usd for run in own), 6),
                    errors=sum(1 for run in own if run.error),
                )
            )

        small = next((item for item in summary if item.tier == "small"), summary[0])
        large = next((item for item in summary if item.tier == "large"), summary[-1])
        comparison = {
            "small": small.model,
            "small_label": small.label,
            "large": large.model,
            "large_label": large.label,
            "extra_correct": large.correct - small.correct,
            "accuracy_delta_pp": round((large.accuracy - small.accuracy) * 100, 1),
            "cost_delta_usd": round(large.cost_usd - small.cost_usd, 6),
            "cost_ratio": (
                round(large.cost_usd / small.cost_usd, 2) if small.cost_usd > 0 else None
            ),
            "time_ratio": (
                round(large.avg_elapsed_ms / small.avg_elapsed_ms, 2)
                if small.avg_elapsed_ms
                else None
            ),
            "both_free": small.cost_usd == 0 and large.cost_usd == 0,
        }
        totals = {
            "tasks": len(selected),
            "models": len(summary),
            "runs": len(runs),
            "errors": sum(1 for run in runs if run.error),
            "correct": sum(item.correct for item in summary),
            "total_tokens": sum(item.total_tokens for item in summary),
            "cost_usd": round(sum(item.cost_usd for item in summary), 6),
            "elapsed_ms": max((run.elapsed_ms for run in runs), default=0),
            "judged": judged,
        }
        return BenchmarkOut(
            task_ids=[task.id for task in selected],
            runs=runs,
            models=summary,
            comparison=comparison,
            totals=totals,
        )

    @app.post("/api/benchmark/analyze", response_model=BenchmarkAnalyzeOut)
    async def benchmark_analyze(payload: BenchmarkAnalyzeRequest) -> BenchmarkAnalyzeOut:
        """Вывод по бенчмарку: где маленькой модели достаточно."""
        model = _model(app, payload.model)

        lines: list[str] = []
        for item in payload.summary:
            lines.append(
                f"- {item.get('label') or item.get('model')} ({item.get('model')}, tier "
                f"{item.get('tier')}): верных {item.get('correct')} из {item.get('total')}, "
                f"точность {round(float(item.get('accuracy') or 0) * 100, 1)}%, "
                f"среднее время {item.get('avg_elapsed_ms')} мс, "
                f"токенов {item.get('total_tokens')}, стоимость ${item.get('cost_usd')}"
            )
        lines.append("")
        for task in payload.tasks:
            lines.append(
                f"Задача «{task.get('title') or task.get('task')}» "
                f"(эталон: {task.get('reference') or '—'}):"
            )
            for answer in task.get("answers") or []:
                verdict = "верно" if answer.get("correct") else "неверно"
                text = str(answer.get("answer") or "").strip().replace("\n", " ")[:350]
                lines.append(
                    f"  - {answer.get('label') or answer.get('model')}: {verdict}; "
                    f"ответ: {text or '(пусто)'}"
                )
            lines.append("")

        comparison = payload.comparison or {}
        if comparison:
            small = comparison.get("small_label") or comparison.get("small") or "маленькая"
            large = comparison.get("large_label") or comparison.get("large") or "флагман"
            ratio = comparison.get("cost_ratio")
            if ratio is None:
                cost_line = (
                    f"разница в стоимости ${comparison.get('cost_delta_usd', 0)}, "
                    "точное соотношение не определено (маленькая модель бесплатна)"
                )
            elif ratio >= 1:
                cost_line = f"флагман {large} дороже {small} в {ratio} раз"
            else:
                cost_line = f"флагман {large} дешевле {small} в {round(1 / ratio, 2)} раз"
            delta = float(comparison.get("accuracy_delta_pp", 0) or 0)
            extra = int(comparison.get("extra_correct", 0) or 0)
            if delta > 0:
                accuracy_line = f"точнее на {delta} п.п. (+{extra} задач)"
            elif delta == 0:
                accuracy_line = "точность такая же"
            else:
                accuracy_line = f"менее точна на {abs(delta)} п.п. (меньше на {abs(extra)} задач)"
            lines.append(f"Сравнение: {cost_line}, {accuracy_line}.")
            lines.append("")

        system = (
            "Ты — аналитик, который сравнивает модели на наборе задач. "
            "Тебе дают сводку по каждой модели (верные ответы, время, токены, стоимость), "
            "эталоны и ответы на каждую задачу, а также сравнение флагмана с маленькой моделью. "
            "Ответь по-русски, кратко и строго по делу:\n"
            "1) сколько задач верно решила каждая модель;\n"
            "2) скорость и ресурсоёмкость: кто быстрее, кто тратит больше токенов;\n"
            "3) во сколько раз флагман дороже маленькой модели и на сколько он точнее "
            "(в задачах и процентных пунктах);\n"
            "4) на каких задачах маленькой модели достаточно, а где без флагмана не обойтись;\n"
            "5) итоговая рекомендация одной строкой.\n"
            "Не выдумывай данных, которых нет в сводке."
        )

        started = time.perf_counter()
        raw, _, finish_reason, usage = await _collect(
            provider(model.provider),
            ProviderRequest(
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": "\n".join(lines)},
                ],
                model=model.id,
                temperature=0.2 if model.supports_temperature else None,
                reasoning=_soft_reasoning(model, "off"),
                max_tokens=payload.max_tokens,
                supports_reasoning=model.supports_reasoning,
                supports_temperature=model.supports_temperature,
            ),
        )
        return BenchmarkAnalyzeOut(
            model=model.id,
            text=raw.strip(),
            usage=usage,
            elapsed_ms=int((time.perf_counter() - started) * 1000),
            finish_reason=finish_reason,
            truncated=finish_reason == "length",
        )

    @app.post("/api/analyze", response_model=AnalyzeOut)
    async def analyze(payload: AnalyzeRequest) -> AnalyzeOut:
        """Продвинутая модель читает ответы сравниваемых моделей и делает вывод."""
        model = _model(app, payload.model)
        active = provider(model.provider)

        lines = [f"Промпт:\n{payload.prompt}", ""]
        if payload.reference:
            lines.extend([f"Эталонный ответ: {payload.reference}", ""])
        lines.append("Ответы разных моделей на этот промпт:")
        for run in payload.runs:
            name = run.get("label") or run.get("model") or "модель"
            metrics = []
            if run.get("elapsed_ms"):
                metrics.append(f"{int(run['elapsed_ms'])} мс")
            completion = (run.get("usage") or {}).get("completion_tokens")
            if completion:
                metrics.append(f"{int(completion)} токенов на ответ")
            cost = run.get("cost_usd")
            if cost:
                metrics.append(f"${float(cost):.6f}")
            suffix = f" · {', '.join(metrics)}" if metrics else ""
            lines.append(f"--- {name} ({run.get('model')}){suffix} ---")
            lines.append(str(run.get("answer") or "").strip()[:4000] or "(пустой ответ)")
            lines.append("")

        system = (
            "Ты — аналитик, который сравнивает ответы разных языковых моделей на одну задачу. "
            "Тебе дают промпт, ответы моделей и их метрики: время ответа, токены, стоимость. "
            "Ответь по-русски, кратко и по делу:\n"
            "1) какая модель ответила правильно (если дан эталон — сверь с ним), где ошибки;\n"
            "2) чем ответы различаются по сути: полнота, точность, структура, длина;\n"
            "3) соотношение цена/качество: кто быстрее, кто экономнее, стоит ли переплачивать "
            "за большую модель на этой задаче;\n"
            "4) для каких задач какую из этих моделей брать;\n"
            "5) итоговая рекомендация одной строкой.\n"
            "Не пересказывай ответы целиком и не выдумывай того, чего в них нет."
        )

        started = time.perf_counter()
        raw, _, finish_reason, usage = await _collect(
            active,
            ProviderRequest(
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": "\n".join(lines)},
                ],
                model=model.id,
                temperature=0.2 if model.supports_temperature else None,
                reasoning=_soft_reasoning(model, "off"),
                max_tokens=payload.max_tokens,
                supports_reasoning=model.supports_reasoning,
                supports_temperature=model.supports_temperature,
            ),
        )
        return AnalyzeOut(
            model=model.id,
            text=raw.strip(),
            usage=usage,
            elapsed_ms=int((time.perf_counter() - started) * 1000),
            finish_reason=finish_reason,
            truncated=finish_reason == "length",
        )

    return app


app = create_app()
