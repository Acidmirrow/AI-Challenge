"""Web-search toggle: SSE contract, prompt augmentation, failure handling."""

from __future__ import annotations

import json
from typing import AsyncIterator

import pytest
from fastapi.testclient import TestClient

import app.main as main_module
from app.config import Settings
from app.providers.base import Provider, ProviderRequest, StreamEvent
from app.search import BraveHtml, DuckDuckGo, SearchError, SearchResult, _real_url, build_search, format_context

RESULTS = [
    SearchResult("DeepSeek V4.1 Flash", "https://example.test/v4", "Новая модель с контекстом 1M"),
    SearchResult("Docs", "https://example.test/docs", "Справочник API"),
]


class FakeSearch:
    name = "fake"

    def __init__(self, results=None, error: str | None = None):
        self._results = RESULTS if results is None else results
        self._error = error

    async def search(self, query: str, limit: int = 5):
        if self._error:
            raise SearchError(self._error)
        return self._results[:limit]


class CapturingProvider(Provider):
    name = "capturing"

    def __init__(self):
        self.requests: list[ProviderRequest] = []

    async def stream(self, request: ProviderRequest) -> AsyncIterator[StreamEvent]:
        self.requests.append(request)
        yield StreamEvent("delta", text="ok")
        yield StreamEvent("done", data={"model": request.model, "elapsed_ms": 1})


def parse_sse(raw: str) -> list[tuple[str, dict]]:
    events, event, data = [], None, []
    for line in raw.splitlines() + [""]:
        if line == "":
            if event:
                events.append((event, json.loads("".join(data) or "{}")))
            event, data = None, []
        elif line.startswith("event:"):
            event = line[6:].strip()
        elif line.startswith("data:"):
            data.append(line[5:].strip())
    return events


@pytest.fixture
def app_client(monkeypatch):
    provider = CapturingProvider()
    monkeypatch.setattr(main_module, "build_provider", lambda settings: provider)
    client = TestClient(main_module.create_app())
    return client, provider


def chat(client, **overrides):
    payload = {
        "model": "mock-reasoner",
        "messages": [{"role": "user", "content": "что нового в deepseek"}],
        "reasoning": "off",
        **overrides,
    }
    return client.post("/api/chat", json=payload)


def test_search_events_and_context_injection(monkeypatch, app_client):
    client, provider = app_client
    monkeypatch.setattr(main_module, "build_search", lambda settings: FakeSearch())

    events = parse_sse(chat(client, web_search=True).text)
    kinds = [kind for kind, _ in events]
    assert kinds[0] == "search_start"
    assert kinds[1] == "search"
    assert kinds[-1] == "done"

    search_payload = events[1][1]
    assert search_payload["backend"] == "fake"
    assert [r["url"] for r in search_payload["results"]] == [
        "https://example.test/v4",
        "https://example.test/docs",
    ]

    sent = provider.requests[-1].messages
    assert sent[0]["role"] == "system"
    assert "Результаты веб-поиска" in sent[0]["content"]
    assert "https://example.test/v4" in sent[0]["content"]
    assert sent[-1]["content"] == "что нового в deepseek"


def test_search_off_by_default_keeps_prompt_clean(monkeypatch, app_client):
    client, provider = app_client
    monkeypatch.setattr(main_module, "build_search", lambda settings: FakeSearch())

    events = parse_sse(chat(client).text)
    assert all(kind not in ("search", "search_start") for kind, _ in events)
    assert [m["role"] for m in provider.requests[-1].messages] == ["user"]


def test_search_failure_still_answers(monkeypatch, app_client):
    client, _ = app_client
    monkeypatch.setattr(main_module, "build_search", lambda settings: FakeSearch(error="HTTP 429"))

    events = parse_sse(chat(client, web_search=True).text)
    kinds = [kind for kind, _ in events]
    assert "search" in kinds
    search_payload = dict(events)[ "search"]
    assert search_payload["results"] == []
    assert "429" in search_payload["error"]
    assert kinds[-1] == "done"


def test_health_reports_search_backend():
    client = TestClient(main_module.create_app())
    body = client.get("/api/health").json()
    assert "web_search" in body


def test_brave_html_parser_extracts_results(monkeypatch):
    html = """
    <div class="snippet" data-type="web">
      <a href="https://a.test/one" class="x l1"><div class="title search-snippet-title">First &amp; best</div></a>
      <div class="generic-snippet"><div class="content desktop-default-regular">Snippet one</div></div>
    </div>
    <div class="snippet" data-type="web">
      <a href="https://b.test/two" class="x l1"><div class="title search-snippet-title">Second</div></a>
      <div class="generic-snippet"><div class="content desktop-default-regular">Snippet two</div></div>
    </div>
    """
    backend = BraveHtml()

    async def fake_get(url: str) -> str:
        assert "q=" in url
        return html

    monkeypatch.setattr(backend, "_get", fake_get)
    results = __import__("asyncio").run(backend.search("deepseek", 5))
    assert [r.url for r in results] == ["https://a.test/one", "https://b.test/two"]
    assert results[0].title == "First & best"
    assert results[1].snippet == "Snippet two"


def test_duckduckgo_parses_results_and_decodes_redirects(monkeypatch):
    body = """
    <a rel="nofollow" class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fcbr.ru%2Fcurrency_base%2Fdaily%2F&rut=x">Курс ЦБ &amp; данные</a>
    <a class="result__snippet" href="https://cbr.ru/">Официальные курсы валют</a>
    <a rel="nofollow" class="result__a" href="https://example.test/direct">Прямая ссылка</a>
    <a class="result__snippet" href="https://example.test/direct">Второй сниппет</a>
    """
    backend = DuckDuckGo()

    async def fake_fetch(query: str) -> str:
        assert query == "курс"
        return body

    monkeypatch.setattr(backend, "_fetch", fake_fetch)
    results = __import__("asyncio").run(backend.search("курс", 5))
    assert [r.url for r in results] == ["https://cbr.ru/currency_base/daily/", "https://example.test/direct"]
    assert results[0].title == "Курс ЦБ & данные"
    assert results[0].snippet == "Официальные курсы валют"
    assert _real_url("//duckduckgo.com/l/?uddg=https%3A%2F%2Fa.test%2Fb") == "https://a.test/b"


def test_build_search_respects_configuration():
    assert build_search(Settings(web_search_backend="off")) is None
    chain = build_search(Settings(web_search_backend="auto"))
    assert chain is not None and "duckduckgo" in chain.name
    assert build_search(Settings(web_search_backend="tavily")) is None  # no key configured


def test_html_to_text_strips_markup_and_scripts():
    from app.search import html_to_text

    raw = (
        "<html><head><style>.x{color:red}</style><script>var secret=1;</script></head>"
        "<body><p>Курс доллара</p><div>41,25 руб.</div></body></html>"
    )
    text = html_to_text(raw)
    assert "Курс доллара" in text
    assert "41,25" in text
    assert "secret" not in text and "color:red" not in text


def test_format_context_includes_page_text_when_available():
    result = SearchResult("ЦБ", "https://cbr.ru/x", "сниппет", "Текст страницы: 41,25 руб. за доллар")
    text = format_context("курс", [result])
    assert "Текст страницы" in text and "41,25" in text


def test_format_context_lists_sources_and_date():
    text = format_context("deepseek", RESULTS)
    assert "«deepseek»" in text
    assert "[1] DeepSeek V4.1 Flash" in text
    assert "URL: https://example.test/v4" in text
