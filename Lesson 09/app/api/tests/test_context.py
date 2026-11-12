from app.context import build_context
from app.context import build_summary_context
from app.dialogue import demo_messages, demo_summaries


def test_demo_has_25_messages_and_concrete_facts() -> None:
    messages = demo_messages()
    assert len(messages) == 25
    text = "\n".join(item["content"] for item in messages)
    assert "4 850 000" in text
    assert "31 марта 2027" in text
    assert "ул. Лесная, 14" in text
    assert "320 м²" in text
    assert "30/40/30" in text


def test_full_strategy_keeps_everything() -> None:
    messages = demo_messages()
    result = build_context(
        messages,
        strategy="full",
        max_messages=4,
        max_tokens=100_000,
        reserve_tokens=500,
    )
    assert len(result.included) == 25
    assert not result.dropped
    assert result.fits is True


def test_last_strategy_keeps_requested_tail() -> None:
    messages = demo_messages()
    result = build_context(
        messages,
        strategy="last",
        max_messages=4,
        max_tokens=100_000,
        reserve_tokens=500,
    )
    assert [item["id"] for item in result.included] == [22, 23, 24, 25]
    assert len(result.dropped) == 21


def test_budget_strategy_drops_old_messages() -> None:
    messages = demo_messages()
    result = build_context(
        messages,
        strategy="budget",
        max_messages=24,
        max_tokens=500,
        reserve_tokens=100,
        system_tokens=20,
    )
    assert result.available == 400
    assert result.message_budget == 380
    assert result.included
    assert result.included_tokens <= result.message_budget
    assert result.dropped
    assert result.fits is True
    assert result.included[0]["id"] > 1


def test_budget_strategy_honors_message_limit() -> None:
    result = build_context(
        demo_messages(),
        strategy="budget",
        max_messages=4,
        max_tokens=100_000,
        reserve_tokens=100,
    )
    assert [item["id"] for item in result.included] == [22, 23, 24, 25]
    assert len(result.dropped) == 21


def test_summaries_cover_every_ten_messages() -> None:
    messages = demo_messages()
    summaries = demo_summaries()
    assert len(summaries) == 3
    for summary in summaries:
        block = messages[summary["from_id"] - 1 : summary["to_id"]]
        assert summary["tokens"] < sum(item["tokens"] for item in block)
    assert [(s["from_id"], s["to_id"]) for s in summaries] == [(1, 10), (11, 20), (21, 25)]


def test_summary_context_uses_separate_summaries() -> None:
    summaries = demo_summaries()
    result = build_summary_context(
        summaries,
        max_tokens=4_000,
        reserve_tokens=500,
        system_tokens=20,
    )
    assert result.included
    assert all(item["id"] >= 1001 for item in result.included)
    assert result.included_tokens < 1_000
