"""Тесты урока 20: мультисерверный хаб, коллизии имён и отказ сервера."""

from __future__ import annotations

import asyncio

from app.flow import run_flow
from app.hub import MCPHub


def test_hub_connects_three_servers_and_resolves_duplicate_names() -> None:
    async def scenario():
        async with MCPHub() as hub:
            return hub.inspect(), await hub.call("orders__get_status"), await hub.call(
                "analytics__get_status"
            )

    inspect, orders_status, analytics_status = asyncio.run(scenario())
    assert inspect["tool_count"] >= 7
    servers = {item["name"]: item for item in inspect["servers"]}
    assert set(servers) == {"orders", "analytics", "time"}
    assert all(item["connected"] for item in servers.values())
    assert "get_customer" in {tool["name"] for tool in inspect["tools"]}
    assert "get_current_time" in {tool["name"] for tool in inspect["tools"]}
    assert "orders__get_status" in {tool["name"] for tool in inspect["tools"]}
    assert "analytics__get_status" in {tool["name"] for tool in inspect["tools"]}
    assert orders_status["server"] == "orders"
    assert orders_status["original"] == "get_status"
    assert analytics_status["server"] == "analytics"
    assert analytics_status["original"] == "get_status"


def test_long_flow_uses_tools_from_all_servers_in_order() -> None:
    result = asyncio.run(run_flow("C-104", 100_000))
    assert result["ok"] is True
    assert result["status"] == "done"
    assert [step["server"] for step in result["steps"]] == [
        "orders",
        "analytics",
        "analytics",
        "orders",
        "time",
    ]
    assert [step["tool"] for step in result["steps"]] == [
        "get_customer",
        "forecast",
        "analytics__get_status",
        "orders__get_status",
        "get_current_time",
    ]
    assert all(step["status"] == "ok" for step in result["steps"])
    assert result["customer"]["name"] == "ООО «Ромашка»"
    assert result["forecast"]["server"] == "analytics"
    assert result["current_time"]["server"] == "time"


def test_disabled_time_server_still_leaves_other_servers_working() -> None:
    result = asyncio.run(run_flow("C-104", 100_000, ["time"]))
    assert result["ok"] is False
    assert result["status"] == "stopped"
    assert result["stopped_server"] == "time"
    assert result["stopped_at"] == "get_current_time"
    assert result["stopped_step"] == 5
    assert [step["status"] for step in result["steps"]] == [
        "ok",
        "ok",
        "ok",
        "ok",
        "error",
    ]
    assert result["output"] is None
    servers = {item["name"]: item for item in result["servers"]}
    assert servers["orders"]["connected"] is True
    assert servers["analytics"]["connected"] is True
    assert servers["time"]["connected"] is False
    assert "time" in result["failures"]
