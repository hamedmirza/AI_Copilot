from __future__ import annotations

import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest

from app.services.browser_preview_service import BrowserPreviewError, BrowserPreviewResult, BrowserPreviewService

from .test_api import HEADERS


def _mock_service(handler) -> BrowserPreviewService:
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return BrowserPreviewService(client=client)


@pytest.fixture()
def loopback_html_server():
    html = (
        b"<!doctype html><html><head></head>"
        b'<body><div id="app">Live preview</div></body></html>'
    )

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(html)

        def log_message(self, format: str, *args) -> None:
            return

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}/"
    finally:
        server.shutdown()
        thread.join(timeout=2)


def _create_preview_project(client, tmp_path):
    project_dir = tmp_path / "preview-project"
    project_dir.mkdir()
    response = client.post(
        "/api/projects",
        json={
            "name": "PreviewProject",
            "source_repo_spec": str(project_dir),
            "validation_profile": "react",
        },
        headers=HEADERS,
    )
    return response.json()["id"]


def test_browser_preview_service_rejects_non_loopback_hosts():
    service = _mock_service(lambda request: httpx.Response(200, request=request, text="ok"))

    with pytest.raises(BrowserPreviewError, match="loopback"):
        service.fetch_preview("https://example.com/app")


def test_browser_preview_service_rejects_external_redirects():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, request=request, headers={"location": "https://example.com/redirected"})

    service = _mock_service(handler)

    with pytest.raises(BrowserPreviewError, match="loopback"):
        service.fetch_preview("http://127.0.0.1:3000/")


def test_browser_preview_service_injects_bridge_and_rewrites_root_assets():
    html = """
    <!doctype html>
    <html>
      <head>
        <script type="module" src="/src/main.tsx"></script>
        <link rel="stylesheet" href="/src/index.css">
      </head>
      <body>
        <div id="root">Preview</div>
      </body>
    </html>
    """

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, request=request, text=html, headers={"content-type": "text/html; charset=utf-8"})

    service = _mock_service(handler)
    result = service.fetch_preview("http://127.0.0.1:3000/demo")
    body = result.body.decode("utf-8")

    assert result.content_type == "text/html; charset=utf-8"
    assert 'window.__AI_COPILOT_PICKER_SOURCE_URL__ = "http://127.0.0.1:3000/demo";' in body
    assert 'src="http://127.0.0.1:3000/src/main.tsx"' in body
    assert 'href="http://127.0.0.1:3000/src/index.css"' in body
    assert "COPILOT_PICKER_BRIDGE_READY" in body


def test_browser_preview_route_requires_token_and_returns_html(client, monkeypatch, tmp_path):
    project_id = _create_preview_project(client, tmp_path)

    monkeypatch.setattr(
        "app.api.routes.api.BrowserPreviewService.fetch_preview",
        lambda self, url: BrowserPreviewResult(
            body=b"<html><body>proxied</body></html>",
            content_type="text/html; charset=utf-8",
            status_code=200,
        ),
    )

    unauthorized = client.get(
        f"/api/browser/preview?url=http://127.0.0.1:3000/&project_id={project_id}",
        headers={"X-Api-Token": "wrong-token"},
    )
    assert unauthorized.status_code == 401

    query_auth = client.get(
        f"/api/browser/preview?url=http://127.0.0.1:3000/&project_id={project_id}&token=dev-token",
    )
    assert query_auth.status_code == 200
    assert "proxied" in query_auth.text

    response = client.get(
        f"/api/browser/preview?url=http://127.0.0.1:3000/&project_id={project_id}",
        headers=HEADERS,
    )
    assert response.status_code == 200
    assert "proxied" in response.text


def test_browser_preview_live_proxy_injects_bridge(client, loopback_html_server, tmp_path):
    project_id = _create_preview_project(client, tmp_path)
    preview_url = loopback_html_server

    response = client.get(
        f"/api/browser/preview?url={preview_url}&project_id={project_id}",
        headers=HEADERS,
    )
    assert response.status_code == 200
    assert "Live preview" in response.text
    assert "__AI_COPILOT_PICKER_SOURCE_URL__" in response.text
    assert "COPILOT_PICKER_BRIDGE_READY" in response.text


def test_browser_preview_dead_port_returns_error(client, tmp_path):
    project_id = _create_preview_project(client, tmp_path)

    response = client.get(
        f"/api/browser/preview?url=http://127.0.0.1:5999/&project_id={project_id}",
        headers=HEADERS,
    )
    assert response.status_code == 400
    assert "Could not reach dev server" in response.text


def test_browser_preview_service_unreachable_host():
    service = BrowserPreviewService()

    with pytest.raises(BrowserPreviewError, match="Could not reach dev server"):
        service.fetch_preview("http://127.0.0.1:5999/")
