# Общие хелперы для shell-скриптов AIHub (source из других scripts)
# shellcheck shell=bash

aihub_load_env() {
  if [ -f .env ]; then
    set -a
    # shellcheck disable=SC1091
    source .env
    set +a
  fi
}

# Для curl на локальный gatekeeper: 0.0.0.0/:: → 127.0.0.1
aihub_gk_host() {
  local h="${GATEKEEPER_HOST:-127.0.0.1}"
  if [ "$h" = "0.0.0.0" ] || [ "$h" = "::" ] || [ "$h" = "[::]" ]; then
    echo "127.0.0.1"
  else
    echo "$h"
  fi
}

aihub_gk_port() {
  echo "${GATEKEEPER_PORT:-8787}"
}

# Порт занят? (чистый bash /dev/tcp, без внешних утилит)
aihub_port_busy() {
  local host="$1" port="$2"
  if (exec 3<>"/dev/tcp/${host}/${port}") 2>/dev/null; then
    exec 3>&- 2>/dev/null || true
    return 0
  fi
  return 1
}

# Ждать освобождения порта (для KeepAlive-сервисов: не поднимать дубль)
aihub_wait_port_free() {
  local host="$1" port="$2" name="$3"
  if ! aihub_port_busy "$host" "$port"; then
    return 0
  fi
  echo "[$name] ${host}:${port} уже занят — свой экземпляр работает, ждём" >&2
  while aihub_port_busy "$host" "$port"; do
    sleep 15
  done
  echo "[$name] порт ${port} освободился — стартуем" >&2
}

# Пароль opencode serve (V2 требует Basic Auth) — из шифрованного vault.
aihub_ensure_opencode_password() {
  local py val
  py="$(aihub_python)"
  val="${OPENCODE_SERVER_PASSWORD:-}"
  if [ -z "$val" ]; then
    val="$("$py" "$PWD/scripts/vault_cli.py" get OPENCODE_SERVER_PASSWORD 2>/dev/null || true)"
  fi
  if [ -z "$val" ]; then
    "$py" "$PWD/scripts/vault_cli.py" gen OPENCODE_SERVER_PASSWORD >/dev/null 2>&1 || true
    val="$("$py" "$PWD/scripts/vault_cli.py" get OPENCODE_SERVER_PASSWORD 2>/dev/null || true)"
    [ -n "$val" ] && echo "[lib_env] OPENCODE_SERVER_PASSWORD сгенерирован → vault" >&2
  fi
  if [ -z "$val" ]; then
    echo "[lib_env] ВНИМАНИЕ: vault недоступен — opencode serve стартует без пароля" >&2
  fi
  export OPENCODE_SERVER_PASSWORD="$val"
}

# Python для скриптов: .venv от install.sh, если есть; иначе системный python3
aihub_python() {
  if [ -x "$PWD/.venv/bin/python" ]; then
    echo "$PWD/.venv/bin/python"
  else
    echo "python3"
  fi
}

# Значение секрета из vault (пусто, если vault недоступен). Ключ — из ENV_SECRET_KEYS.
aihub_vault_get() {
  local py
  py="$(aihub_python)"
  "$py" "$PWD/scripts/vault_cli.py" get "$1" 2>/dev/null || true
}
