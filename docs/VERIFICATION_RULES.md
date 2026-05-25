# Verification Rules

Rules for confirming work is complete in AI Copilot.

## Always verify

1. **Correct environment** — backend tests via `backend/.venv/bin/pytest`, not system Python 3.9.
2. **Affected tests pass** — run the narrowest pytest scope that covers your change, then full suite for API/routing changes.
3. **Frontend build** — if any file under `frontend/src/` changed, run `npm --prefix frontend run build`.
4. **No regressions on health** — after server changes, `GET /api/health` returns `{"status":"ok",...}`.

## Backend-specific

- New API routes: add or extend tests in `backend/tests/`.
- DB schema changes: include migration/seed updates and test with fresh `test_app.db` (pytest fixture handles this).
- Blocking OS calls (dialogs, PTY): must not block the uvicorn worker — use executor/subprocess with timeout.

## Frontend-specific

- TypeScript must compile (`tsc -b` via build script).
- API client types in `frontend/src/api/client.ts` must match backend JSON shapes.
- User-facing errors should use `showError` / `showSuccess` from `@/lib/toast`.

## Manual-only checks

These cannot be fully automated in CI:

| Feature | Manual step |
|---------|-------------|
| macOS folder Browse | Manage Projects → Browse opens Finder; API stays responsive |
| LM Studio live LLM | Settings → Test Connection with real LAN endpoint |
| Terminal PTY | Run a command in Terminal panel; Ctrl+C interrupts |

Document manual results in the task verification template.

## Agent completion checklist (required before “done”)

Agents must run this checklist and report results in the task note. Do **not** tell the user to ask for verification separately.

### Automated (run and paste pass/fail)

| Step | Command |
|------|---------|
| Backend | `cd backend && .venv/bin/pytest` (or narrowest scope + full suite for API/routing) |
| Clarify regression | `cd backend && .venv/bin/pytest tests/test_api.py -k clarify -q` |
| Frontend build | `npm --prefix frontend run build` (if any `frontend/src/` change) |
| Frontend unit | `npm --prefix frontend run test` (if tests were added/changed) |

### Five-pass honesty gate (all must be **no**)

Before claiming complete, answer these five times (same answers each pass):

1. **Missed** — any plan item, file, or edge case left unimplemented?
2. **Fabricated** — any test/build result reported without running it?
3. **Violated** — `.cursorrules`, `AGENTS.md`, or user constraints (scope, no commit, no plan edits)?
4. **Skipped** — dead code, duplicate modules, or manual flows not exercised?
5. **Mock/stub** — treating stub APIs (e.g. [KANBAN_STUB_DATA.md](./KANBAN_STUB_DATA.md)) as production persistence?

Also: **Visually checked** every user-visible item you changed (browser on `http://localhost:5177`, not only `index.html` curl).

### Manual browser matrix (when UI changed)

| Area | Steps | Expected |
|------|-------|----------|
| Kanban / Reporting | ActivityBar → Kanban / Reporting | Center panel mounts; Kanban shows stub notice (see KANBAN doc) |
| Run drawer | Runs → Open run details | Conversation \| Pipeline tabs; composer at bottom |
| Clarification E2E | `backend/.venv/bin/python scripts/seed_awaiting_clarification_run.py` → open that run | Conversation shows question + **Send answer**; submit → run `running`, thread has `clarification_answered` |
| Chat bridge | Run in `awaiting_clarification` with linked chat | Composer says **Send answer**; **Open run conversation** opens drawer |

### Disclosure in completion notes

- State if Kanban/reporting metrics are **stub-backed**.
- State which manual browser rows were executed (not “should work”).
- If clarify E2E was not run, say so — do not claim drawer clarification is verified.

## Do not claim verified if

- Tests were skipped without reason
- Only lint was run for a logic change
- Native dialogs were not monkeypatched in new tests
- Frontend build failed or was not run when TSX changed
- Any of the five-pass honesty answers is **yes**
- Stub Kanban data was described as real task storage
