import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import close_all_sessions

# Isolate API tests from production app.db (engine binds at import time).
os.environ["DB_URL"] = "sqlite:///./backend/test_app.db"

from app.api.main import app
from app.db.session import SessionLocal, reconfigure_engine, run_migrations, seed_app_config
from app.providers.fake import FakeProvider
from app.providers.registry import ProviderRegistry
from app.services.chat_orchestrator import chat_orchestrator
from app.services.orchestration_service import run_engine

TEST_DB = Path(__file__).resolve().parents[1] / "test_app.db"
TEST_DB_URL = f"sqlite:///{TEST_DB}"


def _remove_test_db_files() -> None:
    for suffix in ("", "-wal", "-shm"):
        candidate = Path(f"{TEST_DB}{suffix}")
        if candidate.exists():
            candidate.unlink()


def seed_pipeline_gate_artifacts(db, run_id: str) -> None:
    """Minimal artifacts so stage-gate checks pass when stages are stubbed."""
    import json

    from app.db.models import ArtifactModel

    payloads = {
        "plan": {
            "summary": "test",
            "steps": [
                {
                    "step_id": "1",
                    "title": "Step",
                    "description": "Work",
                    "acceptance_criteria": ["done"],
                }
            ],
            "risks": [],
        },
        "architect": {
            "overview": "test",
            "modules": [],
            "file_changes": [{"path": "app.py", "action": "modify", "rationale": "test"}],
            "dependencies": [],
        },
        "coder": {"summary": "test", "file_changes": []},
    }
    for artifact_type, content in payloads.items():
        db.add(
            ArtifactModel(
                run_id=run_id,
                artifact_type=artifact_type,
                content_json=json.dumps(content),
            )
        )
    db.commit()


@pytest.fixture(autouse=True)
def _reset_backend_state():
    chat_orchestrator.wait_for_idle()
    run_engine.wait_for_idle()
    close_all_sessions()
    from app.db.session import engine as db_engine

    db_engine.dispose()
    _remove_test_db_files()
    reconfigure_engine(TEST_DB_URL)
    run_migrations()
    db = SessionLocal()
    try:
        seed_app_config(db)
    finally:
        db.close()
    yield
    chat_orchestrator.wait_for_idle()
    run_engine.wait_for_idle(timeout=30)
    registry = ProviderRegistry.get()
    registry.fake_provider = None
    registry.reload({})
    close_all_sessions()
    from app.db.session import engine as db_engine

    db_engine.dispose()
    _remove_test_db_files()
    reconfigure_engine(TEST_DB_URL)
    run_migrations()


@pytest.fixture()
def client():
    registry = ProviderRegistry.get()
    registry.fake_provider = FakeProvider(
        default_response='{"content":"Fake assistant reply","tool_calls":[],"finish_reason":"stop"}'
    )
    registry.reload({})
    with TestClient(app) as test_client:
        yield test_client
    chat_orchestrator.wait_for_idle()
    run_engine.wait_for_idle()
