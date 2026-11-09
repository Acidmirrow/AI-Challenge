"""Тесты инструментов агента: вычисления, даты, единицы, числа, хеши, валюты."""

from __future__ import annotations

import pytest

from app.agent_tools import TOOL_SCHEMAS, execute_tool, tool_catalog


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("2 + 2", 4),
        ("(4850 * 17) / 100", 824.5),
        ("2 ** 10", 1024),
        ("round(2.6)", 3),
        ("max(2, 7, 5) - min(1, 4)", 6),
        ("17 // 5", 3),
        ("17 % 5", 2),
    ],
)
def test_calculator_counts(expression: str, expected: float) -> None:
    result = execute_tool("calculator", {"expression": expression})
    assert result["ok"] is True
    assert result["result"]["value"] == expected


def test_calculator_rejects_division_by_zero() -> None:
    result = execute_tool("calculator", {"expression": "1 / 0"})
    assert result["ok"] is False
    assert "ноль" in result["error"].lower()


def test_calculator_rejects_names_and_huge_powers() -> None:
    assert execute_tool("calculator", {"expression": "__import__('os')"})["ok"] is False
    assert execute_tool("calculator", {"expression": "2 ** 99"})["ok"] is False


def test_text_stats() -> None:
    result = execute_tool("text_stats", {"text": "Привет мир! Как дела?"})
    assert result["ok"] is True
    stats = result["result"]
    assert stats["words"] == 4
    assert stats["sentences"] == 2
    assert stats["chars"] == 21
    assert stats["chars_no_spaces"] == 18


def test_currency_rates_converts_through_base(monkeypatch) -> None:
    from app import agent_tools

    agent_tools._rates_cache.clear()
    monkeypatch.setattr(
        agent_tools,
        "_fetch_rates",
        lambda base: {
            "result": "success",
            "time_last_update_utc": "Mon, 09 Nov 2026 00:00:00 +0000",
            "rates": {"USD": 1.0, "RUB": 80.0, "EUR": 0.9, "CNY": 7.0, "GBP": 0.8},
        },
    )
    result = execute_tool("currency_rates", {"base": "USD", "targets": ["RUB", "EUR"]})
    assert result["ok"] is True
    assert result["result"]["base"] == "USD"
    assert result["result"]["rates"] == {"RUB": 80.0, "EUR": 0.9}
    agent_tools._rates_cache.clear()


def test_currency_rates_rejects_bad_codes(monkeypatch) -> None:
    from app import agent_tools

    agent_tools._rates_cache.clear()
    monkeypatch.setattr(
        agent_tools,
        "_fetch_rates",
        lambda base: {"result": "success", "rates": {"USD": 1.0, "RUB": 80.0}},
    )
    assert execute_tool("currency_rates", {"base": "US"})["ok"] is False
    assert execute_tool("currency_rates", {"base": "USD", "targets": ["XXX"]})["ok"] is False
    agent_tools._rates_cache.clear()


def test_currency_rates_default_targets(monkeypatch) -> None:
    from app import agent_tools

    agent_tools._rates_cache.clear()
    monkeypatch.setattr(
        agent_tools,
        "_fetch_rates",
        lambda base: {
            "result": "success",
            "rates": {"USD": 1.0, "RUB": 80.0, "EUR": 0.9, "CNY": 7.0, "GBP": 0.8},
        },
    )
    result = execute_tool("currency_rates", {"base": "USD"})
    assert result["ok"] is True
    assert set(result["result"]["rates"]) == {"RUB", "EUR", "CNY", "GBP"}
    agent_tools._rates_cache.clear()


def test_unit_converter() -> None:
    km = execute_tool("unit_converter", {"value": 5, "from_unit": "km", "to_unit": "m"})
    assert km["ok"] is True
    assert km["result"]["result"] == 5000

    celsius = execute_tool("unit_converter", {"value": 100, "from_unit": "C", "to_unit": "F"})
    assert celsius["result"]["result"] == 212

    pounds = execute_tool("unit_converter", {"value": 1, "from_unit": "kg", "to_unit": "lb"})
    assert pounds["result"]["result"] == 2.204623


def test_date_diff_between_dates() -> None:
    result = execute_tool(
        "date_diff", {"start": "2026-01-01", "end": "2026-11-09"}
    )
    assert result["ok"] is True
    assert result["result"]["days"] == 312
    assert result["result"]["abs_days"] == 312


def test_date_diff_add_days() -> None:
    result = execute_tool("date_diff", {"start": "2026-01-01", "days": 10})
    assert result["ok"] is True
    assert result["result"]["target"] == "2026-01-11"


def test_number_base() -> None:
    hex_result = execute_tool(
        "number_base", {"value": "255", "from_base": 10, "to_base": 16}
    )
    assert hex_result["result"]["result"] == "ff"

    binary_result = execute_tool(
        "number_base", {"value": "1010", "from_base": 2, "to_base": 10}
    )
    assert binary_result["result"]["result"] == "10"


def test_number_stats() -> None:
    result = execute_tool("number_stats", {"numbers": [2, 4, 6]})
    assert result["ok"] is True
    stats = result["result"]
    assert stats["count"] == 3
    assert stats["sum"] == 12
    assert stats["mean"] == 4
    assert stats["median"] == 4
    assert stats["stdev"] == 1.632993


def test_text_hash() -> None:
    result = execute_tool("text_hash", {"text": "hello", "algorithm": "sha256"})
    assert result["ok"] is True
    assert result["result"]["hash"] == (
        "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"
    )
    assert result["result"]["hex_length"] == 64


@pytest.mark.parametrize(
    ("prompt", "expected"),
    [
        ("Какой курс доллара к рублю?", "currency_rates"),
        ("Сколько будет 17 * 4?", "calculator"),
        ("Посчитай 17% от 4 850", "calculator"),
        ("Сколько сейчас времени в Москве?", "current_time"),
        ("Сколько слов в этом тексте?", "text_stats"),
        ("Переведи 5 км в метры", "unit_converter"),
        ("Сколько дней между 2026-01-01 и 2026-11-09?", "date_diff"),
        ("Переведи 255 в шестнадцатеричную", "number_base"),
        ("Среднее чисел 2, 4, 6", "number_stats"),
        ("SHA256 от текста hello", "text_hash"),
        ("Напиши текст про агентов", None),
        ("Привет, как дела?", None),
    ],
)
def test_required_tool(prompt: str, expected: str | None) -> None:
    from app.agent_tools import required_tool

    assert required_tool(prompt) == expected


def test_required_tools_for_all_nine_tools_example() -> None:
    from app.agent_tools import required_tools

    prompt = (
        "Собери отчёт: время в Москве; сколько дней до 2027-01-01; "
        "курс USD/RUB и 250 USD в рублях; 5 км в метрах; 255 в hex; "
        "среднее чисел 2, 4, 6; SHA256 от hello; сколько слов в "
        "«агент вызывает инструменты по шагам»."
    )
    assert required_tools(prompt) == [
        "text_hash", "number_base", "date_diff", "unit_converter",
        "number_stats", "currency_rates", "text_stats", "current_time",
        "calculator",
    ]


def test_required_tools_for_currency_and_math() -> None:
    from app.agent_tools import required_tools

    assert required_tools(
        "Узнай курс доллара к рублю и посчитай, сколько рублей в 250 долларах."
    ) == ["currency_rates", "calculator"]
    assert required_tools("Сколько рублей в 250 долларах?") == [
        "currency_rates", "calculator",
    ]
    assert required_tools("Какой сегодня курс доллара к рублю?") == ["currency_rates"]
    assert required_tools(
        "Сколько дней между 2026-01-01 и 2026-11-09?"
    ) == ["date_diff"]
    assert required_tools("Переведи 5 км в метры") == ["unit_converter"]


def test_current_time_default_timezone() -> None:
    result = execute_tool("current_time", {})
    assert result["ok"] is True
    assert result["result"]["timezone"] == "Europe/Moscow"
    assert result["result"]["weekday"]


def test_current_time_unknown_timezone() -> None:
    result = execute_tool("current_time", {"timezone": "Mars/Olympus"})
    assert result["ok"] is False


def test_unknown_tool_is_reported() -> None:
    result = execute_tool("nope", {})
    assert result["ok"] is False
    assert "Неизвестный" in result["error"]


def test_tool_catalog_matches_schemas() -> None:
    catalog = tool_catalog()
    assert len(catalog) == len(TOOL_SCHEMAS) == 9
    assert {item["name"] for item in catalog} == {
        "calculator", "current_time", "text_stats", "currency_rates",
        "unit_converter", "date_diff", "number_base", "number_stats", "text_hash",
    }
