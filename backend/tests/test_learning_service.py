import json

from app.core.enums import RunStatus
from app.db.models import (
    AppConfigModel,
    ArtifactModel,
    ImprovementModel,
    LessonModel,
    ProjectModel,
    RunModel,
    TaskModel,
)
from app.db.session import SessionLocal
from app.services.learning_service import LearningService


def _set_config(db, key: str, value: object) -> None:
    row = db.query(AppConfigModel).filter(AppConfigModel.key == key).first()
    assert row is not None
    row.value = str(value)
    db.commit()


def _seed_project(db, tmp_path, name: str) -> ProjectModel:
    workspace = tmp_path / name
    workspace.mkdir()
    project = ProjectModel(
        name=name,
        source_repo_spec=str(workspace),
        validation_profile="python",
        protected_files_json="[]",
    )
    db.add(project)
    db.flush()
    return project


def _seed_run(
    db,
    *,
    project: ProjectModel,
    status: str,
    description: str = "Implement feature",
    stage: str = "tester",
    error_message: str | None = None,
) -> RunModel:
    task = TaskModel(project_id=project.id, description=description, validation_profile="python")
    db.add(task)
    db.flush()
    run = RunModel(
        project_id=project.id,
        task_id=task.id,
        status=status,
        current_stage=stage,
        error_message=error_message,
        workspace_path=project.source_repo_spec,
    )
    db.add(run)
    db.commit()
    return run


def _add_artifacts(db, run_id: str, artifact_types: list[str]) -> None:
    for artifact_type in artifact_types:
        db.add(
            ArtifactModel(
                run_id=run_id,
                artifact_type=artifact_type,
                content_json=json.dumps({"ok": True}),
            )
        )
    db.commit()


def test_unknown_failure_stays_candidate(tmp_path):
    db = SessionLocal()
    try:
        project = _seed_project(db, tmp_path, "UnknownCandidate")
        run = _seed_run(
            db,
            project=project,
            status="failed",
            description="Investigate flaky error",
            stage="reviewer",
            error_message="Some opaque failure",
        )

        LearningService(db).finalize_terminal_run(run.id)

        improvement = db.query(ImprovementModel).filter(ImprovementModel.source_run_id == run.id).first()
        assert improvement is not None
        assert improvement.status == "candidate"
        assert improvement.failure_class == "unknown"
    finally:
        db.close()


def test_json_decode_error_classifies_as_schema_contract(tmp_path):
    db = SessionLocal()
    try:
        project = _seed_project(db, tmp_path, "JsonSchemaFailure")
        run = _seed_run(
            db,
            project=project,
            status="failed",
            description="Verify resume UI output",
            stage="reviewer",
            error_message="Expecting ',' delimiter: line 15 column 163 (char 688)",
        )

        LearningService(db).finalize_terminal_run(run.id)
        db.refresh(run)

        assert run.failure_class == "schema_contract"
        assert run.failure_subclass == "invalid_json"
        assert run.primary_failure_class == "schema_contract"
    finally:
        db.close()


def test_trial_exposure_auto_promotes_after_successful_run(tmp_path):
    db = SessionLocal()
    try:
        _set_config(db, "learning_min_trial_runs", 1)
        project = _seed_project(db, tmp_path, "TrialPromote")

        baseline_run = _seed_run(
            db,
            project=project,
            status="failed",
            description="Fix frontend validation bug",
            stage="tester",
            error_message="Validation failed",
        )
        learner = LearningService(db)
        learner.finalize_terminal_run(baseline_run.id)

        source_run = _seed_run(
            db,
            project=project,
            status="blocked",
            description="Fix frontend validation bug",
            stage="tester",
            error_message="Validation failed",
        )
        learner.finalize_terminal_run(source_run.id)

        improvement = db.query(ImprovementModel).filter(ImprovementModel.source_run_id == source_run.id).first()
        assert improvement is not None
        assert improvement.status == "trialing"

        trial_run = _seed_run(
            db,
            project=project,
            status="running",
            description="Fix frontend validation bug",
            stage="tester",
        )

        context = learner.build_learning_context(trial_run, "tester", "Task context")
        assert any(item["id"] == improvement.id for item in context["project_lessons"])

        trial_run.status = "completed"
        db.commit()
        learner.finalize_terminal_run(trial_run.id)

        db.refresh(improvement)
        assert improvement.status == "approved"
    finally:
        db.close()


def test_ensure_run_learning_state_backfills_terminal_outcomes(tmp_path):
    db = SessionLocal()
    try:
        project = _seed_project(db, tmp_path, "OutcomeBackfill")
        run = _seed_run(
            db,
            project=project,
            status=RunStatus.COMPLETED.value,
            description="Implement dashboard",
            stage="tester",
        )
        db.refresh(run)
        run.terminal_success = None
        run.terminal_status = None
        db.commit()

        LearningService(db).ensure_run_learning_state(run)
        db.refresh(run)

        assert run.terminal_success is True
        assert run.terminal_status == RunStatus.COMPLETED.value
        assert run.approval_reached is True
    finally:
        db.close()


def test_awaiting_approval_skips_lesson_upsert(tmp_path):
    db = SessionLocal()
    try:
        project = _seed_project(db, tmp_path, "AwaitingApproval")
        run = _seed_run(db, project=project, status=RunStatus.AWAITING_APPROVAL.value, stage="tester")

        LearningService(db).finalize_terminal_run(run.id)

        assert db.query(LessonModel).filter(LessonModel.run_id == run.id).count() == 0
        assert db.query(ImprovementModel).filter(ImprovementModel.source_run_id == run.id).count() == 0
    finally:
        db.close()


def test_auto_promote_only_on_completed(tmp_path):
    db = SessionLocal()
    try:
        project = _seed_project(db, tmp_path, "CompletedOnly")
        awaiting = _seed_run(db, project=project, status=RunStatus.AWAITING_APPROVAL.value, stage="tester")
        _add_artifacts(db, awaiting.id, ["plan", "coder", "review_summary"])

        learner = LearningService(db)
        learner.finalize_terminal_run(awaiting.id)
        assert (
            db.query(ImprovementModel)
            .filter(ImprovementModel.scope == "global", ImprovementModel.status == "approved")
            .count()
            == 0
        )

        completed = _seed_run(db, project=project, status=RunStatus.COMPLETED.value, stage="tester")
        _add_artifacts(db, completed.id, ["plan", "architect", "coder", "review_summary", "test_plan"])
        learner.finalize_terminal_run(completed.id)

        global_skill = (
            db.query(ImprovementModel)
            .filter(
                ImprovementModel.source_run_id == completed.id,
                ImprovementModel.scope == "global",
                ImprovementModel.status == "approved",
            )
            .first()
        )
        assert global_skill is not None
        assert set(global_skill.stages) >= {"planner", "architect", "coder", "reviewer", "tester"}
    finally:
        db.close()


def test_auto_promote_respects_disabled_setting(tmp_path):
    db = SessionLocal()
    try:
        _set_config(db, "learning_auto_promote_enabled", False)
        project = _seed_project(db, tmp_path, "AutoPromoteDisabled")
        run = _seed_run(db, project=project, status=RunStatus.COMPLETED.value, stage="tester")
        _add_artifacts(db, run.id, ["plan", "coder"])

        LearningService(db).finalize_terminal_run(run.id)

        assert (
            db.query(ImprovementModel)
            .filter(ImprovementModel.source_run_id == run.id, ImprovementModel.scope == "global")
            .count()
            == 0
        )
    finally:
        db.close()


def test_failure_auto_promote_requires_min_trial_runs(tmp_path):
    db = SessionLocal()
    try:
        _set_config(db, "learning_min_trial_runs", 3)
        _set_config(db, "learning_auto_promote_enabled", True)
        project = _seed_project(db, tmp_path, "FailureTrials")
        learner = LearningService(db)
        description = "Validation failure shared"

        signature = None
        for _ in range(2):
            run = _seed_run(
                db,
                project=project,
                status="failed",
                description=description,
                stage="tester",
                error_message="Validation failed",
            )
            learner.finalize_terminal_run(run.id)
            db.refresh(run)
            signature = run.failure_signature

        completed = _seed_run(
            db,
            project=project,
            status=RunStatus.COMPLETED.value,
            description=description,
            stage="tester",
        )
        learner.finalize_terminal_run(completed.id)
        lesson = db.query(LessonModel).filter(LessonModel.run_id == completed.id).one()
        parsed = json.loads(lesson.content)
        parsed["kind"] = "failure_avoidance"
        parsed["confidence"] = 0.9
        parsed["failure_signature"] = signature
        parsed["failure_class"] = "validation_profile"
        parsed["stages"] = ["tester"]
        lesson.content = json.dumps(parsed)
        db.commit()

        assert learner.auto_promote_lesson_if_eligible(lesson, completed) is None
    finally:
        db.close()


def test_failure_auto_promote_after_enough_matching_failures(tmp_path):
    db = SessionLocal()
    try:
        _set_config(db, "learning_min_trial_runs", 2)
        _set_config(db, "learning_auto_promote_enabled", True)
        project = _seed_project(db, tmp_path, "FailurePromote")
        learner = LearningService(db)
        description = "Fix frontend validation bug"

        first = _seed_run(
            db,
            project=project,
            status="failed",
            description=description,
            stage="tester",
            error_message="Validation failed",
        )
        learner.finalize_terminal_run(first.id)
        signature = first.failure_signature
        assert signature

        second = _seed_run(
            db,
            project=project,
            status="failed",
            description=description,
            stage="tester",
            error_message="Validation failed",
        )
        db.refresh(second)
        second.failure_signature = signature
        db.commit()
        learner.finalize_terminal_run(second.id)

        lesson = db.query(LessonModel).filter(LessonModel.run_id == second.id).first()
        assert lesson is not None
        parsed = json.loads(lesson.content)
        parsed["kind"] = "failure_avoidance"
        parsed["confidence"] = 0.9
        parsed["failure_signature"] = signature
        parsed["failure_class"] = "validation_profile"
        parsed["stages"] = ["tester"]
        lesson.content = json.dumps(parsed)
        db.commit()

        _set_config(db, "learning_auto_promote_enabled", False)
        completed = _seed_run(
            db,
            project=project,
            status=RunStatus.COMPLETED.value,
            description=description,
            stage="tester",
        )
        learner.finalize_terminal_run(completed.id)
        _set_config(db, "learning_auto_promote_enabled", True)
        completed_lesson = db.query(LessonModel).filter(LessonModel.run_id == completed.id).first()
        assert completed_lesson is not None
        completed_parsed = json.loads(completed_lesson.content)
        completed_parsed["kind"] = "failure_avoidance"
        completed_parsed["confidence"] = 0.9
        completed_parsed["failure_signature"] = signature
        completed_parsed["failure_class"] = "validation_profile"
        completed_parsed["stages"] = ["tester"]
        completed_lesson.content = json.dumps(completed_parsed)
        db.commit()

        promoted = learner.auto_promote_lesson_if_eligible(completed_lesson, completed)
        assert promoted is not None
        assert promoted["scope"] == "global"
        assert promoted["status"] == "approved"
    finally:
        db.close()


def test_auto_promote_dedup_by_source_lesson_and_trigger(tmp_path):
    db = SessionLocal()
    try:
        project = _seed_project(db, tmp_path, "DedupPromote")
        run = _seed_run(db, project=project, status=RunStatus.COMPLETED.value, stage="tester")
        _add_artifacts(db, run.id, ["plan", "coder"])
        learner = LearningService(db)
        learner.finalize_terminal_run(run.id)

        lesson = db.query(LessonModel).filter(LessonModel.run_id == run.id).one()
        assert (
            db.query(ImprovementModel)
            .filter(ImprovementModel.source_lesson_id == lesson.id, ImprovementModel.scope == "global")
            .count()
            == 1
        )
        second = learner.auto_promote_lesson_if_eligible(lesson, run)
        assert second is None

        duplicate = _seed_run(db, project=project, status=RunStatus.COMPLETED.value, stage="tester")
        _add_artifacts(db, duplicate.id, ["plan", "coder"])
        learner.finalize_terminal_run(duplicate.id)
        global_count = (
            db.query(ImprovementModel)
            .filter(
                ImprovementModel.scope == "global",
                ImprovementModel.status == "approved",
                ImprovementModel.title == lesson.title,
            )
            .count()
        )
        assert global_count == 1
    finally:
        db.close()


def test_derive_stages_from_artifacts_maps_types(tmp_path):
    db = SessionLocal()
    try:
        project = _seed_project(db, tmp_path, "ArtifactStages")
        run = _seed_run(db, project=project, status="running", stage="none")
        _add_artifacts(
            db,
            run.id,
            [
                "plan",
                "architect",
                "ui_design",
                "coder",
                "review_summary",
                "review_notes",
                "test_plan",
                "unknown_type",
            ],
        )

        stages = LearningService(db)._derive_stages_from_artifacts(run.id)

        assert stages == ["planner", "architect", "ui_designer", "coder", "reviewer", "tester"]
    finally:
        db.close()


def test_derive_stages_from_artifacts_includes_post_deploy_supervisor(tmp_path):
    db = SessionLocal()
    try:
        project = _seed_project(db, tmp_path, "SupervisorStage")
        run = _seed_run(db, project=project, status=RunStatus.COMPLETED.value, stage="supervisor")
        _add_artifacts(db, run.id, ["plan", "coder", "test_plan", "supervisor"])

        stages = LearningService(db)._derive_stages_from_artifacts(run.id)

        assert stages == ["planner", "coder", "tester", "supervisor"]
    finally:
        db.close()


def test_build_learning_context_scoring_basics(tmp_path):
    db = SessionLocal()
    try:
        project = _seed_project(db, tmp_path, "ContextScoring")
        run = _seed_run(db, project=project, status="running", description="Implement dashboard", stage="coder")
        learner = LearningService(db)

        signature_match = ImprovementModel(
            project_id=project.id,
            source_run_id=run.id,
            title="Signature match",
            status="approved",
            scope="project",
            kind="repo_convention",
            hypothesis="Signature match",
            task_kind="implementation",
            comparable_task_signature="implement-dashboard",
            cohort_key=f"{project.id}:implementation:implement-dashboard:planner",
            confidence=0.7,
            machine_guidance_json=json.dumps(
                {"summary": "Matched task", "guidance": "Follow matched signature"},
                ensure_ascii=True,
            ),
            stages_json=json.dumps(["planner"]),
            tags_json=json.dumps(["implementation"]),
            decision_metadata_json=json.dumps({"trigger_pattern": "sig-a"}, ensure_ascii=True),
        )
        signature_miss = ImprovementModel(
            project_id=project.id,
            source_run_id=run.id,
            title="Signature miss",
            status="approved",
            scope="project",
            kind="repo_convention",
            hypothesis="Signature miss",
            task_kind="implementation",
            comparable_task_signature="",
            cohort_key=f"{project.id}:implementation:general-task:planner",
            confidence=0.7,
            machine_guidance_json=json.dumps(
                {"summary": "Other task", "guidance": "Different signature"},
                ensure_ascii=True,
            ),
            stages_json=json.dumps(["planner"]),
            tags_json=json.dumps(["implementation"]),
            decision_metadata_json=json.dumps({"trigger_pattern": "sig-b"}, ensure_ascii=True),
        )
        db.add(signature_match)
        db.add(signature_miss)
        db.commit()

        planner_context = learner.build_learning_context(run, "planner", "Base context")
        match_score = next(
            item["score"] for item in planner_context["project_lessons"] if item["title"] == "Signature match"
        )
        miss_score = next(
            item["score"] for item in planner_context["project_lessons"] if item["title"] == "Signature miss"
        )
        assert match_score > miss_score
    finally:
        db.close()


def test_record_and_retire_block_creates_lesson(tmp_path):
    db = SessionLocal()
    try:
        project = _seed_project(db, tmp_path, "BlockRecord")
        run = _seed_run(db, project=project, status="running", stage="coder")
        learner = LearningService(db)

        signature = learner.record_block(
            run.id,
            block_type="structural_guard",
            stage="coder",
            source="change_guard",
            message="Structural regression in foo.py",
            guidance="Use line_changes and preserve exports.",
            target_stages=["coder"],
        )
        assert signature

        retired = learner.retire_block_on_resolution(run.id, signature, resolved_by_stage="coder")
        assert retired is not None
        assert retired["guidance"]

        lesson = db.query(LessonModel).filter(LessonModel.run_id == run.id).first()
        improvement = db.query(ImprovementModel).filter(ImprovementModel.source_run_id == run.id).first()
        assert lesson is not None
        assert improvement is not None

        context = learner.build_learning_context(run, "coder", "Task context")
        assert "Resolved blocks to avoid" in context["context"]
    finally:
        db.close()


def test_retire_and_finalize_do_not_duplicate_block_lessons(tmp_path):
    db = SessionLocal()
    try:
        project = _seed_project(db, tmp_path, "BlockDedupe")
        run = _seed_run(db, project=project, status="blocked", stage="coder", error_message="Validation failed")
        learner = LearningService(db)

        signature = learner.record_block(
            run.id,
            block_type="validation_failure",
            stage="tester",
            source="validation_profile",
            message="Validation failed",
            guidance="Fix pytest failures before retrying.",
            target_stages=["coder", "tester"],
        )
        learner.retire_block_on_resolution(run.id, signature, resolved_by_stage="tester")
        learner.finalize_terminal_run(run.id)

        improvements = db.query(ImprovementModel).filter(ImprovementModel.source_run_id == run.id).all()
        block_titles = [item.title for item in improvements if item.title.startswith("Resolved block:")]
        assert len(block_titles) == len(set(block_titles))
    finally:
        db.close()


def test_block_resolution_improvement_uses_friendly_title(tmp_path):
    db = SessionLocal()
    try:
        project = _seed_project(db, tmp_path, "FriendlyBlockTitle")
        run = _seed_run(db, project=project, status="running", stage="reviewer")
        learner = LearningService(db)

        signature = learner.record_block(
            run.id,
            block_type="review_rejection",
            stage="reviewer",
            source="reviewer",
            message="Review rejected due to insufficient evidence.",
            guidance="Include concrete reviewer evidence before retrying.",
            target_stages=["coder", "reviewer"],
        )
        learner.retire_block_on_resolution(run.id, signature, resolved_by_stage="reviewer")

        improvement = db.query(ImprovementModel).filter(ImprovementModel.source_run_id == run.id).first()
        assert improvement is not None

        serialized = learner.get_improvement(improvement.id)
        assert improvement.title == "Avoid repeat reviewer guard rejection"
        assert serialized["display_title"] == "Avoid repeat reviewer guard rejection"
    finally:
        db.close()


def test_unresolved_block_flushed_at_terminal_failure(tmp_path):
    db = SessionLocal()
    try:
        project = _seed_project(db, tmp_path, "BlockFlush")
        run = _seed_run(
            db,
            project=project,
            status="failed",
            stage="coder",
            error_message="Guard rejected",
        )
        learner = LearningService(db)
        learner.record_block(
            run.id,
            block_type="structural_guard",
            stage="coder",
            source="change_guard",
            message="Guard rejected patch",
            guidance="Preserve imports.",
            target_stages=["coder"],
        )
        learner.finalize_terminal_run(run.id)

        lesson = db.query(LessonModel).filter(LessonModel.run_id == run.id).first()
        assert lesson is not None
    finally:
        db.close()


def test_awaiting_approval_mid_run_block_still_creates_lesson(tmp_path):
    db = SessionLocal()
    try:
        project = _seed_project(db, tmp_path, "AwaitBlockLesson")
        run = _seed_run(db, project=project, status=RunStatus.AWAITING_APPROVAL.value, stage="reviewer")
        learner = LearningService(db)

        signature = learner.record_block(
            run.id,
            block_type="review_rejection",
            stage="reviewer",
            source="reviewer",
            message="Missing criterion mapping",
            guidance="Map each change to acceptance criteria.",
            target_stages=["coder"],
        )
        learner.retire_block_on_resolution(run.id, signature, resolved_by_stage="reviewer")
        learner.finalize_terminal_run(run.id)

        assert db.query(LessonModel).filter(LessonModel.run_id == run.id).count() == 1
        assert db.query(ImprovementModel).filter(ImprovementModel.source_run_id == run.id).count() == 1
    finally:
        db.close()
