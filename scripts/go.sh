#!/usr/bin/env bash
# Идемпотентный старт + статус + открытие URL
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=lib_env.sh
source "$ROOT/scripts/lib_env.sh" 2>/dev/null || true

if ! curl -sf "http://127.0.0.1:${GATEKEEPER_PORT:-8787}/health" >/dev/null 2>&1; then
  echo "→ start_all"
  bash "$ROOT/scripts/start_all.sh" || true
  bash "$ROOT/scripts/wait_ready.sh" 2>/dev/null || sleep 3
fi

bash "$ROOT/scripts/status.sh" 2>/dev/null || true
bash "$ROOT/scripts/open_url.sh" 2>/dev/null || true
