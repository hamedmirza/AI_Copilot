#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/backend"
COMMIT="$(git -C "$ROOT" rev-parse --short HEAD 2>/dev/null || echo unknown)"
echo "pipeline_matrix_report commit=$COMMIT"
echo "scenario_id,repo_mode,task_kind,terminal_status,blocking_event"
log="$(mktemp)"
trap 'rm -f "$log"' EXIT
PIPELINE_MATRIX_CSV=1 .venv/bin/pytest tests/test_pipeline_e2e_matrix.py -q -s --capture=no >"$log" 2>&1
grep -E '^M[0-9]{2},' "$log"
grep -E 'passed in' "$log" || true
