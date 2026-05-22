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

## Do not claim verified if

- Tests were skipped without reason
- Only lint was run for a logic change
- Native dialogs were not monkeypatched in new tests
- Frontend build failed or was not run when TSX changed
