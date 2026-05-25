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


@pytest.fixture(autouse=True)
def _reset_backend_state():
    chat_orchestrator.wait_for_idle()
    run_engine.wait_for_idle()
    close_all_sessions()
    reconfigure_engine("sqlite:///:memory:")
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
    run_engine.wait_for_idle()
    registry = ProviderRegistry.get()
    registry.fake_provider = None
    registry.reload({})
    close_all_sessions()
    reconfigure_engine("sqlite:///:memory:")
    _remove_test_db_files()
    reconfigure_engine(TEST_DB_URL)


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
