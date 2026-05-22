#!/usr/bin/env bash
# Watches AI Copilot logs and emits AGENT_LOOP_WAKE_logmonitor for the Cursor agent loop.
# See docs/LOG_MONITOR.md and .cursor/skills-cursor/loop/SKILL.md
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
STATE_FILE="/tmp/ai-copilot-log-monitor.state"
LAST_WAKE_FILE="/tmp/ai-copilot-log-monitor.lastwake"
PID_FILE="/tmp/ai-copilot-log-monitor.pid"
HEARTBEAT_PID_FILE="/tmp/ai-copilot-log-monitor-heartbeat.pid"
CURSOR_LOOP_PID_FILE="/tmp/ai-copilot-log-monitor-cursor.pid"
MONITOR_LOG="/tmp/ai-copilot-log-monitor.log"
SENTINEL="AGENT_LOOP_WAKE_logmonitor"
COOLDOWN_SECS="${COOLDOWN_SECS:-120}"
POLL_SECS="${POLL_SECS:-5}"
HEARTBEAT_SECS="${HEARTBEAT_SECS:-600}"
PROMPT='Review AI Copilot logs since the last check. Read logs/app.jsonl, logs/server.log, and logs/frontend.log for NEW errors, warnings, tracebacks, or connection failures. Summarize issues, note severity, and suggest fixes when actionable. Ignore routine INFO noise unless it indicates a problem.'

LOG_APP="$ROOT/logs/app.jsonl"
LOG_SERVER="$ROOT/logs/server.log"
LOG_FRONTEND="$ROOT/logs/frontend.log"

emit_wake() {
  local reason="${1:-new_log_activity}"
  printf '%s {"prompt":"%s","reason":"%s","cooldown_secs":%s}\n' \
    "$SENTINEL" "$PROMPT" "$reason" "$COOLDOWN_SECS"
}

last_wake_epoch() {
  if [[ -f "$LAST_WAKE_FILE" ]]; then
    cat "$LAST_WAKE_FILE"
  else
    echo 0
  fi
}

record_wake() {
  date +%s >"$LAST_WAKE_FILE"
}

# Returns 0 if cooldown elapsed and a wake may be emitted.
cooldown_ready() {
  local now last elapsed
  now=$(date +%s)
  last=$(last_wake_epoch)
  elapsed=$((now - last))
  if [[ "$elapsed" -ge "$COOLDOWN_SECS" ]]; then
    return 0
  fi
  return 1
}

emit_wake_if_ready() {
  local reason="$1"
  if cooldown_ready; then
    emit_wake "$reason"
    record_wake
    return 0
  fi
  return 1
}

is_issue_line() {
  local line="$1" file="${2:-}"
  # Suppress known Vite dev-server proxy noise from frontend.log — these are
  # transient reconnect failures, not real application errors.
  if [[ "$file" == *frontend.log* ]]; then
    if [[ "$line" =~ (ECONNREFUSED|ws[[:space:]]proxy[[:space:]]error|http[[:space:]]proxy[[:space:]]error) ]]; then
      return 1
    fi
  fi
  if [[ "$line" =~ \"level\":[[:space:]]*\"(error|warning|critical)\" ]]; then
    return 0
  fi
  if [[ "$line" =~ (Traceback|ERROR|CRITICAL|Exception|FAILED|ECONNREFUSED) ]]; then
    return 0
  fi
  return 1
}

init_state() {
  mkdir -p "$(dirname "$STATE_FILE")"
  : >"$STATE_FILE"
  for f in "$LOG_APP" "$LOG_SERVER" "$LOG_FRONTEND"; do
    if [[ -f "$f" ]]; then
      local lines
      lines=$(wc -l <"$f" | tr -d ' ')
      echo "$(basename "$f")=$lines" >>"$STATE_FILE"
    else
      echo "$(basename "$f")=0" >>"$STATE_FILE"
    fi
  done
}

read_offset() {
  local name="$1"
  grep -E "^${name}=" "$STATE_FILE" 2>/dev/null | tail -1 | cut -d= -f2 || echo 0
}

write_offset() {
  local name="$1" val="$2"
  if [[ ! -f "$STATE_FILE" ]]; then
    init_state
    return
  fi
  local tmp
  tmp=$(mktemp)
  awk -v n="$name" -v v="$val" '
    BEGIN { found=0 }
    $0 ~ "^" n "=" { print n "=" v; found=1; next }
    { print }
    END { if (!found) print n "=" v }
  ' "$STATE_FILE" >"$tmp" && mv "$tmp" "$STATE_FILE"
}

scan_new_lines() {
  local found=0
  local files=("$LOG_APP" "$LOG_SERVER" "$LOG_FRONTEND")
  for f in "${files[@]}"; do
    [[ -f "$f" ]] || continue
    local name offset new total slice
    name=$(basename "$f")
    offset=$(read_offset "$name")
    total=$(wc -l <"$f" | tr -d ' ')
    if [[ "$total" -le "$offset" ]]; then
      continue
    fi
    new=$((total - offset))
    slice=$(tail -n "$new" "$f")
    while IFS= read -r line; do
      if is_issue_line "$line" "$f"; then
        found=1
        break
      fi
    done <<<"$slice"
    write_offset "$name" "$total"
    if [[ "$found" -eq 1 ]]; then
      return 0
    fi
  done
  return 1
}

cmd_once() {
  [[ -f "$STATE_FILE" ]] || init_state
  if scan_new_lines; then
    if emit_wake_if_ready "scan_found_issues"; then
      return 0
    fi
    echo "log-monitor: issues found but cooldown active (${COOLDOWN_SECS}s)"
    return 0
  fi
  echo "log-monitor: no new issues ($(date -u +%Y-%m-%dT%H:%M:%SZ))"
  return 0
}

run_poll_loop() {
  local mode="$1"
  [[ -f "$STATE_FILE" ]] || init_state
  touch "$LOG_APP" "$LOG_SERVER" "$LOG_FRONTEND" 2>/dev/null || true
  local last_heartbeat=0
  while true; do
    local now
    now=$(date +%s)
    if scan_new_lines; then
      emit_wake_if_ready "watch_found_issues" || true
    fi
    if [[ "$mode" == "cursor" ]] || [[ "$mode" == "heartbeat" ]]; then
      if (( now - last_heartbeat >= HEARTBEAT_SECS )); then
        emit_wake_if_ready "heartbeat_full_scan" || true
        last_heartbeat=$now
      fi
    fi
    sleep "$POLL_SECS"
  done
}

cmd_watch() {
  echo $$ >"$PID_FILE"
  echo "log-monitor: watching logs (pid $$, cooldown ${COOLDOWN_SECS}s)"
  run_poll_loop watch
}

cmd_heartbeat() {
  echo $$ >"$HEARTBEAT_PID_FILE"
  run_poll_loop heartbeat
}

# Cursor agent loop (dynamic schedule): stdout sentinels for monitored shell.
# Regex for Cursor: ^AGENT_LOOP_WAKE_logmonitor
cmd_cursor_loop() {
  echo $$ >"$CURSOR_LOOP_PID_FILE"
  echo "log-monitor: Cursor dynamic loop (pid $$, sentinel $SENTINEL, cooldown ${COOLDOWN_SECS}s, heartbeat ${HEARTBEAT_SECS}s)"
  echo "log-monitor: arm with monitored background shell; pattern ^AGENT_LOOP_WAKE_logmonitor"
  run_poll_loop cursor
}

cmd_start() {
  cmd_stop
  [[ -f "$STATE_FILE" ]] || init_state
  mkdir -p "$(dirname "$MONITOR_LOG")"
  nohup env COOLDOWN_SECS="$COOLDOWN_SECS" "$0" watch >>"$MONITOR_LOG" 2>&1 &
  nohup env COOLDOWN_SECS="$COOLDOWN_SECS" HEARTBEAT_SECS="$HEARTBEAT_SECS" "$0" heartbeat >>"$MONITOR_LOG" 2>&1 &
  sleep 0.5
  if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    echo "log-monitor: started detached (watcher pid $(cat "$PID_FILE"), log $MONITOR_LOG)"
    echo "log-monitor: for Cursor wakes, also run: $0 cursor-loop (background shell in IDE)"
  else
    echo "log-monitor: failed to start — see $MONITOR_LOG"
    exit 1
  fi
}

cmd_status() {
  local w=stopped h=stopped c=stopped
  if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    w="running (pid $(cat "$PID_FILE"))"
  fi
  if [[ -f "$HEARTBEAT_PID_FILE" ]] && kill -0 "$(cat "$HEARTBEAT_PID_FILE")" 2>/dev/null; then
    h="running (pid $(cat "$HEARTBEAT_PID_FILE"))"
  fi
  if [[ -f "$CURSOR_LOOP_PID_FILE" ]] && kill -0 "$(cat "$CURSOR_LOOP_PID_FILE")" 2>/dev/null; then
    c="running (pid $(cat "$CURSOR_LOOP_PID_FILE"))"
  fi
  echo "Watcher: $w"
  echo "Heartbeat: $h"
  echo "Cursor loop: $c"
  echo "Cooldown: ${COOLDOWN_SECS}s | Log: $MONITOR_LOG"
  if [[ -f "$LAST_WAKE_FILE" ]]; then
    echo "Last wake epoch: $(cat "$LAST_WAKE_FILE")"
  fi
}

cmd_stop() {
  for f in "$PID_FILE" "$HEARTBEAT_PID_FILE" "$CURSOR_LOOP_PID_FILE"; do
    if [[ -f "$f" ]]; then
      local pid
      pid=$(cat "$f")
      if kill -0 "$pid" 2>/dev/null; then
        kill "$pid" 2>/dev/null || true
      fi
      rm -f "$f"
    fi
  done
  pkill -f "log-monitor-loop.sh watch" 2>/dev/null || true
  pkill -f "log-monitor-loop.sh heartbeat" 2>/dev/null || true
  pkill -f "log-monitor-loop.sh cursor-loop" 2>/dev/null || true
  echo "log-monitor: stopped"
}

case "${1:-}" in
  once) cmd_once ;;
  watch) cmd_watch ;;
  heartbeat) cmd_heartbeat ;;
  cursor-loop) cmd_cursor_loop ;;
  stop) cmd_stop ;;
  start) cmd_start ;;
  status) cmd_status ;;
  init) init_state ;;
  *)
    echo "Usage: $0 {once|watch|heartbeat|cursor-loop|start|stop|status|init}"
    exit 1
    ;;
esac
