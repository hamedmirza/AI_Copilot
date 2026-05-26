"""Matrix scenario definitions M01–M20."""

from __future__ import annotations

from dataclasses import dataclass

from tests.fixtures.pipeline_matrix import repos


@dataclass(frozen=True)
class MatrixCase:
    scenario_id: str
    repo_mode: str
    task_kind: str
    description: str
    architect_paths: list[str]
    validation_profile: str = "python"
    playbook_approved: bool = True
    debug_plan: bool = False
    expected_status: str = "awaiting_approval"
    approve_after: bool = False
    resolve_clarification: bool = True

    def build_repo(self, tmp_path):
        root = tmp_path / f"matrix_{self.scenario_id.lower()}"
        if self.repo_mode == "greenfield":
            return repos.build_greenfield(root)
        if self.repo_mode == "partial":
            return repos.build_partial(root)
        if self.repo_mode == "debug":
            return repos.build_debug_broken(root)
        return repos.build_full(root)


MATRIX_CASES: tuple[MatrixCase, ...] = (
    MatrixCase("M01", "greenfield", "implementation", "Create backend/app/demo.py with a unit test", ["backend/app/demo.py"]),
    MatrixCase("M02", "greenfield", "implementation", "Add frontend/src/App.tsx scaffold for the new UI", ["frontend/src/App.tsx"], validation_profile="fullstack"),
    MatrixCase("M03", "partial", "implementation", "Patch backend/app/services/foo.py to return 2", ["backend/app/services/foo.py"]),
    MatrixCase("M04", "full", "implementation", "Extend backend/app/services/foo.py and update backend/tests/test_foo.py", ["backend/app/services/foo.py", "backend/tests/test_foo.py"]),
    MatrixCase("M05", "full", "implementation", "Change frontend UI label in frontend/src/App.tsx", ["frontend/src/App.tsx"], validation_profile="fullstack"),
    MatrixCase("M06", "greenfield", "analysis", "Produce repo structure analysis report only", [".ai-copilot/reports/structure.md"]),
    MatrixCase("M07", "partial", "analysis", "Audit module foo and write findings to .ai-copilot/reports/foo-audit.md", [".ai-copilot/reports/foo-audit.md"]),
    MatrixCase("M08", "full", "analysis", "Security review report for the service layer", [".ai-copilot/reports/security.md"]),
    MatrixCase("M09", "partial", "validation", "Run pytest on changed backend modules", [], validation_profile="python"),
    MatrixCase("M10", "full", "validation", "Verify frontend build and backend tests", [], validation_profile="fullstack"),
    MatrixCase("M11", "debug", "debug", "Diagnose failing test in backend/tests/test_broken.py", ["backend/tests/test_broken.py"], debug_plan=True),
    MatrixCase("M12", "partial", "debug", "Fix ImportError in backend/app/services/foo.py", ["backend/app/services/foo.py"], debug_plan=True),
    MatrixCase("M13", "full", "playbook", "Deploy runbook with rollback steps for production release", []),
    MatrixCase(
        "M14",
        "full",
        "playbook",
        "Destructive playbook without rollback steps",
        [],
        playbook_approved=False,
        expected_status="blocked",
    ),
    MatrixCase("M15", "greenfield", "setup", "Project scaffold task for new greenfield workspace", ["backend/app/main.py"]),
    MatrixCase(
        "M16",
        "full",
        "implementation",
        "Doc-only: update README.md with usage notes",
        ["README.md", "backend/app/services/foo.py"],
    ),
    MatrixCase(
        "M17",
        "full",
        "implementation",
        "Update documentation artifacts in docs/CHANGELOG.md",
        ["docs/CHANGELOG.md", "backend/app/services/foo.py"],
    ),
    MatrixCase(
        "M18",
        "full",
        "mixed",
        "Update frontend dashboard page and backend API route together",
        ["frontend/src/App.tsx", "backend/app/services/foo.py"],
        validation_profile="fullstack",
    ),
    MatrixCase("M19", "full", "implementation", "Reach approval gate for small backend tweak", ["backend/app/services/foo.py"], approve_after=True, expected_status="completed"),
    MatrixCase(
        "M20",
        "partial",
        "implementation",
        "Improve kanban dashboard experience without specifying frontend or backend",
        ["frontend/src/App.tsx"],
        validation_profile="fullstack",
    ),
)
