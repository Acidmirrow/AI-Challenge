"""Тесты урока 18: MCP-инструменты, накопление и отчёт по всем запускам."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import app
from app.scheduler import Scheduler

client = TestClient(app)


def _payload(result: dict) -> dict:
    assert result.get("text")
    return json.loads(result["text"])


def _call(tool: str, arguments: dict | None = None) -> dict:
    response = client.post(
        "/api/mcp/call", json={"tool": tool, "arguments": arguments or {}}
    )
    assert response.status_code == 200
    return _payload(response.json())


def test_health_reports_scheduler_and_three_tools() -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["lesson"] == 18
    assert payload["topic"] == "Планировщик и фоновые задачи"
    assert payload["tools"] == 3
    assert payload["scheduler_enabled"] is False


def test_mcp_registers_three_scheduler_tools() -> None:
    response = client.post("/api/mcp/inspect")
    assert response.status_code == 200
    payload = response.json()
    assert payload["server"]["name"] == "lesson18-scheduler"
    assert payload["tool_count"] == 3
    tools = {tool["name"]: tool for tool in payload["tools"]}
    assert set(tools) == {"fetch_metrics", "save_snapshot", "read_snapshots"}
    assert tools["save_snapshot"]["input_schema"]["required"] == ["snapshot"]
    assert "since" in tools["read_snapshots"]["input_schema"]["properties"]


def test_mcp_fetch_save_and_read_accumulated_snapshots() -> None:
    first = _call("fetch_metrics", {"source": "test"})
    second = _call("fetch_metrics", {"source": "test"})
    assert first["ok"] is True
    assert second["ok"] is True
    assert first["snapshot"]["run_id"] != second["snapshot"]["run_id"]

    saved_first = _call("save_snapshot", {"snapshot": first["snapshot"]})
    saved_second = _call("save_snapshot", {"snapshot": second["snapshot"]})
    assert saved_first["ok"] is True
    assert saved_second["total"] == 2

    read = _call("read_snapshots", {"limit": 10})
    assert read["ok"] is True
    assert read["count"] == 2
    assert read["total"] == 2
    assert {item["run_id"] for item in read["snapshots"]} == {
        first["snapshot"]["run_id"],
        second["snapshot"]["run_id"],
    }


def test_scheduler_accumulates_runs_and_report_uses_all_of_them() -> None:
    for _ in range(3):
        response = client.post("/api/scheduler/run")
        assert response.status_code == 200
        assert response.json()["ok"] is True

    response = client.get("/api/snapshots", params={"limit": 10})
    snapshots_payload = response.json()
    assert snapshots_payload["count"] == 3
    snapshots = snapshots_payload["snapshots"]
    expected_requests = sum(int(item["requests"]) for item in snapshots)

    response = client.post("/api/scheduler/report")
    assert response.status_code == 200
    report = response.json()["report"]
    assert report["runs"] == 3
    assert report["snapshot_ids"] == [item["id"] for item in snapshots]
    assert report["requests_total"] == expected_requests
    assert report["errors_total"] == sum(int(item["errors"]) for item in snapshots)
    assert len(report["series"]) == 3
    assert report["series"][-1]["collected_at"] == snapshots[-1]["collected_at"]


def test_scheduler_report_can_be_read_from_api() -> None:
    client.post("/api/scheduler/run")
    client.post("/api/scheduler/run")
    report_response = client.post("/api/scheduler/report")
    assert report_response.status_code == 200

    latest = client.get("/api/reports/latest")
    assert latest.status_code == 200
    assert latest.json()["report"]["runs"] == 2

    history = client.get("/api/reports")
    assert history.status_code == 200
    assert history.json()["count"] >= 1


def test_background_scheduler_runs_without_manual_calls() -> None:
    settings = Settings(
        scheduler_enabled=True,
        scheduler_snapshot_interval_s=0.05,
        scheduler_report_interval_s=0.1,
        scheduler_startup_delay_s=0.01,
        scheduler_report_window_minutes=60,
    )

    async def scenario() -> dict:
        scheduler = Scheduler(settings)
        await scheduler.start()
        await asyncio.sleep(8.0)
        await scheduler.stop()
        return scheduler.status()

    status = asyncio.run(scenario())
    assert status["runs_this_process"] >= 2
    assert status["snapshots_total"] >= 2
    assert status["reports_total"] >= 1
    assert status["last_error"] is None
    assert status["running"] is False


def test_report_reads_snapshots_inside_period() -> None:
    # Добавляем снимок через MCP, затем проверяем фильтр периода в read_snapshots.
    fetched = _call("fetch_metrics")
    saved = _call("save_snapshot", {"snapshot": fetched["snapshot"]})["snapshot"]
    collected = datetime.fromisoformat(saved["collected_at"])
    since = (collected - timedelta(seconds=1)).isoformat()
    until = (collected + timedelta(seconds=1)).isoformat()
    read = _call("read_snapshots", {"since": since, "until": until})
    assert read["count"] == 1
    assert read["snapshots"][0]["run_id"] == saved["run_id"]


def test_snapshot_limit_evicts_earliest_record() -> None:
    from app import storage

    for index in range(501):
        storage.save_snapshot(
            {
                "run_id": f"limit-{index}",
                "collected_at": f"2026-11-25T00:00:{index % 60:02d}+00:00",
                "source": "limit-test",
                "cpu_pct": index % 100,
                "requests": index,
                "errors": 0,
                "latency_ms": index,
                "queue_depth": 0,
            }
        )

    result = storage.read_snapshots(limit=1000)
    assert result["total"] == 500
    assert result["count"] == 500
    assert "limit-0" not in {item["run_id"] for item in result["snapshots"]}
    assert "limit-500" in {item["run_id"] for item in result["snapshots"]}


def test_clear_removes_snapshots_and_reports() -> None:
    client.post("/api/scheduler/run")
    client.post("/api/scheduler/report")
    assert client.get("/api/snapshots").json()["total"] >= 1

    response = client.post("/api/scheduler/clear")
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["snapshots_deleted"] >= 1
    assert payload["reports_deleted"] >= 1
    assert client.get("/api/snapshots").json()["total"] == 0
    assert client.get("/api/reports/latest").json()["report"] is None
    assert client.get("/api/reports").json()["count"] == 0
