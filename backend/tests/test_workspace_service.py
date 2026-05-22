from pathlib import Path

from app.services.workspace_service import prepare_run_workspace


def test_prepare_run_workspace_ignores_runtime_workspaces(tmp_path: Path):
    source = tmp_path / "repo"
    source.mkdir()
    (source / "app.py").write_text("print('ok')\n", encoding="utf-8")
    archived = source / "runtime" / "workspaces" / "older-run"
    archived.mkdir(parents=True)
    (archived / "artifact.txt").write_text("ignore me\n", encoding="utf-8")
    legacy = source / "backend" / "workspaces" / "legacy-run"
    legacy.mkdir(parents=True)
    (legacy / "artifact.txt").write_text("ignore me too\n", encoding="utf-8")

    workspace = prepare_run_workspace(source, "self-hosted-run")

    assert (workspace / "app.py").exists()
    assert not (workspace / "runtime" / "workspaces").exists()
    assert not (workspace / "backend" / "workspaces").exists()
