from pathlib import Path


def test_service_modules_are_wired_into_runtime():
    root = Path(__file__).resolve().parents[2]
    api_text = (root / "backend/app/api/routes/api.py").read_text(encoding="utf-8")
    orchestration_text = (root / "backend/app/services/orchestration_service.py").read_text(encoding="utf-8")

    assert "from app.services.learning_service import LearningService" in api_text
    assert "LearningService(" in api_text
    assert "from app.services.learning_service import LearningService" in (root / "backend/app/services/run_approval_service.py").read_text(encoding="utf-8")
    assert "approve_run_sync" in api_text
    assert "derive_run_display_name" in api_text
    assert "run_numbers_for_task" in api_text
    assert "get_cached_tree" in api_text
    assert "store_tree_cache" in api_text
    assert "invalidate_tree_cache" in api_text
    assert "LearningService(" in orchestration_text
    assert "lessons_applied" in orchestration_text
    assert "ReconnaissanceService" in orchestration_text
    assert "BaselineService" in orchestration_text
    assert "RepoHealthService" in orchestration_text
    assert "DependencyVerifierService" in orchestration_text
    assert "trigger_setup_run" in api_text
    assert "_stage_documentation" in orchestration_text
    assert "_stage_app_designer" in orchestration_text
