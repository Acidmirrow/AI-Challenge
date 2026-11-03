"""Форматы ответа: сборка запроса, разбор и валидация."""

from __future__ import annotations

import pytest

from app.formats import FORMATS_BY_ID, build_format_request, parse_check, parse_payload
from app.validation import InvalidSchema, check_schema, validate

MOVIE_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "year": {"type": "integer"},
        "rating": {"type": "number"},
    },
    "required": ["title", "year", "rating"],
    "additionalProperties": False,
}


def test_text_format_has_no_structured_params() -> None:
    built = build_format_request(FORMATS_BY_ID["text"], "привет", None)
    assert built.response_format is None and built.tools is None
    assert [m["role"] for m in built.messages] == ["system", "user"]


def test_json_object_sends_response_format_and_schema_hint() -> None:
    built = build_format_request(FORMATS_BY_ID["json_object"], "матрица", MOVIE_SCHEMA, schema_name="movie")
    assert built.response_format == {"type": "json_object"}
    assert "JSON Schema" in built.messages[0]["content"]
    assert '"year"' in built.messages[0]["content"]


def test_json_schema_uses_strict_wrapper() -> None:
    built = build_format_request(FORMATS_BY_ID["json_schema"], "матрица", MOVIE_SCHEMA, schema_name="movie")
    sent = built.response_format or {}
    assert sent["type"] == "json_schema"
    assert sent["json_schema"]["strict"] is True
    assert sent["json_schema"]["schema"] == MOVIE_SCHEMA


def test_json_schema_downgrades_when_model_lacks_support() -> None:
    built = build_format_request(
        FORMATS_BY_ID["json_schema"], "матрица", MOVIE_SCHEMA,
        schema_name="movie", supports_json_schema=False,
    )
    assert built.response_format == {"type": "json_object"}
    assert '"year"' in built.messages[0]["content"]
    assert built.notes and "json_object" in built.notes[0]
    assert built.schema == MOVIE_SCHEMA


def test_tool_call_forces_tool_choice_when_thinking_is_off() -> None:
    built = build_format_request(
        FORMATS_BY_ID["tool_call"], "матрица", MOVIE_SCHEMA, tool_name="save_movie", reasoning="off"
    )
    tools = built.tools or []
    assert tools[0]["function"]["name"] == "save_movie"
    assert tools[0]["function"]["parameters"] == MOVIE_SCHEMA
    assert built.tool_choice == {"type": "function", "function": {"name": "save_movie"}}
    assert built.notes == []


def test_tool_call_falls_back_to_auto_in_thinking_mode() -> None:
    built = build_format_request(
        FORMATS_BY_ID["tool_call"], "матрица", MOVIE_SCHEMA, reasoning="high"
    )
    assert built.tool_choice == "auto"
    assert built.notes and "tool_choice" in built.notes[0]


@pytest.mark.parametrize("fmt", ["json_object", "json_schema", "tool_call"])
def test_parse_valid_json(fmt: str) -> None:
    parsed, tool_call, error = parse_payload(FORMATS_BY_ID[fmt], '{"title": "Матрица"}', '{"title": "Матрица"}', "save_movie")
    assert parsed == {"title": "Матрица"}
    assert error is None
    if fmt == "tool_call":
        assert tool_call and tool_call["name"] == "save_movie"


def test_parse_strips_markdown_fence() -> None:
    parsed, _, error = parse_payload(FORMATS_BY_ID["json_object"], '```json\n{"a": 1}\n```', "", None)
    assert parsed == {"a": 1} and error is None


def test_parse_reports_broken_json() -> None:
    parsed, _, error = parse_payload(FORMATS_BY_ID["json_object"], '{"a": ', "", None)
    assert parsed is None
    assert error and "JSON" in error


def test_parse_tool_call_without_arguments() -> None:
    parsed, _, error = parse_payload(FORMATS_BY_ID["tool_call"], "", "", None)
    assert parsed is None
    assert error and "не вызвала" in error


def test_markdown_format_returns_text() -> None:
    parsed, tool_call, error = parse_payload(FORMATS_BY_ID["markdown"], "| a | b |", "", None)
    assert parsed == "| a | b |" and tool_call is None and error is None


def test_validation_paths_are_human_readable() -> None:
    errors = validate({"title": "Матрица"}, MOVIE_SCHEMA)
    paths = {item["path"] for item in errors}
    assert paths == {"year", "rating"}
    assert all(item["validator"] == "required" for item in errors)


def test_extra_keys_are_caught_when_schema_forbids_them() -> None:
    errors = validate({"title": "M", "year": 1999, "rating": 8.7, "extra": 1}, MOVIE_SCHEMA)
    assert [item["path"] for item in errors] == ["extra"]
    assert errors[0]["validator"] == "additionalProperties"


def test_invalid_schema_is_rejected() -> None:
    with pytest.raises(InvalidSchema):
        check_schema({"type": "unknown-type"})


def test_system_prompt_override_replaces_builtin_hint() -> None:
    built = build_format_request(
        FORMATS_BY_ID["text"], "матрица", None, system_prompt="Ответь ровно тремя пунктами."
    )
    assert built.messages[0] == {"role": "system", "content": "Ответь ровно тремя пунктами."}


def test_empty_system_prompt_falls_back_to_builtin_hint() -> None:
    built = build_format_request(FORMATS_BY_ID["markdown"], "матрица", None, system_prompt="   ")
    assert "Markdown" in built.messages[0]["content"]


def test_parse_check_json() -> None:
    check = parse_check(FORMATS_BY_ID["json_object"], '{"a": 1}', None)
    assert check["ok"] is True and check["kind"] == "json"


def test_parse_check_markdown_table() -> None:
    table = "| a | b |\n|---|---|\n| 1 | 2 |\n| 3 | 4 |"
    check = parse_check(FORMATS_BY_ID["markdown"], table, None)
    assert check["ok"] is True and check["kind"] == "markdown_table"
    assert "2" in check["detail"]


def test_parse_check_plain_text_is_not_parseable() -> None:
    check = parse_check(FORMATS_BY_ID["text"], "Матрица — хороший фильм.", None)
    assert check["ok"] is False and check["kind"] == "text"


def test_parse_check_tool_arguments() -> None:
    check = parse_check(
        FORMATS_BY_ID["tool_call"], "", {"name": "save_movie", "arguments": '{"title": "Матрица"}'}
    )
    assert check["ok"] is True and check["kind"] == "json"


def test_stop_passed_to_provider_kwargs() -> None:
    from app.config import Settings
    from app.providers.base import ProviderRequest
    from app.providers.openai_provider import OpenAIProvider

    provider = OpenAIProvider(Settings(provider="openai", openai_api_key="sk-test"))
    kwargs = provider._kwargs(
        ProviderRequest(
            messages=[{"role": "user", "content": "hi"}],
            model="gpt-4.1",
            stop=["\n\n", "5"],
            temperature=0.0,
        )
    )
    assert kwargs["stop"] == ["\n\n", "5"]

