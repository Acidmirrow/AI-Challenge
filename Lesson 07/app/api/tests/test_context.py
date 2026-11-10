from app.context import build_context, merge_histories


def history(count: int) -> list[dict]:
    return [
        {"role": "user" if index % 2 == 0 else "assistant", "content": f"m{index}"}
        for index in range(count)
    ]


def test_context_keeps_all_messages_when_fit() -> None:
    window = build_context(history(4), "Новый вопрос", max_messages=10, max_chars=10_000)
    assert window.included == 4
    assert window.dropped == 0
    assert window.messages[0]["role"] == "system"
    assert window.messages[-1] == {"role": "user", "content": "Новый вопрос"}


def test_context_limits_message_count() -> None:
    window = build_context(history(10), "Новый вопрос", max_messages=3, max_chars=10_000)
    assert window.included == 2
    assert window.dropped == 8
    assert [item["content"] for item in window.messages[1:-1]] == ["m8", "m9"]


def test_context_limits_characters() -> None:
    window = build_context(history(5), "x" * 50, max_messages=10, max_chars=30)
    assert window.included == 0
    assert window.chars > 30  # сам вопрос не режем, но старую историю убираем


def test_context_never_drops_the_new_prompt() -> None:
    window = build_context([], "важный вопрос", max_messages=0, max_chars=1)
    assert window.messages[-1]["content"] == "важный вопрос"


def test_merge_histories_remaps_tool_call_ids() -> None:
    past = [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"id": "call_same", "type": "function", "function": {"name": "calculator", "arguments": "{}"}}
            ],
        },
        {"role": "tool", "content": "{}", "tool_call_id": "call_same", "name": "calculator"},
    ]
    current = [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"id": "call_same", "type": "function", "function": {"name": "calculator", "arguments": "{}"}}
            ],
        }
    ]
    merged = merge_histories(current, [("ctx-past", past)])
    past_call = merged[0]["tool_calls"][0]["id"]
    current_call = merged[2]["tool_calls"][0]["id"]
    assert past_call != current_call
    assert merged[1]["tool_call_id"] == past_call
