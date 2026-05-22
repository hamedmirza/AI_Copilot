# Comprehensive Rules and Guidelines

Consolidated standards for humans and AI agents in AI Copilot.

## Architecture (actual)

- **Monorepo**: `backend/` (FastAPI) + `frontend/` (Vite React), orchestrated by `scripts/server.sh`
- **Persistence**: SQLite at `backend/app.db` (WAL mode)
- **Auth**: `X-Api-Token` header; default dev token `dev-token`
- **Agents pipeline**: Planner → Architect → UI Designer → Coder → Reviewer → Tester → Supervisor
- **Projects**: local workspace path or HTTPS git clone into `backend/repos/`

## Coding standards

### Python (backend)

- Python 3.12+, line length 100 (ruff)
- Type hints on public functions
- Services in `backend/app/services/`, routes in `backend/app/api/routes/`
- Raise domain exceptions from `app.core.exceptions`; map to HTTP in route handlers
- Prefer explicit imports; avoid circular imports via lazy imports when needed

### TypeScript (frontend)

- Path alias `@/` → `frontend/src/`
- Zustand stores in `frontend/src/store/`
- API access only through `frontend/src/api/client.ts`
- UI primitives in `frontend/src/components/ui/`

## Agent behavior

1. Read existing code before editing
2. Minimal diff — solve the stated problem only
3. Run tests and build (see [TESTING.md](TESTING.md))
4. Do not commit unless asked
5. Follow [VERIFICATION_RULES.md](VERIFICATION_RULES.md) and [QUALITY_GATEWAY.md](QUALITY_GATEWAY.md)

## Native OS integration

- **macOS folder picker**: AppleScript via `backend/app/tools/dialog_service.py`
- Route runs picker in a thread pool with 120s timeout so uvicorn stays responsive
- Tests must monkeypatch `pick_directory`; real Finder is manual (AGENTS.md)

## WebSocket

- Hooks in `frontend/src/hooks/useWebSocket.ts`
- Dev Strict Mode may log benign close-before-open warnings; production unaffected

## Documentation map

| Doc | Purpose |
|-----|---------|
| README.md | User quick start |
| AGENTS.md | Agent stack & commands |
| Cursor_Guide.md | Pre-task checklist |
| docs/TESTING.md | pytest & build commands |
| docs/TASK_CHECKLIST.md | Feature CR tracker |
| docs/TASK_VERIFICATION_TEMPLATE.md | Per-task sign-off |
