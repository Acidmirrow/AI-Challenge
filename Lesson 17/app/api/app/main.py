"""API урока 17: mock CRM API, MCP-инструмент и агентский чат."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from datetime import date

from .agent import AgentConfig
from .config import get_settings
from .mcp_agent import MCPChat
from .mcp_client import MCPError, call_tool, inspect_server
from .models_catalog import ModelInfo, build_catalog
from .providers import Provider, ProviderError, build_provider

settings = get_settings()
catalog = build_catalog(settings)
app = FastAPI(title="AI Challenge · Lesson 17 MCP tool", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[item.strip() for item in settings.cors_origins.split(",") if item.strip()] or ["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

CUSTOMERS: dict[str, dict[str, Any]] = {
    "C-104": {
        "id": "C-104",
        "name": "ООО «Ромашка»",
        "email": "ops@romashka.example",
        "plan": "Pro",
        "balance_rub": 128000,
        "open_tickets": 2,
        "manager": "Анна Смирнова",
        "since": "2024-03-12",
    },
    "C-207": {
        "id": "C-207",
        "name": "ИП Волков",
        "email": "volkov@example.ru",
        "plan": "Start",
        "balance_rub": 0,
        "open_tickets": 5,
        "manager": "Илья Петров",
        "since": "2025-11-02",
    },
    "C-318": {
        "id": "C-318",
        "name": "ООО «Северный ветер»",
        "email": "office@northwind.example",
        "plan": "Enterprise",
        "balance_rub": 540000,
        "open_tickets": 1,
        "manager": "Ольга Ким",
        "since": "2023-07-19",
    },
    "C-422": {
        "id": "C-422",
        "name": "Мария Лебедева",
        "email": "m.lebedeva@example.ru",
        "plan": "Pro",
        "balance_rub": 12400,
        "open_tickets": 3,
        "manager": "Дмитрий Соколов",
        "since": "2025-01-27",
    },
    "C-509": {
        "id": "C-509",
        "name": "ООО «Кибер-Логистика»",
        "email": "ops@cyberlog.example",
        "plan": "Enterprise",
        "balance_rub": 0,
        "open_tickets": 8,
        "manager": "Наталья Орлова",
        "since": "2022-11-08",
    },
}

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
    max_steps: int = Field(default=4, ge=1, le=6)


class ToolCallRequest(BaseModel):
    tool: str = Field(min_length=1, max_length=120)
    arguments: dict[str, Any] = Field(default_factory=dict)


class CustomerCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: str = Field(min_length=3, max_length=160)
    plan: Literal["Start", "Pro", "Enterprise"]
    balance_rub: int = Field(default=0, ge=0)
    open_tickets: int = Field(default=0, ge=0)
    manager: str = Field(default="", max_length=120)


@app.get("/api/health")
async def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "lesson": 17,
        "topic": "Первый инструмент MCP",
        "provider": settings.provider_label,
        "tools": 4,
    }


@app.get("/api/lesson")
async def lesson() -> dict[str, Any]:
    return {
        "lesson": 17,
        "title": "Первый инструмент MCP",
        "implemented": True,
        "tool": "get_customer",
        "tools": ["get_customer", "list_customers", "create_customer", "delete_customer"],
    }


@app.get("/api/models")
async def models() -> list[dict[str, Any]]:
    return [model.as_dict() for model in catalog.all()]


@app.get("/mock/customers/{customer_id}")
async def mock_customer(customer_id: str) -> dict[str, Any]:
    """Учебный HTTP API, вокруг которого построен MCP-сервер."""

    customer = CUSTOMERS.get(customer_id.upper())
    if customer is None:
        raise HTTPException(status_code=404, detail="Клиент не найден")
    return customer


@app.get("/mock/customers")
async def mock_customers() -> list[dict[str, Any]]:
    return list(CUSTOMERS.values())


@app.post("/mock/customers", status_code=201)
async def mock_create_customer(payload: CustomerCreate) -> dict[str, Any]:
    """Добавляет клиента в mock CRM; идентификатор выдаётся автоматически."""

    numbers = [
        int(customer_id.split("-", 1)[1])
        for customer_id in CUSTOMERS
        if customer_id.startswith("C-") and customer_id.split("-", 1)[1].isdigit()
    ]
    customer_id = f"C-{max(numbers, default=100) + 1}"
    customer = {
        "id": customer_id,
        "name": payload.name.strip(),
        "email": payload.email.strip(),
        "plan": payload.plan,
        "balance_rub": payload.balance_rub,
        "open_tickets": payload.open_tickets,
        "manager": payload.manager.strip(),
        "since": date.today().isoformat(),
    }
    CUSTOMERS[customer_id] = customer
    return customer


@app.delete("/mock/customers/{customer_id}")
async def mock_delete_customer(customer_id: str) -> dict[str, Any]:
    customer = CUSTOMERS.pop(customer_id.upper(), None)
    if customer is None:
        raise HTTPException(status_code=404, detail="Клиент не найден")
    return customer


@app.post("/api/mcp/inspect")
async def mcp_inspect() -> dict[str, Any]:
    try:
        return await inspect_server()
    except MCPError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/api/mcp/call")
async def mcp_call(payload: ToolCallRequest) -> dict[str, Any]:
    try:
        return await call_tool(payload.tool, payload.arguments)
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
