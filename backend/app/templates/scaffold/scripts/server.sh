#!/usr/bin/env bash
# {{PROJECT_NAME}} dev server helper
set -euo pipefail
case "${1:-status}" in
  start) echo "Start dev servers for {{PROJECT_NAME}}" ;;
  stop) echo "Stop dev servers" ;;
  *) echo "Usage: $0 start|stop|status" ;;
esac
