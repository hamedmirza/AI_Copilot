# AI Copilot IDE

A local VS Code-like IDE with an embedded 7-agent software team pipeline, remote LM Studio/Ollama support, and multi-project management.

## Prerequisites

- Python 3.12+
- Node.js 20+
- LM Studio (optional, for live LLM) — default LAN URL: `http://192.168.128.70:1234/v1`

## Quick Start

```bash
# 1. Copy environment bootstrap file
cp .env.example .env

# 2. Install frontend deps (once)
npm --prefix frontend install

# 3. Start backend + frontend (backend 8500, frontend 5177 — strict, no auto-increment)
./scripts/server.sh start-all
```

Open http://localhost:5177 — complete the onboarding wizard on first launch.

## Server Commands

```bash
./scripts/server.sh start-all       # Backend (8500) + frontend (5177)
./scripts/server.sh start           # Backend only
./scripts/server.sh start-frontend  # Frontend only (port 5177, strictPort)
./scripts/server.sh stop            # Stop both
./scripts/server.sh restart         # Restart backend
./scripts/server.sh status          # Status for both
```

## LM Studio Setup

1. Install LM Studio on your network PC
2. Load a model (recommended: `qwen2.5-coder-32b-instruct` for coding)
3. Enable **Start on LAN** (binds to `0.0.0.0:1234`)
4. In AI Copilot Settings (`Cmd+,`), verify URL: `http://192.168.128.70:1234/v1`
5. Click **Test Connection**

All runtime settings are stored in SQLite (`backend/app.db`) — no server restart needed after changes.

## Architecture

- **Backend:** FastAPI + SQLAlchemy + SQLite WAL (port 8500)
- **Frontend:** React 19 + Vite + Tailwind + Monaco + xterm.js (port 5177, strict)
- **Agents:** Planner → Architect → UI Designer → Coder → Reviewer → Tester → Supervisor
- **Real-time:** WebSocket `/ws/runs/{id}` and `/ws/events`

## Testing

```bash
cd backend && .venv/bin/pytest
npm --prefix frontend run build
```

## Documentation

- Master checklist: [docs/TASK_CHECKLIST.md](docs/TASK_CHECKLIST.md)
- Change requests: [docs/CHANGE_REQUESTS/](docs/CHANGE_REQUESTS/)

## First Run

<!-- Screenshots placeholder -->
_On first boot with no projects, the onboarding wizard guides LM Studio setup and first project creation._

## License

MIT
