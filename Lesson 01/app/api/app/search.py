"""Web search backends used when the chat request asks for internet access.

Keyless by default (Brave HTML endpoint), upgradeable with an API key
(Tavily / Brave Search API). Every backend is best-effort: a failure is reported
in the SSE `search` event, it never aborts the answer.
"""

from __future__ import annotations

import base64
import binascii
import html
import re
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Iterable
from urllib.parse import parse_qs, unquote, urlparse

import httpx

from .config import Settings

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)


class SearchError(RuntimeError):
    pass


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str = ""
    page_text: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


async def add_page_content(
    results: list[SearchResult], top: int = 2, max_chars: int = 1500, timeout: float = 8.0
) -> list[SearchResult]:
    """Fetch readable text of the top hits so the model sees facts, not just snippets.

    Best-effort: a page that fails to load simply keeps its snippet.
    """
    if not results:
        return results
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        for result in results[:top]:
            try:
                response = await client.get(
                    result.url,
                    headers={"User-Agent": USER_AGENT, "Accept-Language": "ru,en;q=0.8"},
                )
            except httpx.HTTPError:
                continue
            if response.status_code != 200 or "html" not in response.headers.get("content-type", ""):
                continue
            result.page_text = html_to_text(response.text)[:max_chars]
    return results


def html_to_text(raw: str) -> str:
    text = re.sub(r"(?is)<(script|style|noscript|svg)[^>]*>.*?</\1>", " ", raw)
    text = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</li>|</tr>", "\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"[ \t\u00a0]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text)
    return text.strip()


class SearchBackend(ABC):
    name = "base"

    @abstractmethod
    async def search(self, query: str, limit: int = 5) -> list[SearchResult]:
        ...


class Chain(SearchBackend):
    """Try backends in order, keep the first non-empty answer."""

    def __init__(self, backends: list[SearchBackend]):
        self._backends = backends
        self.name = "+".join(b.name for b in backends)

    async def search(self, query: str, limit: int = 5) -> list[SearchResult]:
        errors: list[str] = []
        for backend in self._backends:
            try:
                results = await backend.search(query, limit)
            except Exception as exc:  # noqa: BLE001 - try the next backend
                errors.append(f"{backend.name}: {exc}")
                continue
            if results:
                self.name = backend.name
                return results
            errors.append(f"{backend.name}: пусто")
        raise SearchError("; ".join(errors) or "нет доступных бэкендов")


class _HtmlSearch(SearchBackend):
    """Shared httpx plumbing for HTML search endpoints."""

    def __init__(self, timeout: float = 12.0):
        self._timeout = timeout

    async def _get(self, url: str) -> str:
        async with httpx.AsyncClient(timeout=self._timeout, follow_redirects=True) as client:
            response = await client.get(url, headers={"User-Agent": USER_AGENT, "Accept-Language": "ru,en;q=0.8"})
        if response.status_code != 200:
            raise SearchError(f"HTTP {response.status_code}")
        return response.text


def _clean(raw: str) -> str:
    text = re.sub(r"<[^>]+>", " ", raw)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


class BraveHtml(_HtmlSearch):
    """Brave web search page, parsed. No API key required."""

    name = "brave-html"

    async def search(self, query: str, limit: int = 5) -> list[SearchResult]:
        url = str(httpx.URL("https://search.brave.com/search").copy_merge_params({"q": query}))
        body = await self._get(url)
        results: list[SearchResult] = []
        for block in body.split('data-type="web"')[1:]:
            link = re.search(r'<a href="(https?://[^"]+)"', block)
            if not link:
                continue
            title = re.search(r'class="title search-snippet-title[^"]*"[^>]*>(.*?)</div>', block, re.S)
            snippet = re.search(r'class="content[^"]*"[^>]*>(.*?)</div>', block, re.S)
            url = link.group(1)
            if any(r.url == url for r in results):
                continue
            results.append(
                SearchResult(
                    title=_clean(title.group(1)) if title else url,
                    url=url,
                    snippet=_clean(snippet.group(1)) if snippet else "",
                )
            )
            if len(results) >= limit:
                break
        if not results:
            raise SearchError("страница поиска не содержит результатов")
        return results


class DuckDuckGo(_HtmlSearch):
    """DuckDuckGo HTML endpoint (POST). Keyless, returns clean result URLs."""

    name = "duckduckgo"

    async def _fetch(self, query: str) -> str:
        async with httpx.AsyncClient(timeout=self._timeout, follow_redirects=True) as client:
            response = await client.post(
                "https://html.duckduckgo.com/html/",
                data={"q": query, "kl": "wt-wt"},
                headers={"User-Agent": USER_AGENT, "Accept-Language": "ru,en;q=0.8"},
            )
        if response.status_code != 200:
            raise SearchError(f"HTTP {response.status_code}")
        return response.text

    async def search(self, query: str, limit: int = 5) -> list[SearchResult]:
        body = await self._fetch(query)

        links = re.findall(r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', body, re.S)
        snippets = re.findall(r'class="result__snippet"[^>]*>(.*?)</a>', body, re.S)

        results: list[SearchResult] = []
        for index, (href, title) in enumerate(links):
            if any(r.url and _real_url(href) == r.url for r in results):
                continue
            results.append(
                SearchResult(
                    title=_clean(title) or _real_url(href),
                    url=_real_url(href),
                    snippet=_clean(snippets[index]) if index < len(snippets) else "",
                )
            )
            if len(results) >= limit:
                break
        if not results:
            raise SearchError("DuckDuckGo не вернул результатов (бот-проверка?)")
        return results


def _real_url(href: str) -> str:
    """DuckDuckGo wraps links as /l/?uddg=<encoded target>."""
    if href.startswith("//"):
        href = "https:" + href
    parsed = urlparse(href)
    if parsed.path.startswith("/l/"):
        target = parse_qs(parsed.query).get("uddg")
        if target:
            return unquote(target[0])
    return href


class Bing(_HtmlSearch):
    """Bing web results. Keyless; links come wrapped in bing.com/ck/a redirects."""

    name = "bing"

    async def _fetch(self, query: str) -> str:
        async with httpx.AsyncClient(timeout=self._timeout, follow_redirects=True) as client:
            response = await client.get(
                "https://www.bing.com/search",
                params={"q": query, "setlang": "ru"},
                headers={"User-Agent": USER_AGENT, "Accept-Language": "ru,en;q=0.8"},
            )
        if response.status_code != 200:
            raise SearchError(f"Bing HTTP {response.status_code}")
        return response.text

    async def search(self, query: str, limit: int = 5) -> list[SearchResult]:
        body = await self._fetch(query)
        results: list[SearchResult] = []
        for block in re.findall(r'<li class="b_algo".*?</li>', body, re.S):
            link = re.search(r'<h2><a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', block, re.S)
            if not link:
                continue
            url = _decode_bing_url(html.unescape(link.group(1)))
            if not url.startswith("http") or any(r.url == url for r in results):
                continue
            snippet = re.search(r'<p[^>]*>(.*?)</p>', block, re.S)
            results.append(
                SearchResult(
                    title=_clean(link.group(2)) or url,
                    url=url,
                    snippet=_clean(snippet.group(1)) if snippet else "",
                )
            )
            if len(results) >= limit:
                break
        if not results:
            raise SearchError("Bing не вернул результатов (разметка изменилась?)")
        return results


def _decode_bing_url(href: str) -> str:
    """Bing wraps results as /ck/a?...&u=a1<base64url-of-target>."""
    if "bing.com/ck/a" not in href:
        return href
    raw = parse_qs(urlparse(href).query).get("u", [""])[0]
    if raw.startswith("a1"):
        raw = raw[2:]
    padded = raw + "=" * (-len(raw) % 4)
    try:
        return base64.urlsafe_b64decode(padded).decode("utf-8", "ignore")
    except (ValueError, binascii.Error):
        return href


class Tavily(SearchBackend):
    """Tavily search API — highest quality, needs a key."""

    name = "tavily"

    def __init__(self, api_key: str, timeout: float = 15.0):
        self._api_key = api_key
        self._timeout = timeout

    async def search(self, query: str, limit: int = 5) -> list[SearchResult]:
        payload = {"api_key": self._api_key, "query": query, "max_results": limit, "search_depth": "basic"}
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post("https://api.tavily.com/search", json=payload)
        if response.status_code != 200:
            raise SearchError(f"Tavily HTTP {response.status_code}: {response.text[:120]}")
        data = response.json()
        return [
            SearchResult(
                title=item.get("title", item.get("url", "")),
                url=item.get("url", ""),
                snippet=(item.get("content") or "")[:400],
            )
            for item in data.get("results", [])[:limit]
        ]


class BraveApi(SearchBackend):
    name = "brave-api"

    def __init__(self, api_key: str, timeout: float = 15.0):
        self._api_key = api_key
        self._timeout = timeout

    async def search(self, query: str, limit: int = 5) -> list[SearchResult]:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.get(
                "https://api.search.brave.com/res/v1/web/search",
                params={"q": query, "count": limit},
                headers={"X-Subscription-Token": self._api_key, "Accept": "application/json"},
            )
        if response.status_code != 200:
            raise SearchError(f"Brave API HTTP {response.status_code}: {response.text[:120]}")
        items = response.json().get("web", {}).get("results", [])[:limit]
        return [
            SearchResult(
                title=_clean(item.get("title", "")),
                url=item.get("url", ""),
                snippet=_clean(item.get("description", "")),
            )
            for item in items
        ]


@dataclass(frozen=True)
class BackendInfo:
    """A search backend the UI can offer."""

    name: str
    label: str
    requires_key: str = ""
    note: str = ""


BACKENDS: tuple[BackendInfo, ...] = (
    BackendInfo("auto", "Авто (лучший доступный)", note="ключевые API → keyless"),
    BackendInfo("duckduckgo", "DuckDuckGo", note="без ключа"),
    BackendInfo("bing", "Bing", note="без ключа"),
    BackendInfo("brave-html", "Brave (HTML)", note="без ключа, бывает 429"),
    BackendInfo("brave-api", "Brave API", requires_key="brave_api_key", note="нужен BRAVE_API_KEY"),
    BackendInfo("tavily", "Tavily", requires_key="tavily_api_key", note="нужен TAVILY_API_KEY"),
)


def backend_infos(settings: Settings) -> list[dict]:
    """Catalog for the UI: what exists, what is usable, what is the default."""
    default = (settings.web_search_backend or "off").strip().lower()
    items = []
    for backend in BACKENDS:
        available = not backend.requires_key or bool(getattr(settings, backend.requires_key, ""))
        items.append(
            {
                "name": backend.name,
                "label": backend.label,
                "available": available,
                "requires_key": backend.requires_key,
                "note": backend.note,
                "is_default": backend.name == default,
            }
        )
    return items


def build_search(settings: Settings, name: str | None = None) -> SearchBackend | None:
    """Resolve a backend by name (``auto`` = best available), ``None`` for off."""
    backend = (name or settings.web_search_backend or "off").strip().lower()
    timeout = settings.web_search_timeout_s

    if backend in ("off", "none", "disabled"):
        return None
    if backend == "duckduckgo":
        return DuckDuckGo(timeout)
    if backend == "bing":
        return Bing(timeout)
    if backend in ("brave-html", "brave"):
        return BraveHtml(timeout)
    if backend == "tavily":
        if not settings.tavily_api_key:
            raise SearchError("Для Tavily нужен TAVILY_API_KEY в .env")
        return Tavily(settings.tavily_api_key, timeout)
    if backend == "brave-api":
        if not settings.brave_api_key:
            raise SearchError("Для Brave API нужен BRAVE_API_KEY в .env")
        return BraveApi(settings.brave_api_key, timeout)
    if backend == "auto":
        candidates: list[SearchBackend] = []
        if settings.tavily_api_key:
            candidates.append(Tavily(settings.tavily_api_key, timeout))
        if settings.brave_api_key:
            candidates.append(BraveApi(settings.brave_api_key, timeout))
        candidates.extend([DuckDuckGo(timeout), Bing(timeout), BraveHtml(timeout)])
        return Chain(candidates)
    raise SearchError(
        f"Неизвестный бэкенд поиска {backend!r}. Доступно: " + ", ".join(b.name for b in BACKENDS)
    )


def format_context(query: str, results: Iterable[SearchResult]) -> str:
    """System-message block handed to the model alongside the question."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    lines = [
        f"Результаты веб-поиска по запросу «{query}» (получены {today}, UTC):",
        "",
    ]
    for index, result in enumerate(results, start=1):
        lines.append(f"[{index}] {result.title}")
        lines.append(f"URL: {result.url}")
        if result.snippet:
            lines.append(f"Фрагмент: {result.snippet}")
        if result.page_text:
            lines.append(f"Текст страницы: {result.page_text}")
        lines.append("")
    lines.append(
        "Используй эти источники, если они относятся к вопросу, и ссылайся на URL. "
        "Если в источниках нет ответа — прямо скажи, что в найденном нет нужных данных, "
        "и ответь из общих знаний, отметив это."
    )
    return "\n".join(lines)
