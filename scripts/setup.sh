#!/bin/bash
# Первый запуск: мастер настройки Telegram + шифрованного хранилища.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
# shellcheck source=scripts/lib_env.sh
source "$ROOT/scripts/lib_env.sh"
PY="$(aihub_python)"
exec "$PY" "$ROOT/scripts/setup_wizard.py" "$@"
