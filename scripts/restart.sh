#!/bin/bash
# Чистый рестарт всех сервисов
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
echo "=== restart ==="
"$ROOT/scripts/stop_all.sh" || true
sleep 2
"$ROOT/scripts/start_all.sh"
echo "=== restart done ==="
