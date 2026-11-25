"""API урока 18: планировщик, SQLite-накопление и агрегированные отчёты."""

from __future__ import annotations

from contextlib import asynccontextmanager
import sqlite3
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from . import storage
from .config import get_settings
from .mcp_client import MCPError, call_tool, inspect_server
from .scheduler import Scheduler, SchedulerError

settings = get_settings()
scheduler = Scheduler(settings)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await scheduler.start()
    try:
        yield
    finally:
        await scheduler.stop()


app = FastAPI(
    title="AI Challenge · Lesson 18 scheduler",
    version="1.0.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[item.strip() for item in settings.cors_origins.split(",") if item.strip()]
    or ["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class ToolCallRequest(BaseModel):
    tool: str = Field(min_length=1, max_length=120)
    arguments: dict[str, Any] = Field(default_factory=dict)


@app.get("/api/health")
async def health() -> dict[str, Any]:
    state = scheduler.status()
    return {
        "status": "ok",
        "lesson": 18,
        "topic": "Планировщик и фоновые задачи",
        "tools": 3,
        "scheduler_enabled": state["enabled"],
        "scheduler_running": state["running"],
        "snapshots_total": state["snapshots_total"],
        "reports_total": state["reports_total"],
        "snapshot_limit": state["snapshot_limit"],
    }


@app.get("/api/lesson")
async def lesson() -> dict[str, Any]:
    return {
        "lesson": 18,
        "title": "Планировщик и фоновые задачи",
        "implemented": True,
        "tools": ["fetch_metrics", "save_snapshot", "read_snapshots"],
        "snapshot_interval_s": settings.snapshot_interval,
        "report_interval_s": settings.report_interval,
        "report_window_minutes": settings.scheduler_report_window_minutes,
        "snapshot_limit": storage.MAX_SNAPSHOTS,
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


@app.get("/api/scheduler/status")
async def scheduler_status() -> dict[str, Any]:
    return scheduler.status()


@app.post("/api/scheduler/run")
async def scheduler_run() -> dict[str, Any]:
    try:
        snapshot = await scheduler.run_once()
    except (MCPError, SchedulerError, RuntimeError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"ok": True, "snapshot": snapshot, "scheduler": scheduler.status()}


@app.post("/api/scheduler/report")
async def scheduler_report() -> dict[str, Any]:
    try:
        report = await scheduler.build_report()
    except (MCPError, SchedulerError, RuntimeError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"ok": True, "report": report, "scheduler": scheduler.status()}


@app.post("/api/scheduler/clear")
async def scheduler_clear() -> dict[str, Any]:
    try:
        deleted = await scheduler.clear_results()
    except (RuntimeError, sqlite3.Error) as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"ok": True, **deleted, "scheduler": scheduler.status()}


@app.get("/api/snapshots")
async def snapshots(
    since: str | None = None,
    until: str | None = None,
    limit: int = Query(default=50, ge=1, le=5000),
) -> dict[str, Any]:
    try:
        return {"ok": True, **storage.read_snapshots(since=since, until=until, limit=limit)}
    except (OSError, RuntimeError, ValueError, sqlite3.Error) as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/reports")
async def reports(limit: int = Query(default=20, ge=1, le=100)) -> dict[str, Any]:
    try:
        items = storage.list_reports(limit)
    except sqlite3.Error as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"ok": True, "count": len(items), "reports": items}


@app.get("/api/reports/latest")
async def latest_report() -> dict[str, Any]:
    try:
        report = storage.latest_report()
    except sqlite3.Error as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"ok": True, "report": report}
