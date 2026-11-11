"""Единая точка входа в API всех уроков.

Один хост и один порт для всего курса: `/lesson-01/api/...` уходит в API урока 01,
`/lesson-02/api/...` — в API урока 02 и так далее. Код каждого урока при этом живёт
в своей папке (`Lesson 0X/app/api`) и не смешивается с остальными — шлюз только
проксирует запросы, включая потоковые (SSE) ответы чата.
"""

from __future__ import annotations

import logging
import os

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("ai-challenge.gateway")


def _upstreams() -> dict[str, str]:
    """Адреса API уроков внутри compose-сети."""
    default = {
        "lesson-01": "http://lesson-01-api:8000",
        "lesson-02": "http://lesson-02-api:8000",
        "lesson-03": "http://lesson-03-api:8000",
        "lesson-04": "http://lesson-04-api:8000",
        "lesson-05": "http://lesson-05-api:8000",
        "lesson-06": "http://lesson-06-api:8000",
        "lesson-07": "http://lesson-07-api:8000",
        "lesson-08": "http://lesson-08-api:8000",
    }
    for lesson, value in default.items():
        override = os.getenv(f"{lesson.upper().replace('-', '_')}_URL", "")
        if override:
            default[lesson] = override.rstrip("/")
    return default


UPSTREAMS = _upstreams()

TITLES = {
    "lesson-01": "Урок 01 — чат с моделью",
    "lesson-02": "Урок 02 — форматы ответа",
    "lesson-03": "Урок 03 — способы рассуждений",
    "lesson-04": "Урок 04 — температура",
    "lesson-05": "Урок 05 — сравнение моделей",
    "lesson-06": "Урок 06 — ИИ-агент",
    "lesson-07": "Урок 07 — сохранение контекста",
    "lesson-08": "Урок 08 — работа с токенами",
}

#: заголовки, которые нельзя пробрасывать как есть
HOP_BY_HOP = {
    "connection",
    "keep-alive",
    "transfer-encoding",
    "upgrade",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "host",
    "content-length",
}

app = FastAPI(title="AI Challenge Gateway", version="1.0.0")


@app.get("/api/lessons")
async def lessons() -> list[dict]:
    """Список уроков и адресов, чтобы UI и curl видели одну картину."""
    return [
        {"id": lesson, "title": TITLES.get(lesson, lesson), "base": f"/{lesson}/api"}
        for lesson in UPSTREAMS
    ]


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "lessons": list(UPSTREAMS)}


@app.api_route(
    "/{lesson}/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
)
async def proxy(lesson: str, path: str, request: Request):
    """Проксировать запрос в API нужного урока, сохраняя стриминг ответа."""
    base = UPSTREAMS.get(lesson)
    if base is None:
        return JSONResponse({"detail": f"Неизвестный урок: {lesson}"}, status_code=404)

    url = f"{base}/{path}"
    headers = {
        key: value
        for key, value in request.headers.items()
        if key.lower() not in HOP_BY_HOP
    }
    body = await request.body()
    client = httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=10.0))

    try:
        upstream = client.build_request(
            request.method,
            url,
            params=request.query_params,
            headers=headers,
            content=body,
        )
        response = await client.send(upstream, stream=True)
    except httpx.HTTPError as exc:
        await client.aclose()
        logger.warning("upstream %s недоступен: %s", url, exc)
        return JSONResponse(
            {"detail": f"API урока {lesson} недоступен: {exc}", "kind": "gateway"},
            status_code=502,
        )

    passthrough = {
        key: value
        for key, value in response.headers.items()
        if key.lower() not in HOP_BY_HOP
    }
    media_type = response.headers.get("content-type", "").split(";")[0].strip()

    if media_type == "text/event-stream":
        async def relay():
            try:
                async for chunk in response.aiter_raw():
                    yield chunk
            finally:
                await response.aclose()
                await client.aclose()

        return StreamingResponse(
            relay(),
            status_code=response.status_code,
            headers={**passthrough, "cache-control": "no-cache"},
            media_type="text/event-stream",
        )

    try:
        content = await response.aread()
    finally:
        await response.aclose()
        await client.aclose()

    return Response(
        content=content,
        status_code=response.status_code,
        headers=passthrough,
        media_type=media_type or None,
    )
