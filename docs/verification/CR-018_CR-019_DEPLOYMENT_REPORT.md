# Deployment Report — CR-018 & CR-019

Filled per [TASK_VERIFICATION_TEMPLATE.md](../TASK_VERIFICATION_TEMPLATE.md) and [VERIFICATION_RULES.md](../VERIFICATION_RULES.md).

---

## Executive summary

**CR-018** remains historically complete and verified based on the 2026-05-21 implementation pass. This report keeps that record intact except for one wording correction: the workspace-isolation path is `runtime/workspaces/{run_id}`, not `backend/workspaces/{run_id}`.

**CR-019** was previously overstated. The code that is actually deployed is narrower than the old title implied. The shipped scope is:

- run-scoped file open via `openRunFile`
- backend run workspace file-read endpoint
- stuck-run **Resume run** UI/API
- startup **auto-resume** setting

CR-019 is therefore **implemented but not yet fully verified** in this report. Automated checks pass. Manual verification remains pending until the seeded live pass is completed and recorded.

The broader repo-operator/runtime orchestration capability has been split out as **CR-020 (planned)**.

---

## Baseline captured before truth-alignment

Run on 2026-05-24 before doc cleanup:

| Check | Result |
|------|--------|
| `./scripts/server.sh status` | backend running on `8500`, frontend running on `5177` |
| `curl -s http://127.0.0.1:8500/api/health` | `{"status":"ok","version":"0.1.0","uptime_seconds":26058,"worker_count":3,"ws_connections":14}` |
| `curl -s -H "X-Api-Token: dev-token" http://127.0.0.1:8500/api/settings` | `auto_resume_enabled=true`, `stop_on_first_failure=true`, `worker_count=3`, LM Studio active |
| `cd backend && .venv/bin/pytest -q` | **117 passed**, 3 warnings |
| `npm --prefix frontend run build` | pass |

Repo truth observed during this pass:

- `docs/CHANGE_REQUESTS/CR-019_repo_operator_runtime_orchestration.md` overstated the shipped capability.
- `docs/TASK_CHECKLIST.md` marked CR-019 as fully verified even though the live manual proof was not trustworthy enough to support that claim.
- `docs/TASK_CHECKLIST.md` also contained stale wording referencing `backend/workspaces/{run_id}`.
- Root `package.json` is absent; frontend package remains under `frontend/package.json`.

---

## CR-018 — Search, Rename, Artifacts, Delete

### Status

- **Implementation:** complete
- **Verification:** historically verified
- **Truth adjustment in this pass:** workspace path wording corrected only

### Historical evidence retained

| Check | Result |
|------|--------|
| Backend tests at original closeout | **38 passed** |
| Frontend build | pass |
| Browser pass on IDE shell / editor / agent panel / settings | pass |
| Search / rename / delete / project delete / artifact viewer flows | pass |

### Correction applied in this truth pass

The old verification summary said:

- `backend/workspaces/{run_id}`

The actual isolated run workspace location is:

- `runtime/workspaces/{run_id}`

No broader CR-018 drift was found in this pass.

---

## CR-019 — Run Workspace File Open, Resume Controls, and Startup Auto-Resume

### Status

- **Implementation:** complete
- **Verification:** partial
- **Reason for partial state:** required manual checks are not yet re-executed and recorded with a repeatable seeded fixture

### Actual shipped scope

| Area | Shipped behavior | Evidence |
|------|------------------|----------|
| Run file open | `openRunFile` resolves inline → artifact row → run workspace → project source | `frontend/src/lib/openRunFile.ts` |
| Run workspace file-read API | `GET /api/runs/{id}/files/{path}` reads from run workspace with traversal guard | `backend/app/api/routes/api.py` |
| Resume run UI/API | `POST /api/runs/{id}/resume`; Run detail shows **Resume run** for `pending`/`running` | `backend/app/api/routes/api.py`, `frontend/src/components/AgentPanel/RunDetailDrawer.tsx` |
| Startup auto-resume setting | Settings exposes `auto_resume_enabled`; backend lifespan re-enqueues one inflight run when enabled | `frontend/src/components/Settings/SettingsPanel.tsx`, `backend/app/api/main.py` |

### Out of scope

CR-019 does **not** ship:

- project runtime contracts
- repo bootstrap/remediation
- managed repo services
- runtime health/smoke orchestration
- runtime dashboard/API

That future capability now belongs to **CR-020**.

---

## Automated verification results

### Current truth-pass results (2026-05-24)

| Check | Result |
|------|--------|
| `cd backend && .venv/bin/pytest -q` | **117 passed**, 3 warnings |
| `npm --prefix frontend run build` | pass |
| `GET /api/health` | 200 OK |

### CR-019-specific automated coverage present

| Behavior | Coverage state |
|------|----------------|
| Resume endpoint success on resumable run | present |
| Run workspace file read (`package.json`) | present |
| Dotfile workspace file read (`.npmrc`) | present |

### CR-019-specific automated coverage added/required by this change

This truth-alignment change requires and should end with coverage for:

| Behavior | Target |
|------|--------|
| Resume endpoint rejection on non-resumable run | pytest |
| Lifespan auto-resume enabled calls `resume_inflight_runs(..., limit=1)` | pytest |
| Lifespan auto-resume disabled skips resume call | pytest |

---

## Manual verification state

### Required manual flows

The following are still the required manual/live checks for CR-019:

| Flow | Required proof state |
|------|----------------------|
| Run-context file open before approval | file link opens correct content |
| Dotfile file open | dotfile path opens without 404 |
| Post-approve fallback | same path opens via project-source fallback after workspace cleanup |
| Resume stuck run | **Resume run** visible and re-queues run |
| Auto-resume enabled | restart re-enqueues exactly one inflight run |
| Auto-resume disabled | restart does not auto-resume |

### Current state

These checks remain **pending live re-verification** in this report.

Reason:

- the previous record mixed real implementation evidence with over-strong manual-completion claims
- the post-approve fallback flow was not actually proven end to end
- there was no repeatable seeded fixture recorded for the live run checks

This report does **not** claim those manual steps are complete until they are rerun against the seeded helper flow and the results are added here.

---

## Documentation and checklist corrections applied

This truth-alignment pass changes the documentation model as follows:

1. `CR-019` title/scope is narrowed to the shipped feature.
2. `CR-020` is introduced as the planned full repo-operator/runtime layer.
3. `TASK_CHECKLIST.md` row `019` is now `Verified = Partial`.
4. `TASK_CHECKLIST.md` row `020` is added as planned / unverified.
5. Verification policy is now explicit:
   - `Status = [x]` means implementation landed
   - `Verified = Yes` requires automated and manual checks to be completed and recorded
6. stale workspace wording is corrected to `runtime/workspaces/{run_id}`.
7. seeded helper scripts are added for repeatable CR-019 manual verification:
   - `scripts/verification/seed_cr019_manual_check.py`
   - `scripts/verification/cleanup_cr019_manual_check.py`

---

## Remaining work to close CR-019 fully

CR-019 can move from **Partial** to **Yes** only after all of the following are completed and recorded:

1. seed deterministic manual verification fixtures
2. run the live UI/browser checks
3. verify the post-approve project-source fallback path
4. record actual results back into:
   - this report
   - the CR-019 document
   - `TASK_CHECKLIST.md`

---

## Files referenced by CR-019

- `frontend/src/lib/openRunFile.ts`
- `frontend/src/lib/artifactFileContent.ts`
- `frontend/src/api/client.ts`
- `frontend/src/components/AgentPanel/ArtifactViewer.tsx`
- `frontend/src/components/AgentPanel/ReviewArtifactPanel.tsx`
- `frontend/src/components/AgentPanel/RunDetailDrawer.tsx`
- `frontend/src/components/Chat/RunFollowUpCard.tsx`
- `frontend/src/components/Settings/SettingsPanel.tsx`
- `backend/app/api/routes/api.py`
- `backend/app/api/main.py`
- `backend/tests/test_api.py`

---

## Sign-off

### CR-018

- **Implementation:** complete
- **Verification:** yes

### CR-019

- **Implementation:** complete
- **Verification:** partial

### CR-020

- **Implementation:** not started
- **Verification:** no
