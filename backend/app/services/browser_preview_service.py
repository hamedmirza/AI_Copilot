from __future__ import annotations

import html
import json
import ipaddress
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx


_REDIRECT_STATUS_CODES = {301, 302, 303, 307, 308}
_MAX_REDIRECTS = 5
_ROOT_ASSET_ATTR_RE = re.compile(r'(?P<prefix>\b(?:src|href)=["\'])/(?P<path>[^"\']*)', re.IGNORECASE)


class BrowserPreviewError(ValueError):
    """Raised when a preview URL is not safe or cannot be proxied."""


@dataclass(frozen=True)
class BrowserPreviewResult:
    body: bytes
    content_type: str
    status_code: int


class BrowserPreviewService:
    def __init__(self, client: httpx.Client | None = None) -> None:
        self._client = client or httpx.Client(timeout=httpx.Timeout(connect=2.0, read=10.0, write=10.0, pool=2.0))

    def fetch_preview(self, raw_url: str) -> BrowserPreviewResult:
        current_url = self._normalize_loopback_url(raw_url)
        response: httpx.Response | None = None

        for _ in range(_MAX_REDIRECTS + 1):
            try:
                response = self._client.get(
                    current_url,
                    follow_redirects=False,
                    headers={"Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8"},
                )
            except httpx.RequestError as exc:
                raise BrowserPreviewError(f"Could not reach dev server: {exc}") from exc
            if response.status_code not in _REDIRECT_STATUS_CODES:
                break
            location = response.headers.get("location")
            if not location:
                break
            current_url = self._normalize_loopback_url(urljoin(current_url, location))
        else:
            raise BrowserPreviewError("Preview URL redirected too many times")

        if response is None:
            raise BrowserPreviewError("Preview request did not return a response")

        content_type = response.headers.get("content-type", "text/plain; charset=utf-8")
        if self._is_html_response(content_type, response.content):
            html_text = response.content.decode(response.encoding or "utf-8", errors="replace")
            injected = self._inject_bridge(html_text, current_url)
            return BrowserPreviewResult(
                body=injected.encode("utf-8"),
                content_type="text/html; charset=utf-8",
                status_code=response.status_code,
            )

        return BrowserPreviewResult(
            body=response.content,
            content_type=content_type,
            status_code=response.status_code,
        )

    def _normalize_loopback_url(self, raw_url: str) -> str:
        parsed = urlparse((raw_url or "").strip())
        if parsed.scheme not in {"http", "https"}:
            raise BrowserPreviewError("Preview URL must use http or https")
        if not parsed.hostname:
            raise BrowserPreviewError("Preview URL must include a hostname")
        if parsed.username or parsed.password:
            raise BrowserPreviewError("Preview URL cannot include credentials")
        if not self._is_loopback_host(parsed.hostname):
            raise BrowserPreviewError("Preview URL must target localhost or a loopback address")
        return parsed.geturl()

    @staticmethod
    def _is_loopback_host(hostname: str) -> bool:
        normalized = hostname.strip().lower()
        if normalized == "localhost":
            return True
        try:
            return ipaddress.ip_address(normalized).is_loopback
        except ValueError:
            return False

    @staticmethod
    def _is_html_response(content_type: str, content: bytes) -> bool:
        lowered = (content_type or "").lower()
        if "text/html" in lowered or "application/xhtml+xml" in lowered:
            return True
        snippet = content[:256].decode("utf-8", errors="ignore").lstrip().lower()
        return snippet.startswith("<!doctype html") or snippet.startswith("<html")

    def _inject_bridge(self, html_text: str, target_url: str) -> str:
        base_href = self._document_base_href(target_url)
        bridge_script = self._bridge_script_source().replace("</script", "<\\/script")
        bootstrap = (
            f'<base href="{html.escape(base_href, quote=True)}">'
            f"<script>window.__AI_COPILOT_PICKER_SOURCE_URL__ = {json.dumps(target_url)};</script>"
            f"<script>{bridge_script}</script>"
        )
        rewritten = self._rewrite_root_asset_urls(html_text, target_url)

        head_index = rewritten.lower().find("</head>")
        if head_index != -1:
            return f"{rewritten[:head_index]}{bootstrap}{rewritten[head_index:]}"

        body_index = rewritten.lower().find("<body")
        if body_index != -1:
            return f"{rewritten[:body_index]}<head>{bootstrap}</head>{rewritten[body_index:]}"

        return f"<head>{bootstrap}</head>{rewritten}"

    def _rewrite_root_asset_urls(self, html_text: str, target_url: str) -> str:
        parsed = urlparse(target_url)
        target_origin = f"{parsed.scheme}://{parsed.netloc}"
        return _ROOT_ASSET_ATTR_RE.sub(lambda match: f'{match.group("prefix")}{target_origin}/{match.group("path")}', html_text)

    @staticmethod
    def _document_base_href(target_url: str) -> str:
        parsed = urlparse(target_url)
        path = parsed.path or "/"
        if path.endswith("/"):
            base_path = path
        else:
            base_path = f"{path.rsplit('/', 1)[0]}/" if "/" in path else "/"
        return f"{parsed.scheme}://{parsed.netloc}{base_path}"

    @staticmethod
    def _bridge_script_source() -> str:
        path = Path(__file__).resolve().parents[3] / "frontend" / "public" / "copilot-picker-bridge.js"
        return path.read_text(encoding="utf-8")
