import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture()
def client():
    with TestClient(app) as test_client:
        yield test_client


def test_health_and_models(client: TestClient) -> None:
    health = client.get("/api/health").json()
    assert health["status"] == "ok"
    assert health["models"] >= 3
    models = client.get("/api/models").json()
    assert any(item["id"] == "mock-fast" for item in models)


def test_presets_are_available(client: TestClient) -> None:
    data = client.get("/api/presets").json()
    assert len(data["presets"]) >= 3
    assert all(item["text"] for item in data["presets"])


def test_analyze_short_text_fits(client: TestClient) -> None:
    result = client.post(
        "/api/analyze",
        json={"text": "Привет, мир!", "model": "mock-fast", "output_reserve": 1000},
    ).json()
    assert result["tokens"] == 4
    assert result["words"] == 2
    assert result["fits"] is True
    assert result["overflow"] == 0
    assert len(result["preview"]) == 4


def test_analyze_detects_overflow_and_truncates(client: TestClient) -> None:
    text = "one two three four five six seven eight nine ten"
    result = client.post(
        "/api/analyze",
        json={"text": text, "model": "mock-fast", "output_reserve": 31_995},
    ).json()
    assert result["available"] == 5
    assert result["tokens"] == 10
    assert result["fits"] is False
    assert result["overflow"] == 5
    assert result["truncated_tokens"] == 5
    assert result["truncated_text"] == "one two three four five"
    assert result["kept_tokens"] == 5
    assert result["dropped_tokens"] == 5


def test_truncate_endpoint(client: TestClient) -> None:
    result = client.post(
        "/api/truncate",
        json={"text": "one two three four", "max_tokens": 2},
    ).json()
    assert result["text"] == "one two"
    assert result["tokens"] == 2
    assert result["dropped_tokens"] == 2


def test_cost_uses_input_and_output_tariffs(client: TestClient) -> None:
    result = client.post(
        "/api/analyze",
        json={
            "text": "one two three four",
            "model": "deepseek-flash",
            "output_reserve": 1000,
        },
    ).json()
    assert result["tokens"] == 4
    assert result["input_price_per_1m"] == 0.28
    assert result["output_price_per_1m"] == 0.42
    assert result["input_cost"] == pytest.approx(4 / 1_000_000 * 0.28, abs=1e-9)
    assert result["output_cost"] == pytest.approx(1000 / 1_000_000 * 0.42, abs=1e-9)
    assert result["total_cost"] == pytest.approx(
        result["input_cost"] + result["output_cost"], abs=1e-9
    )


def test_compare_three_contexts(client: TestClient) -> None:
    result = client.post(
        "/api/compare",
        json={
            "base_text": "one two three",
            "model": "mock-fast",
            "output_reserve": 100,
            "demo_window": 1_000,
        },
    ).json()
    assert result["available"] == 900
    assert [item["kind"] for item in result["contexts"]] == [
        "minimal", "large", "maximal",
    ]
    assert result["contexts"][0]["fits"] is True
    assert result["contexts"][1]["fits"] is True
    assert result["contexts"][2]["fits"] is False
    assert result["contexts"][2]["overflow"] > 0
    assert result["contexts"][2]["kept_tokens"] == 900
    assert result["contexts"][2]["dropped_tokens"] > 0
    assert len(result["dependencies"]) == 4


def test_dialogue_grows_and_overflows(client: TestClient) -> None:
    result = client.post(
        "/api/dialogue",
        json={
            "model": "deepseek-flash",
            "turns": 5,
            "user_tokens": 100,
            "assistant_tokens": 200,
            "system_tokens": 20,
            "demo_window": 1_000,
        },
    ).json()
    turns = result["turns"]
    assert len(turns) == 5
    assert turns[0]["prompt_tokens"] == 120
    assert turns[0]["history_tokens"] == 20
    assert turns[-1]["prompt_tokens"] == 1_320
    assert turns[0]["fits"] is True
    assert turns[-1]["fits"] is False
    assert result["first_overflow_turn"] == 4
    assert result["first_overflow_tokens"] > 0
    assert len(result["risks"]) == 5


def test_compare_charges_only_kept_tokens_on_overflow(client: TestClient) -> None:
    result = client.post(
        "/api/compare",
        json={
            "base_text": "one two three",
            "model": "deepseek-flash",
            "output_reserve": 500,
            "demo_window": 512,
        },
    ).json()
    maximal = result["contexts"][2]
    assert maximal["tokens"] == 14
    assert maximal["kept_tokens"] == 12
    assert maximal["input_cost"] == pytest.approx(12 / 1_000_000 * 0.28, abs=1e-9)


def test_unknown_model_is_rejected(client: TestClient) -> None:
    response = client.post(
        "/api/analyze",
        json={"text": "hello", "model": "missing-model"},
    )
    assert response.status_code == 400
