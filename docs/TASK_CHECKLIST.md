# AI Copilot — Task Checklist

| CR  | Title                          | Status | Files Changed | Verified | Date       |
|-----|--------------------------------|--------|---------------|----------|------------|
| 001 | Bootstrap & Server             | [x]    | scripts/, backend/app/api/main.py, backend/pyproject.toml | Yes | 2026-05-21 |
| 002 | Database Layer                 | [x]    | backend/app/db/ | Yes | 2026-05-21 |
| 003 | LM Provider Router             | [x]    | backend/app/providers/ | Yes | 2026-05-21 |
| 004 | All 7 Agent Implementations    | [x]    | backend/app/agents/, backend/app/schemas/agent_outputs.py | Yes | 2026-05-21 |
| 005 | Run Engine & Orchestration     | [x]    | backend/app/services/orchestration_service.py, run_engine/ | Yes | 2026-05-21 |
| 006 | File Service & Patch Guard     | [x]    | backend/app/services/file_service.py, tools/patch_guard.py | Yes | 2026-05-21 |
| 007 | Projects API & Multi-Repo      | [x]    | backend/app/services/project_service.py, api/routes/ | Yes | 2026-05-21 |
| 008 | Frontend IDE Shell             | [x]    | frontend/src/App.tsx, store/, ActivityBar | Yes | 2026-05-21 |
| 009 | File Tree & Monaco Editor      | [x]    | frontend/src/components/FileTree/, Editor/ | Yes | 2026-05-21 |
| 010 | Terminal Panel                 | [x]    | frontend/src/components/Terminal/, api terminal WS | Yes | 2026-05-21 |
| 011 | Agent Panel & Pipeline UI      | [x]    | frontend/src/components/AgentPanel/ | Yes | 2026-05-21 |
| 012 | Git Panel                      | [x]    | frontend/src/components/GitPanel/, git_service.py | Yes | 2026-05-21 |
| 013 | Settings & LM Configuration    | [x]    | frontend/src/components/Settings/ | Yes | 2026-05-21 |
| 014 | Validation Profiles & Tester   | [x]    | backend/app/tools/command_runner.py | Yes | 2026-05-21 |
| 015 | Logging & Observability        | [x]    | backend/app/core/logging.py, LogViewer | Yes | 2026-05-21 |
| 016 | Onboarding & Empty States      | [x]    | frontend/src/components/Onboarding/ | Yes | 2026-05-21 |
| 017 | Documentation & CR Registry    | [x]    | docs/, README.md, .env.example | Yes | 2026-05-21 |
| 018 | Search, Rename, Artifacts, Delete | [x] | frontend SearchPanel, FileTree, ArtifactViewer, ProjectDeleteDialog; api rename endpoint | Yes | 2026-05-21 |

## Verification Summary (2026-05-21, re-verified)

- `./scripts/server.sh start` → health 200 `{"status":"ok","version":"0.1.0"}`
- Second start → `Server already running (pid 98447)`
- `npm --prefix frontend run build` → success (tsc + vite)
- `pytest` → 14 passed
- Browser E2E → `http://localhost:5177` (fixed Vite dev port; fails if busy instead of auto-increment)
  - Search, Settings, Agent validation, delete confirm, Git, onboarding Help, Monaco open file

## Gap Closure (2026-05-21)

- Search panel: file search by path fragment in sidebar
- File tree: inline rename, drag-and-drop move, proper context menu (rename/delete/copy path)
- File tree auto-refresh: global WS triggers refresh 3s after `run_completed` / `code_patch_applied` / `awaiting_approval`
- Agent panel: WS run status from pipeline events; collapsible JSON artifacts with copy
- Project delete: type-name-to-confirm dialog in top bar
- Project switch: clears editor tabs and agent state; overlay shows project name
- Terminal: explicit Ctrl+C (`\x03`) relay to PTY
- Duplicate route modules removed (consolidated in `api.py` only)
- Onboarding: Skip button; re-open via Help menu
