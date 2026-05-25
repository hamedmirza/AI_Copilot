"""Tests for workspace dev URL inference."""

from pathlib import Path

from app.services.workspace_dev_url import build_default_visual_checks, infer_dev_server_base, infer_routes_from_changed_files


def test_infer_dev_server_base_from_frontend_package_json(tmp_path):
    pkg = tmp_path / "frontend" / "package.json"
    pkg.parent.mkdir(parents=True)
    pkg.write_text('{"scripts":{"dev":"vite --port 5173"}}', encoding="utf-8")
    assert infer_dev_server_base(tmp_path) == "http://localhost:5173/"


def test_infer_routes_from_kanban_page():
    routes = infer_routes_from_changed_files(["frontend/src/pages/KanbanPage.tsx"])
    assert "/kanban" in routes


def test_build_default_visual_checks_uses_workspace_port(tmp_path):
    pkg = tmp_path / "frontend" / "package.json"
    pkg.parent.mkdir(parents=True)
    pkg.write_text('{"scripts":{"dev":"vite --port 4000"}}', encoding="utf-8")
    checks = build_default_visual_checks(tmp_path, ["frontend/src/pages/KanbanPage.tsx"])
    assert checks
    assert checks[0]["url"].startswith("http://localhost:4000")
