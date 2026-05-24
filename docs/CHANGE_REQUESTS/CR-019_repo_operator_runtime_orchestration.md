# CR-019 — Run Workspace File Open, Resume Controls, and Startup Auto-Resume

## Status: Implemented

## Scope

This CR covers the shipped operator-facing run utilities that were actually deployed:

- run-scoped file open via `openRunFile`
- backend run workspace file-read endpoint
- stuck-run **Resume run** controls in UI/API
- startup **auto-resume** setting in Settings

The filename is retained for continuity with the existing CR registry. Full repo-operator/runtime orchestration is **not** part of this CR and is deferred to CR-020.

| Area | CR-019 (shipped) | Notes |
|------|------------------|-------|
| Per-run workspace file open | `openRunFile` resolution chain: inline → artifact row → run workspace → project source | Uses `GET /api/runs/{id}/files/{path}` |
| Stuck run recovery | `POST /api/runs/{id}/resume` + Run detail **Resume run** button | Resumable statuses are `pending` and `running` only |
| Startup resume policy | `auto_resume_enabled` in Settings | Backend lifespan re-enqueues **one** inflight run on startup when enabled |
| Operator surfaces | Agent panel / Run detail wiring for file links and resume action | Built on existing run UI from earlier CRs |

**Out of scope:** runtime contracts, bootstrap/remediation, managed repo services, health/smoke orchestration, runtime dashboard/API, search/rename/delete (CR-018), model/provider configuration.

## Acceptance criteria

- [x] `openRunFile` resolves file content in this order: inline content → artifact row → `GET /api/runs/{id}/files/...` → project source read
- [x] Artifact/review file links use `openRunFile` with `runId` / `artifacts` when available
- [x] `api.runs.resume` calls `POST /api/runs/{run_id}/resume` for `pending` / `running` runs
- [x] Run detail drawer shows **Resume run** only when the run is resumable
- [x] Settings exposes **Resume interrupted runs on server startup** (`auto_resume_enabled`)
- [x] Higher-level docs make it explicit that startup auto-resume re-enqueues only **one** pending/running run
- [x] No stray root `package.json` exists; frontend package remains under `frontend/`

## Implementation notes

- Backend resume and startup auto-resume already existed; this CR makes the capability visible and testable through frontend API/UI and documentation.
- `isResumableStatus` in `frontend/src/types/runs.ts` matches backend resume endpoint rules.
- `GET /api/runs/{run_id}/files/{path:path}` reads only from a run workspace, with traversal protection and dotfile-safe path encoding from the frontend.
- Startup auto-resume is intentionally limited to a batch size of **1** per backend startup.

## Verification checklist

### Automated

| Check | Command / step | Result |
|-------|----------------|--------|
| Backend tests | `cd backend && .venv/bin/pytest -q` | **117 passed**, 3 warnings |
| Frontend build | `npm --prefix frontend run build` | pass |
| Server health | `GET /api/health` | ok |
| Resume endpoint success | `POST /api/runs/{id}/resume` on `pending`/`running` | covered by pytest |
| Resume endpoint rejection | `POST /api/runs/{id}/resume` on non-resumable status | covered by pytest |
| Run workspace file read | `GET /api/runs/{id}/files/{path}` incl. dotfile | covered by pytest |
| Startup auto-resume enabled | lifespan startup calls `resume_inflight_runs(db, limit=1)` | covered by pytest |
| Startup auto-resume disabled | lifespan startup skips `resume_inflight_runs` | covered by pytest |

### Manual

| Check | Step | Result |
|-------|------|--------|
| Run-context file open | Review/artifact file link opens correct content before approval | Pending live verification |
| Dotfile file open | Dotfile path opens without 404 | Pending live verification |
| Post-cleanup fallback | After approve/promote and workspace cleanup, file open falls back to project source | Pending live verification |
| Resume stuck run | **Resume run** visible on resumable run and re-queues it | Pending live verification |
| Auto-resume enabled | Enabled setting re-enqueues exactly one inflight run after backend restart | Pending live verification |
| Auto-resume disabled | Disabled setting prevents startup auto-resume | Pending live verification |

Manual verification is seeded by `scripts/verification/seed_cr019_manual_check.py`.

## Files

- `frontend/src/lib/openRunFile.ts`
- `frontend/src/lib/artifactFileContent.ts`
- `frontend/src/components/AgentPanel/ArtifactViewer.tsx`
- `frontend/src/components/AgentPanel/ReviewArtifactPanel.tsx`
- `frontend/src/components/AgentPanel/RunDetailDrawer.tsx`
- `frontend/src/components/Chat/RunFollowUpCard.tsx`
- `frontend/src/api/client.ts`
- `frontend/src/components/Settings/SettingsPanel.tsx`
- `backend/app/api/routes/api.py`
- `backend/app/api/main.py`
- `backend/tests/test_api.py`
- `scripts/verification/seed_cr019_manual_check.py`
- `scripts/verification/cleanup_cr019_manual_check.py`
