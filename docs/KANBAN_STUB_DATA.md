# Kanban data

The workbench **Kanban** panel is wired in the IDE (`frontend/src/workbench/builtins.tsx`, `CenterContent` in `App.tsx`) and now reads from live project/task/run data.

## Backend sources

| Endpoint | Module | Behavior |
|----------|--------|----------|
| `GET /api/projects/{project_id}/kanban` | [`backend/app/api/routes/kanban_data.py`](../backend/app/api/routes/kanban_data.py) | Groups real project runs into board columns and returns live summary counts, warnings, and run cards. |
| `GET /api/projects/{project_id}/metrics` | [`backend/app/api/routes/kanban_data.py`](../backend/app/api/routes/kanban_data.py) | Derives success/failure rates and historical score points from real run history. |

## What this means

- Board cards come from persisted `tasks` and `runs`.
- Warning badges and mismatch state come from run truth/readiness metadata.
- No hardcoded sample cards or fake percentages remain in the API path used by the workbench panel.

## Verification

See [VERIFICATION_RULES.md](./VERIFICATION_RULES.md) for the normal manual verification checklist.
