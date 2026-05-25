from __future__ import annotations

import html
import re
from dataclasses import dataclass
from typing import Final
from urllib.parse import parse_qs, quote_plus, urlparse

import httpx

_DDG_SEARCH_URL: Final[str] = "https://html.duckduckgo.com/html/"
_USER_AGENT: Final[str] = "AI-Copilot/0.1 (+https://localhost)"
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


@dataclass
class WebSearchResult:
    title: str
    url: str
    snippet: str


class WebSearchError(RuntimeError):
    pass


class WebSearchService:
    def __init__(self, *, timeout_seconds: float = 12.0) -> None:
        self.timeout_seconds = timeout_seconds

    def search(self, query: str, *, limit: int = 5) -> list[WebSearchResult]:
        normalized = " ".join(str(query or "").split())
        if not normalized:
            raise WebSearchError("Search query is required")

        response = httpx.get(
            f"{_DDG_SEARCH_URL}?q={quote_plus(normalized)}",
            headers={"User-Agent": _USER_AGENT},
            timeout=self.timeout_seconds,
            follow_redirects=True,
        )
        response.raise_for_status()
        return self._parse_results(response.text, limit=max(1, min(limit, 8)))

    def build_context_block(self, query: str, *, limit: int = 5) -> str:
        results = self.search(query, limit=limit)
        if not results:
            return "Web search was enabled, but no public web results were found."
        lines = [
            "Web search findings (public internet, verify before relying on unstable details):",
        ]
        for index, result in enumerate(results, start=1):
            lines.append(f"{index}. {result.title}")
            lines.append(f"   URL: {result.url}")
            if result.snippet:
                lines.append(f"   Note: {result.snippet}")
        return "\n".join(lines)

    def search_payload(self, query: str, *, limit: int = 5) -> dict[str, object]:
        return {
            "query": " ".join(str(query or "").split()),
            "results": [
                {"title": item.title, "url": item.url, "snippet": item.snippet}
                for item in self.search(query, limit=limit)
            ],
        }

    def _parse_results(self, content: str, limit: int) -> list[WebSearchResult]:
        anchors = list(_ANCHOR_RE.finditer(content))
        snippets = list(_SNIPPET_RE.finditer(content))
        results: list[WebSearchResult] = []
        for index, match in enumerate(anchors):
            if len(results) >= limit:
                break
            title = self._clean_text(match.group("title"))
            url = self._normalize_url(html.unescape(match.group("href")))
            snippet_match = snippets[index] if index < len(snippets) else None
            snippet_html = ""
            if snippet_match:
                snippet_html = snippet_match.group("snippet") or snippet_match.group("div_snippet") or ""
            snippet = self._clean_text(snippet_html)
            if not title or not url:
                continue
            results.append(
                WebSearchResult(
                    title=title,
                    url=url,
                    snippet=snippet[:_MAX_SNIPPET_LENGTH].rstrip(),
                )
            )
        return results

    def _clean_text(self, value: str) -> str:
        normalized = _TAG_RE.sub(" ", value or "")
        normalized = html.unescape(normalized)
        return " ".join(normalized.split())

    def _normalize_url(self, value: str) -> str:
        parsed = urlparse(value)
        query = parse_qs(parsed.query)
        redirected = query.get("uddg")
        if redirected and redirected[0]:
            return html.unescape(redirected[0])
        if value.startswith("//"):
            return f"https:{value}"
        return value
