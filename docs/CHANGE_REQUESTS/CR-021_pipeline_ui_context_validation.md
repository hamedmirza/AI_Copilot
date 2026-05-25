# CR-021 — Pipeline UI gate, context injection, and frontend scaffold guard

## Status: Implemented

## Problem

Pipeline runs could classify tasks as frontend deliverables (via `infer_deliverable_kind`) while `UIDesignerAgent` skipped unless the literal word `frontend` appeared in context. Architect/plan artifacts were not injected into the ui_designer stage. Fullstack validation ran `npm --prefix frontend run build` on greenfield workspaces without `frontend/package.json`, producing opaque ENOENT failures.

## Scope

| Area | Change |
|------|--------|
| UI gate | `should_run_ui_designer` aligned with `infer_deliverable_kind` / UI surface tokens; orchestration owns skip |
| Context | `_append_pipeline_artifact_context` injects plan + architect into ui_designer; coder receives ui_design summary |
| Scaffold guard | `partition_frontend_commands` blocks required frontend npm validation with `FRONTEND_SCAFFOLD_MESSAGE` |

## Acceptance criteria

- [x] Tasks mentioning UI/screen/dashboard (without the word `frontend`) run ui_designer when deliverable kind is frontend
- [x] ui_designer stage context includes planner summary, acceptance criteria, architect overview/modules/paths
- [x] Coder context includes ui_design summary when a ui_design artifact exists
- [x] Required `npm --prefix frontend` commands do not run when `frontend/package.json` is missing; run blocks with scaffold guidance
- [x] Optional blocked frontend npm commands record `validation_skipped` instead of ENOENT
- [x] Unit tests cover UI gate helpers, scaffold partition, and tester block behavior

## Files touched

- `backend/app/services/run_truth_service.py`
- `backend/app/agents/__init__.py`
- `backend/app/services/orchestration_service.py`
- `backend/app/tools/lint_runner.py`
- `backend/app/providers/fake.py`
- `backend/tests/test_deliverable_ui_gate.py`
- `backend/tests/test_lint_runner_scaffold.py`
- `backend/tests/test_agents.py`
- `backend/tests/test_api.py`

## Out of scope

- Scaffolding end-user project repos (e.g. `AI_Assitant`)
- Changing default validation profile command lists in `backend/app/core/defaults.py`
