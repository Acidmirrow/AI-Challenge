"""API урока 19: автоматический пайплайн из MCP-инструментов."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .mcp_client import MCPError, call_tool, inspect_server
from .pipeline import SCENARIOS, Pipeline, PipelineError

app = FastAPI(title="AI Challenge · Lesson 19 MCP pipeline", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

pipeline = Pipeline()


class PipelineRequest(BaseModel):
    query: str = Field(default="MCP инструменты", min_length=1, max_length=500)
    scenario: Literal[
        "none", "empty_search", "summarize_error", "save_error"
    ] = "none"


class ToolCallRequest(BaseModel):
    tool: str = Field(min_length=1, max_length=120)
    arguments: dict[str, Any] = Field(default_factory=dict)


@app.get("/api/health")
async def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "lesson": 19,
        "topic": "Композиция MCP инструментов",
        "tools": 3,
        "pipeline": ["search", "summarize", "saveToFile"],
    }


@app.get("/api/lesson")
async def lesson() -> dict[str, Any]:
    return {
        "lesson": 19,
        "title": "Композиция MCP инструментов",
        "implemented": True,
        "pipeline": ["search", "summarize", "saveToFile"],
        "scenarios": SCENARIOS,
    }


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


@app.post("/api/pipeline/run")
async def pipeline_run(payload: PipelineRequest) -> dict[str, Any]:
    try:
        return await pipeline.run(payload.query, payload.scenario)
    except MCPError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except PipelineError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/api/pipeline/scenarios")
async def pipeline_scenarios() -> dict[str, Any]:
    return {"ok": True, "scenarios": SCENARIOS}
