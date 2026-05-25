# Task Verification — Protected files in planner/architect context

Filled per [TASK_VERIFICATION_TEMPLATE.md](../TASK_VERIFICATION_TEMPLATE.md).

---

## Task

**ID / title:** Inject protected files into planner/architect stage context  
**Date:** 2026-05-25  
**Agent / author:** Cursor agent (subagent pass)

## Scope

- **Files changed:**
  - `backend/app/services/orchestration_service.py` — `_stage_context()` appends protected file list when project has entries
  - `backend/tests/test_api.py` — `test_stage_context_includes_protected_files_for_planner_and_architect`, `test_pipeline_block_protect_resolve_learning_events`
  - `backend/app/services/supervisor_service.py` — valid `path_lines` list spread (no invalid `if` inside list literal)
- **User-visible behavior:** Planner and architect pipeline stages receive the same "Protected files (never patch):" bullet list already shown to coder/reviewer, so early stages can route around protected paths.

## Automated checks

| Check | Command | Result |
|-------|---------|--------|
| Targeted tests | `cd backend && .venv/bin/pytest tests/test_api.py::test_stage_context_includes_protected_files_for_planner_and_architect tests/test_api.py::test_pipeline_block_protect_resolve_learning_events -q` | ☑ 2 passed |
| Full backend suite | `cd backend && .venv/bin/pytest -q` | ☑ **164 passed** (2026-05-25, ~21s) |
| Frontend build | `npm --prefix frontend run build` | ☐ N/A (no TSX changes) |

**Related automated coverage (unchanged unless noted):**

- `test_learning_service.py` — `test_record_and_retire_block_creates_lesson`, block dedupe, terminal flush, awaiting-approval block lessons
- `test_coder_context_includes_acceptance_criteria_and_blueprint` — coder protected-files section
- `test_pipeline_block_protect_resolve_learning_events` — end-to-end via `OrchestrationService._stage_coder`: protected-path guard → `block_recorded` → retry → `block_resolved` → `code_patch_applied`; lesson + project improvement (`Avoid repeat repository safety block`)

## Manual verification

| Step | Expected | Result |
|------|----------|--------|
| Server status | `./scripts/server.sh status` → backend 8500, frontend 5177 | ☑ Checked at doc update (use `start-all` if down) |
| Health API | `curl -s -H "X-Api-Token: dev-token" http://localhost:8500/api/health` | ☑ `{"status":"ok",...}` when backend running |
| UI smoke | http://localhost:5177 loads IDE shell | ☐ Not re-run this pass (prior pass: IDE shell OK) |
| Block → resolve → learning (UI) | Run hits coder guard on protected path → block event → retry resolves → lesson in run/learn UI | ☑ **API/integration** — see automated test above; **UI event cards not exercised** in this pass |

### Operator steps for block → resolve → learning (UI)

1. `./scripts/server.sh start-all`
2. Open http://localhost:5177, select a project with `protected_files` (e.g. `secret.txt`).
3. Start a run whose architect blueprint targets a protected file (or triggers coder `PatchGuardError` on protected path).
4. Confirm run events: `block_recorded`, then after successful retry/coder pass: `block_resolved`, then `code_patch_applied` (orchestration emits resolve before patch-applied).
5. Open run detail / learnings: confirm lesson or improvement titled from resolved block guidance appears on a subsequent run’s planner context (`lessons_applied` event).

Service-layer block/lesson flow is covered by pytest (`test_pipeline_block_protect_resolve_learning_events` + `test_learning_service.py`). UI wiring remains optional manual confirmation using the steps above.

## Notes

- Coder stage may list protected files twice (once from `_stage_context`, once from `_build_coder_context`); harmless duplication, minimal diff.
- Reviewer uses label `Protected files:` in `_build_reviewer_context`; planner/architect/coder early context use `Protected files (never patch):`.
- `supervisor_service.build_post_deploy_context` uses `path_lines` built before the `sections` list (fixes invalid `*(... if ... else ...)` inside a list literal).

## Sign-off

- [x] Matches [VERIFICATION_RULES.md](../VERIFICATION_RULES.md) for automated scope
- [x] Backend pytest green (164 passed)
- [x] Block → resolve → learning — **API/integration confirmed** (`test_pipeline_block_protect_resolve_learning_events`); full IDE run-detail UI not re-validated this pass
