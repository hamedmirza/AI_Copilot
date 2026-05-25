# AI Copilot — Task Checklist

| CR  | Title                          | Status | Files Changed | Verified | Date       |
|-----|--------------------------------|--------|---------------|----------|------------|
| 001 | Bootstrap & Server             | [x]    | scripts/server.sh, backend/app/api/main.py | Yes | 2026-05-21 |
| 002 | Database Layer                 | [x]    | backend/app/db/ | Yes | 2026-05-21 |
| 003 | LM Provider Router             | [x]    | backend/app/providers/ | Yes | 2026-05-21 |
| 004 | All 7 Agent Implementations    | [x]    | backend/app/agents/ | Yes | 2026-05-21 |
| 005 | Run Engine & Orchestration     | [x]    | orchestration_service.py, workspace_service.py | Yes | 2026-05-21 |
| 006 | File Service & Patch Guard     | [x]    | file_service.py, patch_guard.py | Yes | 2026-05-21 |
| 007 | Projects API & Multi-Repo      | [x]    | project_service.py, api routes | Yes | 2026-05-21 |
| 008 | Frontend IDE Shell             | [x]    | frontend/src/App.tsx, store/ | Yes | 2026-05-21 |
| 009 | File Tree & Monaco Editor      | [x]    | FileTree/, Editor/ | Yes | 2026-05-21 |
| 010 | Terminal Panel                 | [x]    | Terminal/, terminal WS | Yes | 2026-05-21 |
| 011 | Agent Panel & Pipeline UI      | [x]    | AgentPanel/, ApproveDialog Monaco diff | Yes | 2026-05-21 |
| 012 | Git Panel                      | [x]    | GitPanel/, git_service.py | Yes | 2026-05-21 |
| 013 | Settings & LM Configuration    | [x]    | Settings/, POST /api/settings/reset | Yes | 2026-05-21 |
| 014 | Validation Profiles & Tester   | [x]    | command_runner.py | Yes | 2026-05-21 |
| 015 | Logging & Observability        | [x]    | logging.py, LogViewer | Yes | 2026-05-21 |
| 016 | Onboarding & Empty States      | [x]    | Onboarding/, onboarding/status API | Yes | 2026-05-21 |
| 017 | Documentation & CR Registry    | [x]    | docs/CHANGE_REQUESTS/, README.md | Yes | 2026-05-21 |
| 018 | Search, Rename, Artifacts, Delete | [x] | SearchPanel, FileTree, ProjectDeleteDialog | Yes | 2026-05-21 |
| 019 | Run Workspace File Open, Resume Controls, and Startup Auto-Resume | [x] | openRunFile, runs.resume UI, auto_resume settings | Partial (auto 2026-05-24, manual pending) | 2026-05-24 |
| 020 | Full Repo Operator Runtime Layer | [ ] | runtime contract, bootstrap/remediation, managed services, health/smoke UI/API | No | - |

## Verification Summary (2026-05-24 — CR-019 truth-alignment pass)

### Automated

| Check | Result |
|-------|--------|
| `cd backend && .venv/bin/pytest -q` | **117 passed**, 3 warnings |
| `npm --prefix frontend run build` | Success (tsc + vite) |
| `GET /api/health` | 200 OK |
| `GET /api/runs/{id}/files/{path}` | Covered by pytest (`package.json` + dotfile `.npmrc`) |
| `POST /api/runs/{id}/resume` | Covered by pytest (success + rejection cases) |
| Lifespan auto-resume enabled | Covered by pytest (`resume_inflight_runs(..., limit=1)`) |
| Lifespan auto-resume disabled | Covered by pytest (no resume call) |

### Manual verification status

| Flow | Status |
|------|--------|
| Settings → Pipeline runtime → auto-resume checkbox | Pending live re-verification |
| RUNS tab → run detail → **Resume run** button | Pending live re-verification |
| Run-context file link before approval | Pending live re-verification |
| Dotfile workspace path open | Pending live re-verification |
| Post-approve fallback to project source | Pending live re-verification |

**Truth note:** CR-019 implementation is present, but the remaining manual checks have not been re-executed and re-recorded in a way that proves the live flows end to end. Keep this row at `Verified = Partial` until the seeded manual pass is completed.

## Verification Summary (2026-05-21 — plan completion)

### Automated

| Check | Result |
|-------|--------|
| `./scripts/server.sh stop` then `pytest -q` | **38 passed** |
| `npm --prefix frontend run build` | Success (tsc + vite) |
| `GET /api/health` | `{"status":"ok","version":"0.1.0"}` |
| `POST /api/settings/reset` | Reverts to `http://172.10.1.2:1234/v1`, `worker_count: 1` |
| `test_run_workspace_isolation` | Run workspace under `runtime/workspaces/{run_id}`, source unchanged until approve |

### Browser E2E (`http://localhost:5177`)

| Flow | Result |
|------|--------|
| Manage Projects → Add Project 3-step wizard | Pass — Step 1 (name/description) → Step 2 (repo/picker) → Step 3 (validation profile + Create) |
| Manage Projects (list / edit / remove) | Pass |
| Settings (`Cmd+,` / gear) | Pass |
| Editor + Monaco | Pass |
| Agent panel (RUNS tab) | Pass — task form, stage chips, Approve/Reject/Retry |
| Approve dialog Monaco diff (§7B) | Implemented — side-by-side `DiffEditor` per changed file from coder artifact; requires `awaiting_approval` run to exercise live |
| Terminal / Git panel | Pass |

### Gap fixes (final pass)

1. **§7H Manage Projects Add** — `ProjectAddWizard.tsx` (3 steps: details → repository with Browse/Git → validation profile review); wired in `ProjectManagerDialog` add mode.
2. **§7B ApproveDialog Monaco diff** — `coderPatchDiff.ts` + `applyLineChanges.ts`; `ApproveDialog` loads original (project source) vs proposed (coder patch) in Monaco `DiffEditor` with per-file tabs.
3. **Per-run workspace isolation** — `workspace_service.prepare_run_workspace()`; approve promotes then discards.
4. **Settings reset** — `POST /api/settings/reset`.
5. **Fresh-DB onboarding** — `GET /api/onboarding/status`; Help menu re-opens wizard.

## Known limitations (non-blocking)

- **LM Studio live test** at `172.10.1.2:1234` not verified on this machine when LAN host is offline; Test Connection works when reachable.
- **pytest teardown** — background run workers may log `Event loop is closed` after TestClient shutdown (benign; tests still pass).

## Commands

```bash
./scripts/server.sh start-all       # backend :8500 + frontend :5177
./scripts/server.sh status

cd backend && .venv/bin/pytest -q
npm --prefix frontend run build
```

## Verification row policy

- `Status = [x]` means implementation landed.
- `Verified = Yes` requires both automated checks and all required manual-only checks to be completed and recorded.
- If manual checks remain open, use `Verified = Partial` or `No`.
- Do not use a CR title broader than the capability that actually shipped.
