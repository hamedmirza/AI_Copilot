from __future__ import annotations

import html
import re
import xml.etree.ElementTree as ET
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Final
from urllib.parse import parse_qs, quote_plus, urlparse

import httpx

_USER_AGENT: Final[str] = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)
_DDG_HEADERS: Final[dict[str, str]] = {
    "User-Agent": _USER_AGENT,
    "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}
_DDG_SEARCH_URL: Final[str] = "https://html.duckduckgo.com/html/"
_GOOGLE_NEWS_RSS_URL: Final[str] = "https://news.google.com/rss/search"
_GITHUB_SEARCH_URL: Final[str] = "https://api.github.com/search/code"
_GOOGLE_CSE_URL: Final[str] = "https://www.googleapis.com/customsearch/v1"
_MAX_SNIPPET_LENGTH: Final[int] = 280
_ANCHOR_RE = re.compile(
    r'<a[^>]*class="result__a"[^>]*href="(?P<href>[^"]+)"[^>]*>(?P<title>.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)
_SNIPPET_RE = re.compile(
    r'<a[^>]*class="result__snippet"[^>]*>(?P<snippet>.*?)</a>|'
    r'<div[^>]*class="result__snippet"[^>]*>(?P<div_snippet>.*?)</div>',
    re.IGNORECASE | re.DOTALL,
)
_TAG_RE = re.compile(r"<[^>]+>")
KNOWN_PROVIDERS: Final[tuple[str, ...]] = ("duckduckgo", "github", "google", "x")


@dataclass(frozen=True)
class WebSearchResult:
    title: str
    url: str
    snippet: str
    provider: str = "duckduckgo"


def parse_provider_names(raw: str | None, *, default: tuple[str, ...] = KNOWN_PROVIDERS) -> tuple[str, ...]:
    if not raw or not str(raw).strip():
        return default
    names: list[str] = []
    for part in str(raw).split(","):
        name = part.strip().lower()
        if name and name in KNOWN_PROVIDERS and name not in names:
            names.append(name)
    return tuple(names or default)


class WebSearchProvider(ABC):
    name: str

    @abstractmethod
    def search(self, client: httpx.Client, query: str, *, limit: int) -> list[WebSearchResult]:
        raise NotImplementedError


class DuckDuckGoHtmlProvider(WebSearchProvider):
    name = "duckduckgo"

    def search(self, client: httpx.Client, query: str, *, limit: int) -> list[WebSearchResult]:
        return _search_duckduckgo_html(client, query, limit=limit, provider=self.name)


class GoogleProvider(WebSearchProvider):
    name = "google"

    def __init__(self, *, api_key: str = "", cse_id: str = "") -> None:
        self.api_key = (api_key or "").strip()
        self.cse_id = (cse_id or "").strip()

    def search(self, client: httpx.Client, query: str, *, limit: int) -> list[WebSearchResult]:
        if self.api_key and self.cse_id:
            response = client.get(
                _GOOGLE_CSE_URL,
                params={
                    "key": self.api_key,
                    "cx": self.cse_id,
                    "q": query,
                    "num": max(1, min(limit, 10)),
                },
                timeout=client.timeout,
            )
            response.raise_for_status()
            payload = response.json()
            items = payload.get("items") if isinstance(payload, dict) else []
            results: list[WebSearchResult] = []
            for item in items or []:
                if not isinstance(item, dict):
                    continue
                title = str(item.get("title") or "").strip()
                url = str(item.get("link") or "").strip()
                snippet = str(item.get("snippet") or "").strip()
                if title and url:
                    results.append(
                        WebSearchResult(
                            title=title,
                            url=url,
                            snippet=snippet[:_MAX_SNIPPET_LENGTH].rstrip(),
                            provider=self.name,
                        )
                    )
                if len(results) >= limit:
                    break
            if results:
                return results
        return _search_duckduckgo_html(
            client,
            f"site:google.com {query}",
            limit=limit,
            provider=self.name,
        )


class GitHubProvider(WebSearchProvider):
    name = "github"

    def __init__(self, *, token: str = "") -> None:
        self.token = (token or "").strip()

    def search(self, client: httpx.Client, query: str, *, limit: int) -> list[WebSearchResult]:
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": _USER_AGENT,
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        response = client.get(
            _GITHUB_SEARCH_URL,
            params={"q": query, "per_page": max(1, min(limit, 10))},
            headers=headers,
            timeout=client.timeout,
        )
        if response.status_code >= 400:
            return _search_duckduckgo_html(
                client,
                f"site:github.com {query}",
                limit=limit,
                provider=self.name,
            )
        payload = response.json()
        items = payload.get("items") if isinstance(payload, dict) else []
        results: list[WebSearchResult] = []
        for item in items or []:
            if not isinstance(item, dict):
                continue
            repo = item.get("repository") if isinstance(item.get("repository"), dict) else {}
            repo_name = str(repo.get("full_name") or "github")
            path = str(item.get("path") or item.get("name") or "").strip()
            url = str(item.get("html_url") or repo.get("html_url") or "").strip()
            title = f"{repo_name}/{path}" if path else repo_name
            snippet = f"GitHub code match in {repo_name}"
            if title and url:
                results.append(
                    WebSearchResult(
                        title=title,
                        url=url,
                        snippet=snippet[:_MAX_SNIPPET_LENGTH].rstrip(),
                        provider=self.name,
                    )
                )
            if len(results) >= limit:
                break
        if results:
            return results
        return _search_duckduckgo_html(
            client,
            f"site:github.com {query}",
            limit=limit,
            provider=self.name,
        )


class XProvider(WebSearchProvider):
    name = "x"

    def search(self, client: httpx.Client, query: str, *, limit: int) -> list[WebSearchResult]:
        return _search_duckduckgo_html(
            client,
            f"site:x.com OR site:twitter.com {query}",
            limit=limit,
            provider=self.name,
        )


def build_providers(
    names: tuple[str, ...],
    *,
    google_api_key: str = "",
    google_cse_id: str = "",
    github_token: str = "",
) -> list[WebSearchProvider]:
    providers: list[WebSearchProvider] = []
    for name in names:
        if name == "duckduckgo":
            providers.append(DuckDuckGoHtmlProvider())
        elif name == "google":
            providers.append(GoogleProvider(api_key=google_api_key, cse_id=google_cse_id))
        elif name == "github":
            providers.append(GitHubProvider(token=github_token))
        elif name == "x":
            providers.append(XProvider())
    return providers


def _search_duckduckgo_html(
    client: httpx.Client,
    query: str,
    *,
    limit: int,
    provider: str,
) -> list[WebSearchResult]:
    """DuckDuckGo HTML search.

    Many queries (news, geopolitics, etc.) return HTTP 202 with no result markup on GET
    but succeed with POST form submission. Try POST first, then GET.
    """
    request_timeout = client.timeout
    for method in ("post", "get"):
        try:
            if method == "post":
                response = client.post(
                    _DDG_SEARCH_URL,
                    data={"q": query},
                    headers=_DDG_HEADERS,
                    timeout=request_timeout,
                    follow_redirects=True,
                )
            else:
                response = client.get(
                    f"{_DDG_SEARCH_URL}?q={quote_plus(query)}",
                    headers=_DDG_HEADERS,
                    timeout=request_timeout,
                    follow_redirects=True,
                )
        except httpx.HTTPError:
            continue
        if response.status_code >= 400:
            continue
        results = _parse_duckduckgo_html(response.text, limit=limit, provider=provider)
        if results:
            return results
    if _should_try_news_rss(query):
        return _search_google_news_rss(client, query, limit=limit, provider="google_news")
    return []


def _should_try_news_rss(query: str) -> bool:
    lowered = query.lower()
    hints = ("news", "latest", "current", "today", "breaking", "headline", "happening")
    return any(hint in lowered for hint in hints)


def _search_google_news_rss(
    client: httpx.Client,
    query: str,
    *,
    limit: int,
    provider: str,
) -> list[WebSearchResult]:
    try:
        response = client.get(
            _GOOGLE_NEWS_RSS_URL,
            params={"q": query, "hl": "en-US", "gl": "US", "ceid": "US:en"},
            headers=_DDG_HEADERS,
            timeout=client.timeout,
            follow_redirects=True,
        )
    except httpx.HTTPError:
        return []
    if response.status_code >= 400:
        return []
    try:
        root = ET.fromstring(response.text)
    except ET.ParseError:
        return []
    results: list[WebSearchResult] = []
    for item in root.findall(".//item"):
        if len(results) >= limit:
            break
        title = _clean_text((item.findtext("title") or "").strip())
        url = (item.findtext("link") or "").strip()
        pub_date = _clean_text((item.findtext("pubDate") or "").strip())
        if not title or not url:
            continue
        snippet = f"Published: {pub_date}" if pub_date else ""
        results.append(
            WebSearchResult(
                title=title,
                url=url,
                snippet=snippet[:_MAX_SNIPPET_LENGTH],
                provider=provider,
            )
        )
    return results


def _parse_duckduckgo_html(content: str, *, limit: int, provider: str) -> list[WebSearchResult]:
    anchors = list(_ANCHOR_RE.finditer(content))
    snippets = list(_SNIPPET_RE.finditer(content))
    results: list[WebSearchResult] = []
    for index, match in enumerate(anchors):
        if len(results) >= limit:
            break
        title = _clean_text(match.group("title"))
        url = _normalize_url(html.unescape(match.group("href")))
        snippet_match = snippets[index] if index < len(snippets) else None
        snippet_html = ""
        if snippet_match:
            snippet_html = snippet_match.group("snippet") or snippet_match.group("div_snippet") or ""
        snippet = _clean_text(snippet_html)
        if not title or not url:
            continue
        results.append(
            WebSearchResult(
                title=title,
                url=url,
                snippet=snippet[:_MAX_SNIPPET_LENGTH].rstrip(),
                provider=provider,
            )
        )
    return results


def _clean_text(value: str) -> str:
    normalized = _TAG_RE.sub(" ", value or "")
    normalized = html.unescape(normalized)
    return " ".join(normalized.split())


def _normalize_url(value: str) -> str:
    parsed = urlparse(value)
    query = parse_qs(parsed.query)
    redirected = query.get("uddg")
    if redirected and redirected[0]:
        return html.unescape(redirected[0])
    if value.startswith("//"):
        return f"https:{value}"
    return value
