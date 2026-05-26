from __future__ import annotations

from unittest.mock import MagicMock

import httpx

from app.services.web_search_providers import (
    DuckDuckGoHtmlProvider,
    GitHubProvider,
    GoogleProvider,
    WebSearchResult,
    _parse_duckduckgo_html,
    build_providers,
    parse_provider_names,
)
from app.services.web_search_service import WebSearchService, infer_allow_web_search


def test_parse_provider_names_deduplicates_and_filters_unknown():
    assert parse_provider_names("duckduckgo,github,unknown,github") == ("duckduckgo", "github")
    assert parse_provider_names("") == ("duckduckgo", "github", "google", "x")


def test_infer_allow_web_search_from_description():
    assert infer_allow_web_search("Extend web search providers") is True
    assert infer_allow_web_search("Fix login bug") is False
    assert infer_allow_web_search("Fix login bug", explicit=True) is True
    assert infer_allow_web_search("Fix login bug", explicit=False) is False


def test_parse_duckduckgo_html_extracts_results():
    html = """
    <a class="result__a" href="https://duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com">Example</a>
    <a class="result__snippet">Example snippet text</a>
    """
    results = _parse_duckduckgo_html(html, limit=5, provider="duckduckgo")
    assert len(results) == 1
    assert results[0].title == "Example"
    assert results[0].url == "https://example.com"
    assert results[0].provider == "duckduckgo"


def test_web_search_service_merges_providers_and_dedupes_urls():
    class StubProvider:
        def __init__(self, name: str, results: list[WebSearchResult]) -> None:
            self.name = name
            self._results = results

        def search(self, client: httpx.Client, query: str, *, limit: int) -> list[WebSearchResult]:
            return self._results[:limit]

    service = WebSearchService(
        providers=[
            StubProvider(
                "duckduckgo",
                [WebSearchResult("A", "https://example.com/a", "one", "duckduckgo")],
            ),
            StubProvider(
                "github",
                [
                    WebSearchResult("B", "https://github.com/x", "two", "github"),
                    WebSearchResult("Dup", "https://example.com/a", "dup", "github"),
                ],
            ),
        ],
        client=MagicMock(),
    )

    results = service.search("providers", limit=5)
    assert [item.provider for item in results] == ["duckduckgo", "github"]
    payload = service.search_payload("providers", limit=5)
    assert payload["providers"] == ["duckduckgo", "github"]
    assert len(payload["results"]) == 2


def test_google_provider_uses_custom_search_when_configured():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "www.googleapis.com"
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "title": "Google doc",
                        "link": "https://developers.google.com/example",
                        "snippet": "Docs",
                    }
                ]
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = GoogleProvider(api_key="key", cse_id="cx")
    results = provider.search(client, "custom search", limit=3)
    client.close()
    assert results[0].provider == "google"
    assert results[0].url.startswith("https://developers.google.com/")


def test_github_provider_parses_api_results():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "api.github.com"
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "name": "web_search_service.py",
                        "path": "backend/app/services/web_search_service.py",
                        "html_url": "https://github.com/org/repo/blob/main/backend/app/services/web_search_service.py",
                        "repository": {"full_name": "org/repo", "html_url": "https://github.com/org/repo"},
                    }
                ]
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = GitHubProvider()
    results = provider.search(client, "web_search_service", limit=3)
    client.close()
    assert results[0].provider == "github"
    assert "org/repo" in results[0].title


def test_build_providers_respects_configured_names():
    providers = build_providers(("duckduckgo", "x"))
    assert [provider.name for provider in providers] == ["duckduckgo", "x"]


def test_duckduckgo_provider_uses_html_endpoint():
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["url"] = str(request.url)
        html = """
        <a class="result__a" href="https://duckduckgo.com/l/?uddg=https%3A%2F%2Fgithub.com%2Fa">GitHub hit</a>
        <a class="result__snippet">Snippet</a>
        """
        return httpx.Response(200, text=html)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    results = DuckDuckGoHtmlProvider().search(client, "python", limit=2)
    client.close()
    assert captured["method"] == "POST"
    assert "html.duckduckgo.com" in captured["url"]
    assert results[0].url == "https://github.com/a"


def test_duckduckgo_falls_back_to_get_when_post_returns_empty():
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.method)
        if request.method == "POST":
            return httpx.Response(202, text="<html><body>challenge</body></html>")
        html = """
        <a class="result__a" href="https://duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com">Hit</a>
        <a class="result__snippet">Snippet</a>
        """
        return httpx.Response(200, text=html)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    results = DuckDuckGoHtmlProvider().search(client, "fallback query", limit=2)
    client.close()
    assert calls == ["POST", "GET"]
    assert results[0].url == "https://example.com"
