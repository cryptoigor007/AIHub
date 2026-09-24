#!/bin/bash
# Ждёт готовности gatekeeper (после start_all), чтобы не дёргать smoke вручную
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
# shellcheck source=scripts/lib_env.sh
source "$ROOT/scripts/lib_env.sh"
aihub_load_env
HOST="$(aihub_gk_host)"
PORT="$(aihub_gk_port)"
PY="$(aihub_python)"
URL="http://${HOST}:${PORT}/health"
MAX="${1:-60}"
echo "ждём $URL до ${MAX}s..."
for i in $(seq 1 "$MAX"); do
  if curl -sf --max-time 2 "$URL" >/dev/null 2>&1; then
    echo "ready за ${i}s"
    curl -sf "$URL" | "$PY" -m json.tool 2>/dev/null || true
    exit 0
  fi
  sleep 1
done
echo "FAIL: не готов за ${MAX}s"
exit 1
