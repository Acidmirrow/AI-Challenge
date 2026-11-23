"""API урока 16: чат с моделью и MCP-инструментами."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .agent import AgentConfig
from .agent_tools import DEFAULT_REGISTRY
from .config import get_settings
from .mcp_agent import MCPChat
from .mcp_client import (
    YOUGILE_URL,
    MCPError,
    call_http_tool,
    call_tool,
    inspect_http,
    inspect_server,
)
from .models_catalog import ModelInfo, build_catalog
from .providers import Provider, ProviderError, build_provider

settings = get_settings()
catalog = build_catalog(settings)
app = FastAPI(title="AI Challenge · Lesson 16 MCP chat", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[item.strip() for item in settings.cors_origins.split(",") if item.strip()] or ["*"],
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


class ToolCallRequest(BaseModel):
    tool: str = Field(min_length=1, max_length=120)
    arguments: dict[str, Any] = Field(default_factory=dict)


class ExternalRequest(BaseModel):
    url: str = Field(default=YOUGILE_URL, min_length=8, max_length=500)


class ExternalCallRequest(ExternalRequest):
    tool: str = Field(min_length=1, max_length=120)
    arguments: dict[str, Any] = Field(default_factory=dict)


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=8_000)


class ChatRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=8_000)
    model: str = Field(min_length=1, max_length=128)
    history: list[ChatMessage] = Field(default_factory=list, max_length=40)
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    reasoning: str = Field(default="off", max_length=16)
    max_tokens: int | None = Field(default=1_500, ge=16, le=10_000)
    max_steps: int = Field(default=6, ge=1, le=10)


@app.get("/api/health")
async def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "lesson": 16,
        "provider": settings.provider_label,
        "mcp_transport": "stdio",
        "tools": len(DEFAULT_REGISTRY),
    }


@app.get("/api/models")
async def models() -> list[dict[str, Any]]:
    return [model.as_dict() for model in catalog.all()]


@app.get("/api/tools")
async def tools() -> list[dict[str, Any]]:
    return DEFAULT_REGISTRY.catalog()


@app.post("/api/mcp/inspect")
async def inspect() -> dict[str, Any]:
    try:
        return await inspect_server()
    except MCPError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/api/mcp/call")
async def call(payload: ToolCallRequest) -> dict[str, Any]:
    try:
        return await call_tool(payload.tool, payload.arguments)
    except MCPError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/mcp/external/inspect")
async def external_inspect(payload: ExternalRequest) -> dict[str, Any]:
    try:
        return await inspect_http(payload.url)
    except MCPError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/api/mcp/external/call")
async def external_call(payload: ExternalCallRequest) -> dict[str, Any]:
    try:
        return await call_http_tool(payload.tool, payload.arguments, payload.url)
    except MCPError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/chat")
async def chat(payload: ChatRequest) -> dict[str, Any]:
    model = _model(payload.model)
    agent = MCPChat(
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
    )
    try:
        result = await agent.run(payload.prompt)
    except ProviderError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
    except MCPError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    result["model"] = model.id
    result["label"] = model.label
    result["provider"] = model.provider
    return result


@app.exception_handler(ProviderError)
async def provider_error(_, exc: ProviderError) -> JSONResponse:
    return JSONResponse(status_code=exc.status, content={"detail": str(exc), "kind": exc.kind})
