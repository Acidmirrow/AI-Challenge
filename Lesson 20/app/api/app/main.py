"""API урока 20: оркестрация нескольких MCP-серверов."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .agent import AgentConfig
from .config import get_settings
from .flow import run_flow
from .hub import MCPHub
from .mcp_agent import MultiMCPChat
from .models_catalog import ModelInfo, build_catalog
from .providers import Provider, ProviderError, build_provider

settings = get_settings()
catalog = build_catalog(settings)
app = FastAPI(title="AI Challenge · Lesson 20 MCP orchestration", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[item.strip() for item in settings.cors_origins.split(",") if item.strip()]
    or ["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_holder: dict[str, Provider] = {}


def _provider(name: str) -> Provider:
    if name not in _holder:
        _holder[name] = build_provider(settings, name)
    return _holder[name]


def _model(model_id: str) -> ModelInfo:
    model = catalog.get(model_id)
    if model is None:
        raise HTTPException(status_code=400, detail=f"Неизвестная модель: {model_id}")
    return model


def _soft_reasoning(model: ModelInfo, wanted: str) -> str:
    levels = list(model.reasoning_levels or ())
    if not levels:
        return "off"
    if wanted in levels:
        return wanted
    return "none" if "none" in levels else levels[0]


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=8_000)


class ChatRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=8_000)
    model: str = Field(min_length=1, max_length=128)
    history: list[ChatMessage] = Field(default_factory=list, max_length=40)
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    reasoning: str = Field(default="off", max_length=16)
    max_tokens: int | None = Field(default=1_200, ge=16, le=10_000)
    max_steps: int = Field(default=6, ge=1, le=10)
    disabled_servers: list[Literal["orders", "analytics", "time"]] = Field(default_factory=list)


class FlowRequest(BaseModel):
    customer_id: str = Field(default="C-104", min_length=1, max_length=32)
    amount_rub: int = Field(default=100_000, ge=1, le=100_000_000)
    disabled_servers: list[Literal["orders", "analytics", "time"]] = Field(default_factory=list)


class HubRequest(BaseModel):
    disabled_servers: list[Literal["orders", "analytics", "time"]] = Field(default_factory=list)


@app.get("/api/health")
async def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "lesson": 20,
        "topic": "Оркестрация MCP",
        "servers": 3,
        "external": "time",
    }


@app.get("/api/lesson")
async def lesson() -> dict[str, Any]:
    return {
        "lesson": 20,
        "title": "Оркестрация MCP",
        "implemented": True,
        "servers": ["orders", "analytics", "time"],
        "external_server": "time",
    }


@app.get("/api/models")
async def models() -> list[dict[str, Any]]:
    return [model.as_dict() for model in catalog.all()]


@app.post("/api/mcp/inspect")
async def mcp_inspect(payload: HubRequest | None = None) -> dict[str, Any]:
    disabled = list(payload.disabled_servers) if payload else []
    async with MCPHub(disabled) as hub:
        return hub.inspect()


@app.post("/api/flow/run")
async def flow_run(payload: FlowRequest) -> dict[str, Any]:
    try:
        return await run_flow(
            payload.customer_id,
            payload.amount_rub,
            payload.disabled_servers,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Ошибка оркестрации: {exc}") from exc


@app.post("/api/chat")
async def chat(payload: ChatRequest) -> dict[str, Any]:
    model = _model(payload.model)
    agent = MultiMCPChat(
        _provider(model.provider),
        AgentConfig(
            model=model.id,
            temperature=payload.temperature,
            reasoning=_soft_reasoning(model, payload.reasoning),
            max_tokens=payload.max_tokens,
            max_steps=payload.max_steps,
            supports_reasoning=model.supports_reasoning,
            supports_temperature=model.supports_temperature,
        ),
        [item.model_dump() for item in payload.history],
        payload.disabled_servers,
    )
    try:
        result = await agent.run(payload.prompt)
    except ProviderError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    result["model"] = model.id
    result["label"] = model.label
    result["provider"] = model.provider
    return result


@app.exception_handler(ProviderError)
async def provider_error(_, exc: ProviderError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status,
        content={"detail": str(exc), "kind": exc.kind},
    )
