"""Pipeline E2E matrix (M01–M20) in one session for stable DB."""

from __future__ import annotations

import os

import pytest

from app.core.enums import RunStatus
from app.services.orchestration_service import run_engine
from tests.fixtures.pipeline_matrix.cases import MATRIX_CASES
from tests.fixtures.pipeline_matrix.helpers import run_matrix_case


@pytest.fixture(autouse=True)
def _matrix_run_engine_idle():
    run_engine.wait_for_idle(timeout=10.0)
    yield
    run_engine.wait_for_idle(timeout=10.0)


@pytest.fixture()
def matrix_db(tmp_path):
    """Dedicated SQLite file per test so the matrix does not fight conftest teardown."""
    from sqlalchemy.orm import close_all_sessions

    from app.db.session import SessionLocal, engine, reconfigure_engine, run_migrations, seed_app_config
    from tests.conftest import TEST_DB_URL
    from tests.fixtures.pipeline_matrix.helpers import configure_matrix_settings

    db_path = tmp_path / "matrix_e2e.db"
    reconfigure_engine(f"sqlite:///{db_path}")
    run_migrations()
    db = SessionLocal()
    try:
        seed_app_config(db)
        configure_matrix_settings(db)
    finally:
        db.close()
    yield db_path
    run_engine.wait_for_idle(timeout=10.0)
    close_all_sessions()
    engine.dispose()
    reconfigure_engine(TEST_DB_URL)


def test_pipeline_e2e_matrix_all(tmp_path, monkeypatch, matrix_db):
    import app.services.orchestration_service as orch_mod
    from app.db.session import SessionLocal
    from app.services import setup_run_service
    from tests.fixtures.pipeline_matrix.helpers import configure_matrix_settings

    db = SessionLocal()
    try:
        configure_matrix_settings(db)
    finally:
        db.close()

    monkeypatch.setattr(setup_run_service, "has_completed_setup", lambda db, pid: True)
    monkeypatch.setattr(setup_run_service, "has_active_setup_run", lambda db, pid: False)
    monkeypatch.setattr(setup_run_service, "trigger_setup_run", lambda *a, **k: None)
    monkeypatch.setattr(orch_mod.run_engine, "enqueue", lambda run_id: orch_mod.run_engine._execute_run(run_id))
    monkeypatch.setattr(
        "app.services.setup_run_service.run_engine.enqueue",
        lambda run_id: orch_mod.run_engine._execute_run(run_id),
    )
    monkeypatch.setattr(orch_mod, "validate_command", lambda command: None)
    monkeypatch.setattr(orch_mod, "run_command", lambda command, workspace_path: (0, "ok", ""))
    monkeypatch.setattr(
        orch_mod,
        "execute_visual_checks",
        lambda *args, **kwargs: {"passed": True, "checks": [], "summary": "ok"},
    )
    monkeypatch.setattr(orch_mod, "integration_guard_issues", lambda *args, **kwargs: [])
    monkeypatch.setattr(orch_mod, "contract_guard_issues", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        orch_mod.OrchestrationService,
        "_finalize_deployment_gates",
        lambda self, db, run_id, workspace, source_root: True,
    )
    monkeypatch.setattr(
        orch_mod.OrchestrationService,
        "_verify_dependencies",
        lambda self, db, run_id, workspace, source: True,
    )
    monkeypatch.setattr(
        orch_mod.OrchestrationService,
        "_build_stage_tool_runtime",
        lambda self, db, run_id, stage: None,
    )
    monkeypatch.setattr(
        orch_mod.OrchestrationService,
        "_deterministic_review_issues",
        lambda self, *args, **kwargs: [],
    )
    monkeypatch.setattr(
        orch_mod.OrchestrationService,
        "_run_frontend_patch_check",
        lambda self, workspace, applied: None,
    )

    failures: list[str] = []
    csv_rows: list[str] = []
    for index, case in enumerate(MATRIX_CASES):
        repo = case.build_repo(tmp_path / f"run_{index}")
        result = run_matrix_case(
            repo_path=str(repo),
            description=case.description,
            task_kind=case.task_kind,
            validation_profile=case.validation_profile,
            architect_paths=case.architect_paths,
            playbook_approved=case.playbook_approved,
            debug_plan=case.debug_plan,
            approve_after=case.approve_after,
            resolve_clarification=case.resolve_clarification,
            monkeypatch=monkeypatch,
            setup_patches=False,
        )
        blocking = result.blocking_event or ""
        csv_rows.append(
            f"{case.scenario_id},{case.repo_mode},{case.task_kind},{result.terminal_status},{blocking}"
        )
        if result.terminal_status != case.expected_status:
            failures.append(
                f"{case.scenario_id}: expected {case.expected_status}, got {result.terminal_status} "
                f"(blocking={result.blocking_event})"
            )
        elif case.expected_status == RunStatus.AWAITING_APPROVAL.value and result.blocking_event:
            failures.append(f"{case.scenario_id}: unexpected blocking_event={result.blocking_event}")
        elif case.expected_status == RunStatus.BLOCKED.value and not result.blocking_event:
            failures.append(f"{case.scenario_id}: expected blocking event for blocked run")
    if os.environ.get("PIPELINE_MATRIX_CSV"):
        for row in csv_rows:
            print(row)
    assert not failures, "Matrix failures:\n" + "\n".join(failures)
