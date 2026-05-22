#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PID_FILE="/tmp/ai-copilot.pid"
FRONTEND_PID_FILE="/tmp/ai-copilot-frontend.pid"
PORT=8500
FRONTEND_PORT=5177
HOST="${HOST:-0.0.0.0}"
BACKEND_RELOAD="${BACKEND_RELOAD:-0}"
LOG_DIR="$ROOT/logs"
LOG_FILE="$LOG_DIR/server.log"
FRONTEND_LOG_FILE="$LOG_DIR/frontend.log"

cd "$ROOT"

ensure_venv() {
  if [[ ! -d "$ROOT/backend/.venv" ]]; then
    python3 -m venv "$ROOT/backend/.venv"
    "$ROOT/backend/.venv/bin/pip" install -q -e "$ROOT/backend[dev]"
  fi
}

port_pid() {
  local port="$1"
  if ! command -v lsof >/dev/null 2>&1; then
    return 1
  fi
  lsof -ti tcp:"$port" -sTCP:LISTEN 2>/dev/null | head -n 1
}

is_running() {
  if [[ -f "$PID_FILE" ]]; then
    local pid
    pid=$(cat "$PID_FILE")
    if kill -0 "$pid" 2>/dev/null; then
      return 0
    fi
    rm -f "$PID_FILE"
  fi
  local pid
  pid=$(port_pid "$PORT" || true)
  if [[ -n "$pid" ]]; then
    echo "$pid" >"$PID_FILE"
    return 0
  fi
  return 1
}

is_frontend_running() {
  if [[ -f "$FRONTEND_PID_FILE" ]]; then
    local pid
    pid=$(cat "$FRONTEND_PID_FILE")
    if kill -0 "$pid" 2>/dev/null; then
      return 0
    fi
    rm -f "$FRONTEND_PID_FILE"
  fi
  local pid
  pid=$(port_pid "$FRONTEND_PORT" || true)
  if [[ -n "$pid" ]]; then
    echo "$pid" >"$FRONTEND_PID_FILE"
    return 0
  fi
  return 1
}

kill_port_strays() {
  local port="$1"
  if command -v lsof >/dev/null 2>&1; then
    local pids
    pids=$(lsof -ti tcp:"$port" 2>/dev/null || true)
    if [[ -n "$pids" ]]; then
      echo "$pids" | xargs kill -9 2>/dev/null || true
    fi
  fi
}

wait_for_health() {
  local attempts=30
  for ((i=1; i<=attempts; i++)); do
    if [[ -n "$(port_pid "$PORT" || true)" ]] && curl -sf --max-time 2 "http://127.0.0.1:${PORT}/api/health" >/dev/null 2>&1; then
      return 0
    fi
    sleep 0.5
  done
  return 1
}

wait_for_frontend() {
  local attempts=30
  for ((i=1; i<=attempts; i++)); do
    if curl -sf --max-time 2 "http://localhost:${FRONTEND_PORT}/" >/dev/null 2>&1; then
      return 0
    fi
    sleep 0.5
  done
  return 1
}

launch_detached() {
  local log_file="$1"
  shift
  python3 - "$log_file" "$@" <<'PY'
import os
import subprocess
import sys

log_path = sys.argv[1]
cmd = sys.argv[2:]
with open(log_path, "ab", buffering=0) as log:
    proc = subprocess.Popen(
        cmd,
        cwd=os.getcwd(),
        env=os.environ.copy(),
        stdin=subprocess.DEVNULL,
        stdout=log,
        stderr=log,
        start_new_session=True,
    )
print(proc.pid)
PY
}

cmd_start() {
  if is_running; then
    echo "Backend already running (pid $(cat "$PID_FILE"))"
    exit 0
  fi

  ensure_venv
  mkdir -p "$LOG_DIR"
  kill_port_strays "$PORT"

  export PYTHONPATH="$ROOT/backend"
  local uvicorn_args=(
    app.api.main:app
    --host "$HOST"
    --port "$PORT"
    --app-dir "$ROOT/backend"
  )
  if [[ "$BACKEND_RELOAD" == "1" ]]; then
    uvicorn_args+=(--reload)
  fi
  launch_detached "$LOG_FILE" "$ROOT/backend/.venv/bin/uvicorn" "${uvicorn_args[@]}" >"$PID_FILE"
  if wait_for_health; then
    echo "$(port_pid "$PORT")" >"$PID_FILE"
    echo "Backend started (pid $(cat "$PID_FILE")) on port $PORT"
  else
    echo "Backend failed health check — see $LOG_FILE"
    exit 1
  fi
}

cmd_start_frontend() {
  if is_frontend_running; then
    echo "Frontend already running (pid $(cat "$FRONTEND_PID_FILE")) on port $FRONTEND_PORT"
    exit 0
  fi

  if [[ ! -d "$ROOT/frontend/node_modules" ]]; then
    npm --prefix "$ROOT/frontend" install --silent
  fi

  mkdir -p "$LOG_DIR"
  kill_port_strays "$FRONTEND_PORT"

  launch_detached "$FRONTEND_LOG_FILE" npm --prefix "$ROOT/frontend" run dev >"$FRONTEND_PID_FILE"

  if wait_for_frontend; then
    echo "$(port_pid "$FRONTEND_PORT")" >"$FRONTEND_PID_FILE"
    echo "Frontend started (pid $(cat "$FRONTEND_PID_FILE")) on port $FRONTEND_PORT"
  else
    echo "Frontend failed to start on port $FRONTEND_PORT — see $FRONTEND_LOG_FILE"
    exit 1
  fi
}

cmd_start_all() {
  cmd_start
  cmd_start_frontend
}

cmd_stop_backend() {
  if [[ -f "$PID_FILE" ]]; then
    local pid
    pid=$(cat "$PID_FILE")
    if kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
      sleep 1
      kill -9 "$pid" 2>/dev/null || true
    fi
    rm -f "$PID_FILE"
  fi
  kill_port_strays "$PORT"
}

cmd_stop_frontend() {
  if [[ -f "$FRONTEND_PID_FILE" ]]; then
    local pid
    pid=$(cat "$FRONTEND_PID_FILE")
    if kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
      sleep 1
      kill -9 "$pid" 2>/dev/null || true
    fi
    rm -f "$FRONTEND_PID_FILE"
  fi
  kill_port_strays "$FRONTEND_PORT"
}

cmd_stop() {
  cmd_stop_backend
  cmd_stop_frontend
  echo "Servers stopped"
}

cmd_restart() {
  cmd_stop_backend
  sleep 1
  cmd_start
}

cmd_start_dev() {
  BACKEND_RELOAD=1 cmd_start
}

cmd_status() {
  if is_running; then
    echo "Backend: running (pid $(cat "$PID_FILE"), port $PORT)"
  else
    echo "Backend: not running"
  fi
  if is_frontend_running; then
    echo "Frontend: running (pid $(cat "$FRONTEND_PID_FILE"), port $FRONTEND_PORT)"
  else
    echo "Frontend: not running"
  fi
}

case "${1:-}" in
  start) cmd_start ;;
  start-dev) cmd_start_dev ;;
  start-frontend) cmd_start_frontend ;;
  start-all) cmd_start_all ;;
  stop) cmd_stop ;;
  restart) cmd_restart ;;
  status) cmd_status ;;
  *)
    echo "Usage: $0 {start|start-dev|start-frontend|start-all|stop|restart|status}"
    exit 1
    ;;
esac
