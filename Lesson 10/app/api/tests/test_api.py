import re

from fastapi.testclient import TestClient

from app.main import app


def test_health_and_strategy_catalog() -> None:
    with TestClient(app) as client:
        health = client.get("/api/health").json()
        assert health["status"] == "ok"
        assert health["lesson"] == 10

        catalog = client.get("/api/strategies").json()
        assert [item["id"] for item in catalog["strategies"]] == [
            "sliding",
            "sticky",
            "summary",
            "full",
        ]
        assert catalog["strategies"][1]["label"] == "Sticky facts / Key-Value memory"


def test_generate_unique_25_message_trunk_and_branches() -> None:
    with TestClient(app) as client:
        first = client.get("/api/generate").json()
        second = client.get("/api/generate").json()

    assert len(first["messages"]) == 25
    assert first["trunk_count"] == 25
    assert first["branch_point"] == 25
    assert len(first["branches"]) == 3
    assert all(10 <= len(branch["messages"]) <= 15 for branch in first["branches"])
    assert all(branch["messages"][0]["id"] == 26 for branch in first["branches"])
    assert len({branch["messages"][0]["id"] for branch in first["branches"]}) == 1
    assert first["trunk_hash"]
    assert any(item["message_id"] == 25 for item in first["checkpoints"])
    assert len(first["summaries"]) == 3
    assert first["code"] != second["code"]
    assert "PRJ-" not in first["title"]
    assert first["messages"][0]["role"] == "user"
    assert first["messages"][-1]["role"] == "user"
    assert first["messages"][1]["content"].startswith("Проект:")
    assert "PRJ-" not in first["messages"][1]["content"]
    assert "Бюджет:" in first["messages"][3]["content"]
    # Конкретные детали встречаются чаще, чем раз в 3–4 сообщения.
    for index in range(3, 25, 4):
        item = first["messages"][index]
        if item["role"] == "assistant":
            assert re.search(r"\d", item["content"]) or ":" in item["content"]


def test_compare_strategies_and_facts() -> None:
    with TestClient(app) as client:
        dialogue = client.get("/api/generate").json()
        result = client.post(
            "/api/compare",
            json={
                "messages": dialogue["messages"],
                "summaries": dialogue["summaries"],
                "sliding_window": 7,
                "facts_window": 6,
            },
        ).json()

    rows = {row["id"]: row for row in result["strategies"]}
    assert rows["sliding"]["messages_count"] == 7
    assert rows["sliding"]["dropped_messages"] == 18
    assert rows["summary"]["summaries_count"] == 3
    assert rows["full"]["messages_count"] == 25

    sticky = rows["sticky"]
    assert sticky["facts_updates"] > 0
    assert sticky["facts_count"] > 0
    assert "Бюджет" in sticky["facts"]
    assert "Срок" in sticky["facts"]
    assert sticky["messages_count"] == 0


def test_facts_window_controls_what_is_extracted() -> None:
    with TestClient(app) as client:
        dialogue = client.get("/api/generate").json()
        narrow = client.post(
            "/api/compare",
            json={
                "messages": dialogue["messages"],
                "summaries": dialogue["summaries"],
                "sliding_window": 7,
                "facts_window": 1,
            },
        ).json()
        wide = client.post(
            "/api/compare",
            json={
                "messages": dialogue["messages"],
                "summaries": dialogue["summaries"],
                "sliding_window": 7,
                "facts_window": 25,
            },
        ).json()

    narrow_facts = next(row for row in narrow["strategies"] if row["id"] == "sticky")
    wide_facts = next(row for row in wide["strategies"] if row["id"] == "sticky")
    assert narrow_facts["facts_count"] == 0
    assert wide_facts["facts_count"] > narrow_facts["facts_count"]


def test_ask_uses_selected_strategy_context() -> None:
    with TestClient(app) as client:
        dialogue = client.get("/api/generate").json()
        answer = client.post(
            "/api/ask",
            json={
                "messages": dialogue["messages"],
                "summaries": dialogue["summaries"],
                "sliding_window": 25,
                "facts_window": 25,
                "strategy": "sticky",
                "question": "Какой бюджет проекта?",
            },
        ).json()

    assert answer["found"] is True
    assert "Бюджет" in answer["answer"]
    assert answer["source"] == "Бюджет"
    assert answer["context"]["id"] == "sticky"


def test_chat_endpoint_answers_without_dialogue() -> None:
    with TestClient(app) as client:
        result = client.post(
            "/api/chat",
            json={"messages": [{"role": "user", "content": "Привет"}]},
        ).json()
    assert result["answer"]
    assert result["model"]


def test_branch_context_is_compared() -> None:
    with TestClient(app) as client:
        dialogue = client.get("/api/generate").json()
        branch = dialogue["branches"][1]
        messages = dialogue["messages"] + branch["messages"]
        summaries = dialogue["summaries"] + branch["summaries"]
        result = client.post(
            "/api/compare",
            json={
                "messages": messages,
                "summaries": summaries,
                "sliding_window": 10,
                "facts_window": 10,
            },
        ).json()

    rows = {row["id"]: row for row in result["strategies"]}
    assert rows["full"]["messages_count"] == len(messages)
    assert rows["full"]["messages_count"] > 25
    assert rows["summary"]["summaries_count"] == 4
    assert rows["sliding"]["dropped_messages"] == len(messages) - 10


def test_generated_messages_are_unique() -> None:
    with TestClient(app) as client:
        dialogue = client.get("/api/generate").json()
    contents = [item["content"] for item in dialogue["messages"]]
    for branch in dialogue["branches"]:
        branch_contents = [item["content"] for item in branch["messages"]]
        assert len(branch_contents) == len(set(branch_contents))
        contents.extend(branch_contents)
    assert len(contents) == len(set(contents))
