# Kanban and reporting data (stub APIs)

The workbench **Kanban** and **Reporting** panels are wired in the IDE (`frontend/src/workbench/builtins.tsx`, `CenterContent` in `App.tsx`). Their **data layer is stubbed** until a real task/metrics store exists.

## Backend stubs

| Endpoint | Module | Behavior |
|----------|--------|----------|
| `GET /api/projects/{project_id}/tasks` | [`backend/app/api/routes/kanban_data.py`](../backend/app/api/routes/kanban_data.py) | Returns two fixed sample tasks per project (`Sample task`, `In progress item`). |
| `PATCH /api/tasks/{task_id}` | same | Echoes update with generic title/description; does not persist. |
| `GET /api/projects/{project_id}/metrics` | same | Returns hardcoded success/failure rates and chart points. |

## What this means

- Drag-and-drop and UI layout are real; **task rows are not stored in SQLite**.
- Pipeline runs that implement “real Kanban” must replace `kanban_data.py` (or add models + migrations) and point `api.kanban` at persistent storage.
- Visual evidence and integration guards check **wiring** (pages, workbench, App mount), not production task data.

## UI indicator

`KanbanWorkbenchPanel` shows a short “stub data” note under the board title when tasks load from the stub API.

## Verification

See [VERIFICATION_RULES.md](./VERIFICATION_RULES.md) — Kanban manual row and agent completion checklist.
