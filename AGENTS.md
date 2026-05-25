# AI Copilot — Agent Guide

How AI agents (Cursor, CI bots) should work in this repository.

## Stack

| Layer | Tech |
|-------|------|
| Backend | Python 3.12+, FastAPI, SQLAlchemy, SQLite WAL, uvicorn (port **8500**) |
| Frontend | React 19, Vite, Tailwind, Monaco, xterm.js (port **5177**, strictPort) |
| LLM | LM Studio / Ollama via provider registry; fake provider in tests |
| Real-time | WebSocket `/ws/runs/{id}`, `/ws/events`, terminal PTY WS |

## Repo layout

```
backend/app/          # FastAPI app (api/, services/, agents/, providers/, tools/)
backend/tests/        # pytest suite
frontend/src/         # React IDE shell
scripts/server.sh     # start/stop backend + frontend
docs/                 # checklists, verification templates, change requests
```

## Commands

```bash
# Dev servers
./scripts/server.sh start-all      # backend 8500 + frontend 5177
./scripts/server.sh status
./scripts/server.sh stop

# Backend tests (always use venv — see docs/TESTING.md)
cd backend && .venv/bin/pytest

# Frontend build
npm --prefix frontend run build
```

First-time setup: `cp .env.example .env`, then `npm --prefix frontend install`. The venv is created automatically by `server.sh` on first start.

## Agent behavior

- **Static role skills** — curated operational guidance for pipeline agents and chat modes lives in [`backend/app/agents/skills/`](backend/app/agents/skills/). Loaded at runtime via [`skill_loader.py`](backend/app/agents/skill_loader.py) and appended to system prompts.
- **Integrity charter + pipeline framework** — every agent prompt also receives [`_integrity.md`](backend/app/agents/skills/_integrity.md) (universal rules, task-kind addendum, verification doc links) and [`pipeline-framework.md`](backend/app/agents/skills/pipeline-framework.md) (stage handoff contract). Resolved pipeline blocks (`record_block` → `retire_block_on_resolution`) become project learnings automatically and are injected into retry context and future runs via `LearningService`.
- **Dynamic learned skills** — approved entries in the `global_skills` table are injected per run by `LearningService.build_learning_context()` (top-4 scored items). These improve from run history; role skill markdown files are version-controlled and edited deliberately.

## Conventions

- **Minimal diffs** — match existing patterns; don't refactor unrelated code.
- **API auth** — tests and dev use header `X-Api-Token: dev-token`.
- **Settings** — stored in SQLite (`backend/app.db`); no restart after settings changes.
- **Routes** — consolidated in `backend/app/api/routes/api.py` (+ `chat.py` for chat).
- **Providers** — register in `backend/app/providers/registry.py`; use `FakeProvider` in tests.
- **No commits** unless the user explicitly asks.

## Testing

See [docs/TESTING.md](docs/TESTING.md) for full commands. Summary:

- Run pytest from `backend/` using `backend/.venv/bin/pytest`.
- System Python 3.9 lacks `ptyprocess` — use the project venv (Python 3.12+).
- Automated tests monkeypatch native dialogs; real Finder is manual only (below).

## Manual verification — macOS folder picker

Automated tests **never** open Finder. They monkeypatch `app.tools.dialog_service.pick_directory`.

To verify Browse on a real desktop:

1. `./scripts/server.sh start-all`
2. Open http://localhost:5177 → Manage Projects → Add Project → **Browse**
3. Confirm macOS folder picker opens; selected path fills the workspace field
4. Confirm other API calls (health, settings) still respond while picker is open

## WebSocket — React Strict Mode (dev only)

In development, React Strict Mode double-mounts components. You may see benign console warnings such as *"WebSocket is closed before the connection is established"* when WS hooks unmount/remount. Production builds are unaffected; reconnect logic handles transient closes.

## Stub workbench data

The Reporting panel uses a stub HTTP API until persistent storage exists. See [docs/KANBAN_STUB_DATA.md](docs/KANBAN_STUB_DATA.md).

## Verification workflow

Before claiming a task complete, follow:

1. [docs/VERIFICATION_RULES.md](docs/VERIFICATION_RULES.md) (includes agent completion checklist and five-pass honesty gate)
2. [docs/QUALITY_GATEWAY.md](docs/QUALITY_GATEWAY.md)
3. [docs/TASK_VERIFICATION_TEMPLATE.md](docs/TASK_VERIFICATION_TEMPLATE.md)

See also [docs/COMPREHENSIVE_RULES_AND_GUIDELINES.md](docs/COMPREHENSIVE_RULES_AND_GUIDELINES.md) and [Cursor_Guide.md](Cursor_Guide.md).
