# Quality Gateway

Pass all applicable gates before marking a task **done**.

## Gate 1 — Build & test

| Change type | Required |
|-------------|----------|
| Backend Python | `cd backend && .venv/bin/pytest` → all pass |
| Frontend TS/TSX | `npm --prefix frontend run build` → success |
| Scripts only | Smoke: `./scripts/server.sh status` or targeted script test |

## Gate 2 — Scope

- Diff is limited to the requested task
- No secrets, `.env`, or local DB committed
- Conventions match surrounding code (see AGENTS.md)

## Gate 3 — Behavior

- Happy path works via automated test or documented manual step
- Error paths return clear messages (JSON for API, toast for UI)
- Blocking operations (folder picker, long subprocess) do not freeze other requests

## Gate 4 — Documentation

- Non-obvious behavior documented in AGENTS.md, README, or `docs/` when user-facing
- Task verification template filled for non-trivial work

## Fast path (docs-only)

For markdown-only changes: review for accuracy against repo (ports, paths, commands). No pytest required unless docs reference broken commands.

## Failure handling

If a gate fails:

1. Fix the issue — do not disable tests or lower timeout without approval
2. Re-run the full applicable gate set
3. Note remaining manual verification in the task template
