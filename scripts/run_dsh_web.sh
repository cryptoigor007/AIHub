#!/bin/bash
# Запуск dsh web (один экземпляр на хранилище: если порт занят — ждём).
# ТЗ: не использовать --trusted-host.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
# shellcheck source=scripts/lib_env.sh
source "$ROOT/scripts/lib_env.sh"
aihub_load_env

export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

HOST="${DSH_WEB_HOST:-127.0.0.1}"
PORT="${DSH_WEB_PORT:-3080}"

DSH_BIN="${DSH_BIN:-$(command -v dsh || true)}"
if [ -z "$DSH_BIN" ]; then
  # Типичный путь npm global
  if [ -x /opt/homebrew/lib/node_modules/@deepseek-ai/dsh/bin/dsh ]; then
    DSH_BIN=/opt/homebrew/lib/node_modules/@deepseek-ai/dsh/bin/dsh
  elif command -v npx &>/dev/null; then
    DSH_BIN="npx --yes @deepseek-ai/dsh"
  else
    echo "dsh not found" >&2
    exit 1
  fi
fi

LOG="${DSH_WEB_LOG:-$HOME/.dsh/web.log}"
mkdir -p "$(dirname "$LOG")"

# KeepAlive-сервис: не поднимаем второй экземпляр на занятом порту.
aihub_wait_port_free "$HOST" "$PORT" "run_dsh_web"

# Запуск web-интерфейса. Точные флаги — проверить на месте (docs/ON_SITE.md).
# Не передаём --trusted-host.
exec $DSH_BIN web --host "$HOST" --port "$PORT" >>"$LOG" 2>&1
