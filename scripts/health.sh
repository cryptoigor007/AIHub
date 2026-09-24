#!/bin/bash
# Проверка здоровья AIHub
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

# shellcheck source=scripts/lib_env.sh
source "$ROOT/scripts/lib_env.sh"
aihub_load_env
# 0.0.0.0 → 127.0.0.1 для локального curl
HOST="$(aihub_gk_host)"
PORT="$(aihub_gk_port)"
PY="$(aihub_python)"

curl -sf "http://${HOST}:${PORT}/health" | "$PY" -m json.tool || {
  echo "FAIL: gatekeeper not responding"
  exit 1
}
