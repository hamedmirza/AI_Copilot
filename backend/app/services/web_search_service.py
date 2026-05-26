from __future__ import annotations

import logging
from typing import Final

import httpx

from app.core.settings import get_settings
from app.services.web_search_providers import (
    KNOWN_PROVIDERS,
    WebSearchProvider,
    WebSearchResult,
    build_providers,
    parse_provider_names,
)

logger = logging.getLogger(__name__)

__all__ = [
    "KNOWN_PROVIDERS",
    "WebSearchError",
    "WebSearchResult",
    "WebSearchService",
    "infer_allow_web_search",
    "parse_provider_names",
]


class WebSearchError(RuntimeError):
    pass


class WebSearchService:
    def __init__(
        self,
        *,
        timeout_seconds: float | None = None,
        providers: list[WebSearchProvider] | None = None,
        provider_names: str | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        settings = get_settings()
        self.timeout_seconds = float(timeout_seconds or settings.web_search_timeout_seconds)
        self._client = client
        self._owns_client = client is None
        if providers is not None:
            self._providers = providers
        else:
            names = parse_provider_names(provider_names or settings.web_search_providers)
            self._providers = build_providers(
                names,
                google_api_key=settings.google_cse_api_key,
                google_cse_id=settings.google_cse_cx,
                github_token=settings.github_token,
            )

    def _get_client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(timeout=self.timeout_seconds)
        return self._client

    def close(self) -> None:
        if self._owns_client and self._client is not None:
            self._client.close()
            self._client = None

    def __enter__(self) -> "WebSearchService":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    @property
    def provider_names(self) -> tuple[str, ...]:
        return tuple(provider.name for provider in self._providers)

    def search(self, query: str, *, limit: int = 5) -> list[WebSearchResult]:
        normalized = " ".join(str(query or "").split())
        if not normalized:
            raise WebSearchError("Search query is required")
        if not self._providers:
            raise WebSearchError("No web search providers are configured")

        cap = max(1, min(limit, 8))
        per_provider = max(1, (cap + len(self._providers) - 1) // len(self._providers))
        merged: list[WebSearchResult] = []
        seen_urls: set[str] = set()
        errors: list[str] = []
        client = self._get_client()

        for provider in self._providers:
            try:
                batch = provider.search(client, normalized, limit=per_provider)
            except Exception as exc:
                message = f"{provider.name}: {exc}"
                errors.append(message)
                logger.warning("Web search provider failed: %s", message)
                continue
            for item in batch:
                if item.url in seen_urls:
                    continue
                seen_urls.add(item.url)
                merged.append(item)
                if len(merged) >= cap:
                    break
            if len(merged) >= cap:
                break

        if not merged and errors:
            raise WebSearchError("; ".join(errors))
        return merged[:cap]

    def build_context_block(self, query: str, *, limit: int = 5) -> str:
        results = self.search(query, limit=limit)
        if not results:
            return "Web search was enabled, but no public web results were found."
        lines = [
            "Web search findings (public internet, verify before relying on unstable details):",
            f"Providers: {', '.join(self.provider_names)}",
        ]
        for index, result in enumerate(results, start=1):
            lines.append(f"{index}. [{result.provider}] {result.title}")
            lines.append(f"   URL: {result.url}")
            if result.snippet:
                lines.append(f"   Note: {result.snippet}")
        return "\n".join(lines)

    def search_payload(self, query: str, *, limit: int = 5) -> dict[str, object]:
        normalized = " ".join(str(query or "").split())
        results = self.search(query, limit=limit)
        payload: dict[str, object] = {
            "query": normalized,
            "providers": list(self.provider_names),
            "results": [
                {
                    "title": item.title,
                    "url": item.url,
                    "snippet": item.snippet,
                    "provider": item.provider,
                }
                for item in results
            ],
        }
        if not results:
            payload["notice"] = (
                "No public web results were returned. The query may have been blocked by a provider, "
                "or optional providers (Google CSE, GitHub token) may be unconfigured."
            )
        return payload


_WEB_SEARCH_HINTS: Final[tuple[str, ...]] = (
    "web search",
    "web_search",
    "search provider",
    "search the web",
    "duckduckgo",
    "github.com",
    "google.com",
    "x.com",
)


def infer_allow_web_search(description: str, explicit: bool | None = None) -> bool:
    if explicit is not None:
        return bool(explicit)
    lower = str(description or "").lower()
    return any(marker in lower for marker in _WEB_SEARCH_HINTS)
