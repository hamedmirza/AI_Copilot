from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.main import app
from app.db.session import SessionLocal, run_migrations, seed_app_config
from app.providers.fake import FakeProvider
from app.providers.registry import ProviderRegistry


@pytest.fixture(scope="module")
def client():
    test_db = Path(__file__).resolve().parents[1] / "test_app.db"
    if test_db.exists():
        test_db.unlink()
    run_migrations()
    db = SessionLocal()
    seed_app_config(db)
    db.close()
    registry = ProviderRegistry.get()
    registry.fake_provider = FakeProvider()
    registry.reload({})
    with TestClient(app) as c:
        yield c
    registry.fake_provider = None
    if test_db.exists():
        test_db.unlink()


HEADERS = {"X-Api-Token": "dev-token"}


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_settings(client):
    r = client.get("/api/settings", headers=HEADERS)
    assert r.status_code == 200
    assert "lmstudio_base_url" in r.json()


def test_pick_directory(client, monkeypatch):
    monkeypatch.setattr(
        "app.tools.dialog_service.pick_directory",
        lambda **_: "/tmp/selected-project",
    )
    r = client.post("/api/dialog/pick-directory", json={}, headers=HEADERS)
    assert r.status_code == 200
    body = r.json()
    assert body["cancelled"] is False
    assert body["path"] == "/tmp/selected-project"

    monkeypatch.setattr(
        "app.tools.dialog_service.pick_directory",
        lambda **_: None,
    )
    r = client.post("/api/dialog/pick-directory", json={"prompt": "Pick one"}, headers=HEADERS)
    assert r.status_code == 200
    assert r.json() == {"cancelled": True, "path": None}


def test_path_traversal(client, tmp_path):
    # Create project
    proj_dir = tmp_path / "proj"
    proj_dir.mkdir()
    (proj_dir / "main.py").write_text("x=1\n")
    r = client.post(
        "/api/projects",
        json={
            "name": "Test",
            "source_repo_spec": str(proj_dir),
            "validation_profile": "python",
        },
        headers=HEADERS,
    )
    pid = r.json()["id"]
    # Use encoded traversal segments so the raw path contains ..
    r = client.put(
        f"/api/projects/{pid}/files/%2E%2E%2F%2E%2E%2F%2E%2E%2Fetc%2Fpasswd",
        json={"content": "hack"},
        headers=HEADERS,
    )
    assert r.status_code == 400


def test_project_update(client, tmp_path):
    proj_dir = tmp_path / "update_proj"
    proj_dir.mkdir()
    (proj_dir / "main.py").write_text("x=1\n")
    r = client.post(
        "/api/projects",
        json={
            "name": "UpdateTest",
            "source_repo_spec": str(proj_dir),
            "validation_profile": "python",
        },
        headers=HEADERS,
    )
    assert r.status_code == 200
    pid = r.json()["id"]

    new_dir = tmp_path / "updated_proj"
    new_dir.mkdir()
    r = client.put(
        f"/api/projects/{pid}",
        json={
            "name": "UpdatedName",
            "description": "Updated description",
            "source_repo_spec": str(new_dir),
            "validation_profile": "react",
        },
        headers=HEADERS,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "UpdatedName"
    assert body["description"] == "Updated description"
    assert body["validation_profile"] == "react"
    assert body["source_repo_spec"] == str(new_dir.resolve())


def test_file_rename(client, tmp_path):
    proj_dir = tmp_path / "rename_proj"
    proj_dir.mkdir()
    (proj_dir / "old.py").write_text("x=1\n")
    r = client.post(
        "/api/projects",
        json={
            "name": "RenameTest",
            "source_repo_spec": str(proj_dir),
            "validation_profile": "python",
        },
        headers=HEADERS,
    )
    pid = r.json()["id"]
    r = client.post(
        f"/api/projects/{pid}/files/old.py/rename",
        json={"new_path": "new.py"},
        headers=HEADERS,
    )
    assert r.status_code == 200
    assert r.json()["path"] == "new.py"
    tree = client.get(f"/api/projects/{pid}/tree", headers=HEADERS).json()
    paths = [i["path"] for i in tree["items"]]
    assert "new.py" in paths
    assert "old.py" not in paths


def test_git_status_empty_repo(client, tmp_path):
    proj_dir = tmp_path / "git_proj"
    proj_dir.mkdir()
    (proj_dir / "main.py").write_text("x=1\n")
    r = client.post(
        "/api/projects",
        json={
            "name": "GitTest",
            "source_repo_spec": str(proj_dir),
            "validation_profile": "python",
        },
        headers=HEADERS,
    )
    assert r.status_code == 200
    pid = r.json()["id"]
    r = client.get(f"/api/projects/{pid}/git/status", headers=HEADERS)
    assert r.status_code == 200
    body = r.json()
    assert "staged" in body
    assert "unstaged" in body
    assert "untracked" in body
    assert any(f["path"] == "main.py" for f in body["untracked"])
