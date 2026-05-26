from app.services.run_observability_service import (
    RunOutcomeClass,
    enrich_event_payload,
    why_blocked_from_context,
)


def test_enrich_blocked_event_adds_outcome_and_why_blocked():
    payload = enrich_event_payload(
        "run_blocked",
        "tester",
        "error",
        {"blocking": ["Integration: App.tsx not wired", "Ruff failed"]},
        message="deployment gates failed",
    )
    assert payload["outcome_class"] == RunOutcomeClass.BLOCKED.value
    assert "Integration" in payload["why_blocked"]


def test_enrich_satisfied_noop_event():
    payload = enrich_event_payload(
        "coder_noop_blueprint_satisfied",
        "coder",
        "info",
        {"paths": ["app/foo.py"]},
        message="Blueprint files already exist",
    )
    assert payload["outcome_class"] == RunOutcomeClass.SATISFIED.value
    assert "why_blocked" not in payload


def test_why_blocked_from_block_recorded():
    text = why_blocked_from_context(
        "block_recorded",
        "coder",
        "Protected path touched",
        {"block_type": "protected_path", "source": "change_guard"},
    )
    assert "Protected Path" in text
    assert "Protected path touched" in text
