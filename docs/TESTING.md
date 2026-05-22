# Testing

## Backend (pytest)

Always use the project virtualenv. From the repo root:

```bash
cd backend && .venv/bin/pytest
```

Or activate first:

```bash
source backend/.venv/bin/activate
cd backend && pytest
```

If `.venv` does not exist, run `./scripts/server.sh start` once (creates venv and installs `backend[dev]`).

### Why not system Python?

The backend depends on `ptyprocess` (terminal PTY). **System Python 3.9** on macOS often fails tests with `ModuleNotFoundError: ptyprocess`. The project requires **Python 3.12+** via `backend/.venv`.

### Targeted runs

```bash
cd backend

# Full suite
.venv/bin/pytest

# API / dialog tests
.venv/bin/pytest tests/test_api.py -v

# Chat tests
.venv/bin/pytest tests/test_chat.py tests/test_chat_model_selection.py -v

# Single test
.venv/bin/pytest tests/test_api.py::test_pick_directory -v
```

Native folder picker tests use **monkeypatch** — they do not open Finder.

## Frontend

```bash
npm --prefix frontend run build    # tsc + vite production build
npm --prefix frontend run lint     # eslint (optional)
```

Dev server (strict port 5177):

```bash
./scripts/server.sh start-frontend
```

## Smoke after changes

```bash
./scripts/server.sh start-all
curl -s http://127.0.0.1:8500/api/health
# → {"status":"ok","version":"..."}
```
