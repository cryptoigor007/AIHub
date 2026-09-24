#!/bin/bash
# Запуск opencode serve (V2 требует пароль — Basic Auth; пароль из vault).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
# shellcheck source=scripts/lib_env.sh
source "$ROOT/scripts/lib_env.sh"
aihub_load_env

export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

OC_BIN="${OC_BIN:-$(command -v opencode || true)}"
if [ -z "$OC_BIN" ]; then
  if [ -x /opt/homebrew/bin/opencode ]; then
    OC_BIN=/opt/homebrew/bin/opencode
  else
    echo "opencode not found" >&2
    exit 1
  fi
fi

PORT="${OPENCODE_SERVE_PORT:-4096}"
HOST="${OPENCODE_SERVE_HOST:-127.0.0.1}"

# V2: фиксируем пароль, чтобы gatekeeper (OPENCODE_SERVER_PASSWORD)
# мог авторизоваться. Если пусто — генерируем и сохраняем в vault.
aihub_ensure_opencode_password

# KeepAlive-сервис: не поднимаем второй экземпляр на занятом порту.
aihub_wait_port_free "$HOST" "$PORT" "run_opencode"

# Точные флаги — уточнить: opencode serve --help
exec "$OC_BIN" serve --hostname "$HOST" --port "$PORT"
