from app.services.run_truth_service import (
    description_implies_frontend_ui,
    infer_deliverable_kind,
    should_run_ui_designer,
)


def test_description_implies_frontend_ui_detects_ui_wording():
    assert description_implies_frontend_ui("Build a super professional UI for the app")
    assert not description_implies_frontend_ui("Build a REST API for batch exports")


def test_infer_deliverable_kind_matches_ui_tokens():
    assert infer_deliverable_kind("Dashboard for billing", None) == "frontend"


def test_should_run_ui_designer_for_frontend_deliverable():
    assert should_run_ui_designer(
        "Professional UI with modular sections",
        "implementation",
        deliverable_kind="frontend",
    )


def test_should_run_ui_designer_for_mixed_with_ui_cues():
    assert should_run_ui_designer(
        "Add API routes and a dashboard screen",
        "mixed",
        deliverable_kind="mixed",
    )


def test_should_run_ui_designer_false_for_backend_only():
    assert not should_run_ui_designer(
        "Add REST API endpoints and database migrations",
        "implementation",
        deliverable_kind="backend",
    )


def test_should_run_ui_designer_false_for_analysis():
    assert not should_run_ui_designer("Write a summary report", "analysis", deliverable_kind="report")
