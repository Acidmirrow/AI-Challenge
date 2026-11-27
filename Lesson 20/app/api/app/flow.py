"""Длинный детерминированный флоу урока 20 через несколько MCP-серверов."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

from .hub import MCPHub


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _step(
    index: int,
    server: str,
    tool: str,
    arguments: dict[str, Any],
    result: dict[str, Any],
    elapsed_ms: int,
) -> dict[str, Any]:
    return {
        "index": index,
        "server": server,
        "tool": tool,
        "status": "ok" if result.get("ok") else "error",
        "arguments": arguments,
        "result": result,
        "elapsed_ms": elapsed_ms,
    }


async def run_flow(
    customer_id: str = "C-104",
    amount_rub: int = 100_000,
    disabled_servers: list[str] | None = None,
) -> dict[str, Any]:
    """Выполнить флоу: клиент → прогноз → два статуса → время."""
    customer_id = customer_id.strip().upper()
    steps: list[dict[str, Any]] = []
    async with MCPHub(disabled_servers) as hub:
        inspect = hub.inspect()

        async def invoke(
            server: str,
            original: str,
            arguments: dict[str, Any],
        ) -> dict[str, Any] | None:
            index = len(steps) + 1
            started = time.perf_counter()
            try:
                exposed = hub.route_name(server, original)
            except KeyError:
                result = {
                    "ok": False,
                    "error": f"Сервер {server} недоступен: инструмент {original} не зарегистрирован",
                }
                steps.append(
                    _step(index, server, original, arguments, result, 0)
                )
                return result
            result = await hub.call(exposed, arguments)
            steps.append(
                _step(
                    index,
                    server,
                    exposed,
                    arguments,
                    result,
                    int((time.perf_counter() - started) * 1000),
                )
            )
            if not result.get("ok"):
                return result
            return result

        customer = await invoke("orders", "get_customer", {"customer_id": customer_id})
        if not customer or not customer.get("ok"):
            return _stopped(inspect, hub, steps, "orders", "get_customer")

        forecast = await invoke(
            "analytics",
            "forecast",
            {"customer_id": customer_id, "amount_rub": amount_rub},
        )
        if not forecast or not forecast.get("ok"):
            return _stopped(inspect, hub, steps, "analytics", "forecast")

        analytics_status = await invoke("analytics", "get_status", {})
        if not analytics_status or not analytics_status.get("ok"):
            return _stopped(inspect, hub, steps, "analytics", "get_status")

        orders_status = await invoke("orders", "get_status", {})
        if not orders_status or not orders_status.get("ok"):
            return _stopped(inspect, hub, steps, "orders", "get_status")

        current_time = await invoke(
            "time", "get_current_time", {"timezone": "Europe/Moscow"}
        )
        if not current_time or not current_time.get("ok"):
            return _stopped(inspect, hub, steps, "time", "get_current_time")

        return {
            "ok": True,
            "status": "done",
            "flow_id": f"flow-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}",
            "message": "Длинный флоу выполнен: данные получены с трёх серверов.",
            "steps": steps,
            "servers": hub.inspect()["servers"],
            "failures": hub.failures,
            "customer": customer.get("customer"),
            "forecast": forecast,
            "analytics_status": analytics_status,
            "orders_status": orders_status,
            "current_time": current_time,
            "finished_at": _now(),
        }


def _stopped(
    inspect: dict[str, Any],
    hub: MCPHub,
    steps: list[dict[str, Any]],
    server: str,
    tool: str,
) -> dict[str, Any]:
    failed = steps[-1] if steps else {}
    return {
        "ok": False,
        "status": "stopped",
        "message": (
            f"Флоу остановлен на {len(steps)}-м шаге ({server}/{tool}); "
            "следующие серверы не вызывались."
        ),
        "stopped_at": tool,
        "stopped_server": server,
        "stopped_step": len(steps),
        "reason": (failed.get("result") or {}).get("error") or "шаг завершился ошибкой",
        "steps": steps,
        "servers": hub.inspect()["servers"],
        "failures": hub.failures,
        "customer": None,
        "forecast": None,
        "output": None,
        "finished_at": _now(),
    }
