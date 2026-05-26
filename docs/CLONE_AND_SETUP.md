# Clone and Setup on a New PC

This guide helps you clone and run `AI_Copilot` on another computer.

## 1) Requirements

Install these first:

- Git
- Python 3.12+
- Node.js 20+ (includes `npm`)

Optional (for live AI models):

- LM Studio or Ollama

## 2) Clone from GitHub

```bash
git clone https://github.com/hamedmirza/AI_Copilot.git
cd AI_Copilot
```

## 3) First-Time Setup

```bash
# Create local environment file
cp .env.example .env

# Install frontend dependencies
npm --prefix frontend install
```

Notes:

- The backend virtual environment is created automatically when you first start the servers.
- Default ports are fixed by project scripts:
  - Backend: `8500`
  - Frontend: `5177`

## 4) Start the App

```bash
./scripts/server.sh start-all
```

Open:

- http://localhost:5177

Useful server commands:

```bash
./scripts/server.sh status
./scripts/server.sh stop
./scripts/server.sh restart
```

## 5) Verify It Works

Quick checks:

- Frontend opens on `http://localhost:5177`
- Backend health/API responds on port `8500`
- You can complete onboarding in the UI

## 6) Run Tests (Recommended)

```bash
# Backend tests (must use project venv)
cd backend && .venv/bin/pytest
```

```bash
# Frontend production build check
cd ..
npm --prefix frontend run build
```

## 7) Pull New Changes Later

From inside the repo:

```bash
git pull origin main
```

## Troubleshooting

- **`python` version too old**: ensure Python 3.12+ is installed and used.
- **`npm` not found**: install Node.js 20+.
- **Port already in use**: free ports `8500` and `5177`, then rerun `./scripts/server.sh start-all`.
- **Model connection issues**: start LM Studio/Ollama and confirm provider URL in app settings.
