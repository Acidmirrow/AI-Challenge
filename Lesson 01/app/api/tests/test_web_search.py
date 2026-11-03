"""Web-search toggle: SSE contract, prompt augmentation, failure handling."""

from __future__ import annotations

import base64
import json
from typing import AsyncIterator

import pytest
from fastapi.testclient import TestClient

import app.main as main_module
from app.config import Settings
from app.providers.base import Provider, ProviderRequest, StreamEvent
from app.search import (
    Bing,
    BraveHtml,
    DuckDuckGo,
    SearchError,
    SearchResult,
    _decode_bing_url,
    _real_url,
    backend_infos,
    build_search,
    format_context,
)

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
    monkeypatch.setattr(main_module, "build_provider", lambda settings, name=None: provider)
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
    monkeypatch.setattr(main_module, "build_search", lambda settings, name=None: FakeSearch())

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
    monkeypatch.setattr(main_module, "build_search", lambda settings, name=None: FakeSearch())

    events = parse_sse(chat(client).text)
    assert all(kind not in ("search", "search_start") for kind, _ in events)
    assert [m["role"] for m in provider.requests[-1].messages] == ["user"]


def test_search_failure_still_answers(monkeypatch, app_client):
    client, _ = app_client
    monkeypatch.setattr(main_module, "build_search", lambda settings, name=None: FakeSearch(error="HTTP 429"))

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
    with pytest.raises(SearchError):  # no key configured
        build_search(Settings(web_search_backend="tavily"))


@pytest.mark.parametrize(
    ("name", "cls"),
    [("duckduckgo", DuckDuckGo), ("bing", Bing), ("brave-html", BraveHtml)],
)
def test_explicit_backend_selection(name, cls):
    backend = build_search(Settings(), name)
    assert isinstance(backend, cls)


def test_unknown_backend_is_rejected():
    with pytest.raises(SearchError) as exc:
        build_search(Settings(), "yandex")
    assert "Неизвестный бэкенд" in str(exc.value)


def test_backend_catalog_marks_keyed_backends_unavailable():
    infos = {b["name"]: b for b in backend_infos(Settings())}
    assert {"auto", "duckduckgo", "bing", "brave-html", "brave-api", "tavily"} <= set(infos)
    assert infos["duckduckgo"]["available"] is True
    assert infos["bing"]["available"] is True
    assert infos["tavily"]["available"] is False
    assert infos["brave-api"]["requires_key"] == "brave_api_key"


def test_bing_parser_decodes_redirect_links(monkeypatch):
    target = "https://cbr.ru/hd_base/KeyRate/"
    encoded = base64.urlsafe_b64encode(target.encode()).decode().rstrip("=")
    body = (
        '<li class="b_algo"><h2><a href="https://www.bing.com/ck/a?!&amp;&amp;p=abc'
        f'&amp;u=a1{encoded}&amp;ntb=1">Ключевая ставка &amp; ЦБ</a></h2>'
        "<p>Текущее значение ставки</p></li>"
    )
    backend = Bing()

    async def fake_fetch(query: str) -> str:
        return body

    monkeypatch.setattr(backend, "_fetch", fake_fetch)
    results = __import__("asyncio").run(backend.search("ставка", 5))
    assert results[0].url == target
    assert results[0].title == "Ключевая ставка & ЦБ"
    assert results[0].snippet == "Текущее значение ставки"
    assert _decode_bing_url("https://example.test/plain") == "https://example.test/plain"


def test_search_backends_endpoint():
    client = TestClient(main_module.create_app())
    body = client.get("/api/search/backends").json()
    names = [item["name"] for item in body]
    assert names[:3] == ["auto", "duckduckgo", "bing"]
    assert all("available" in item for item in body)


def test_request_backend_override_is_honoured(monkeypatch, app_client):
    client, _ = app_client
    seen: list[str | None] = []

    def fake_build(settings, name=None):
        seen.append(name)
        return FakeSearch()

    monkeypatch.setattr(main_module, "build_search", fake_build)
    events = parse_sse(chat(client, web_search=True, search_backend="bing").text)
    assert seen and seen[-1] == "bing"
    search_payload = dict(events)["search"]
    assert search_payload["query"] and search_payload["error"] is None


def test_unknown_backend_in_request_returns_400(monkeypatch, app_client):
    client, _ = app_client

    def fake_build(settings, name=None):
        raise SearchError(f"Неизвестный бэкенд поиска {name!r}")

    monkeypatch.setattr(main_module, "build_search", fake_build)
    response = chat(client, web_search=True, search_backend="nope")
    assert response.status_code == 400
    assert "Неизвестный бэкенд" in response.json()["detail"]


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
