#!/bin/bash
# Полная диагностика AIHub — один проход, всё важное
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
VER="$(cat VERSION 2>/dev/null || echo '?')"

echo "=== AIHub doctor v${VER} ==="
echo "pwd: $ROOT"
echo "time: $(date -Iseconds 2>/dev/null || date)"
echo ""

# shellcheck source=scripts/lib_env.sh
source "$ROOT/scripts/lib_env.sh"
PY="$(aihub_python)"

# --- env ---
if [ -f .env ]; then
  echo "[ok] .env есть"
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
else
  echo "[!] нет .env — cp .env.example .env (секреты настраиваются мастером: ./scripts/setup.sh)"
fi

# v3.6.0: секреты живут в vault, в .env их нет — добираем оттуда (пусто = недоступен)
TOKEN_VAL="${TELEGRAM_BOT_TOKEN:-$(aihub_vault_get TELEGRAM_BOT_TOKEN)}"
SECRET_PATH="${SECRET_PATH:-$(aihub_vault_get SECRET_PATH)}"
OWNER="${OWNER_TELEGRAM_ID:-$(aihub_vault_get OWNER_TELEGRAM_ID)}"

echo "ENV=${ENV:-production}"
echo "SECRET_PATH=${SECRET_PATH:-?}"
echo "PUBLIC_URL=${PUBLIC_URL:-не задан}"
echo "NETWORK_MODE=${NETWORK_MODE:-hybrid}"
echo ""
echo "--- сеть (hybrid = LAN + Tailscale mesh) ---"
MODE="${NETWORK_MODE:-hybrid}"
echo "режим: $MODE"
echo "дома в Wi‑Fi: LAN без Tailscale (URL: ./scripts/status.sh)"
if [ "$MODE" = "cloudflare" ]; then
  echo -n "cloudflared: "
  command -v cloudflared >/dev/null && cloudflared --version 2>&1 | head -1 || echo "НЕ НАЙДЕН (brew install cloudflared)"
else
  echo -n "tailscale: "
  if command -v tailscale >/dev/null; then
    tailscale status --self 2>&1 | head -3 || tailscale status 2>&1 | head -3
    echo -n "serve: "
    tailscale serve status 2>&1 | head -5 || echo "(не настроен — ./scripts/enable_tailscale_serve.sh)"
  else
    echo "НЕ УСТАНОВЛЕН — https://tailscale.com/download/mac"
  fi
  if echo "${PUBLIC_URL:-}" | grep -q trycloudflare; then
    echo "[!] PUBLIC_URL указывает на trycloudflare при MODE=tailscale — перезапустите enable_tailscale_serve.sh"
  fi
fi
echo "TOKEN_SET=$([ -n "${TOKEN_VAL:-}" ] && echo yes || echo NO)"
echo "OWNER=${OWNER:-?}"
echo ""

# --- bins ---
echo "--- бинарники ---"
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"  # как в run_*.sh
echo -n "Python (.venv/system): "; "$PY" --version 2>&1 || echo "НЕТ"
echo -n "opencode: "; command -v opencode >/dev/null && opencode --version 2>&1 | head -1 || echo "не найден в PATH"
echo -n "dsh: "; command -v dsh >/dev/null && dsh --version 2>&1 | head -1 || echo "не найден в PATH"
echo -n "websockets (pip): "; "$PY" -c "import websockets; print(websockets.__version__)" 2>/dev/null || echo "НЕТ — pip install websockets"
echo ""

# --- validate_env ---
echo "--- validate_env ---"
PYTHONPATH="$ROOT" "$PY" scripts/validate_env.py 2>&1 || true
echo ""

# --- health ---
# 0.0.0.0 → 127.0.0.1 для локального curl
HOST="${GATEKEEPER_HOST:-127.0.0.1}"
if [ "$HOST" = "0.0.0.0" ] || [ "$HOST" = "::" ]; then HOST="127.0.0.1"; fi
PORT="${GATEKEEPER_PORT:-8787}"
echo "--- health gatekeeper :${PORT} ---"
if curl -sf --max-time 5 "http://${HOST}:${PORT}/health" | "$PY" -m json.tool 2>/dev/null; then
  :
else
  echo "[!] gatekeeper не отвечает на http://${HOST}:${PORT}/health"
  echo "    → ./scripts/start_all.sh  или смотрите logs: ./scripts/logs.sh"
fi
echo ""

# --- upstream ---
code_of() { curl -s -o /dev/null -w "%{http_code}" --max-time 3 "$1" 2>/dev/null || true; }
echo "--- DSH :${DSH_WEB_PORT:-3080} ---"
CODE=$(code_of "http://127.0.0.1:${DSH_WEB_PORT:-3080}/"); CODE="${CODE:-000}"
case "$CODE" in
  000) echo "offline" ;;
  401|403) echo "HTTP $CODE — жив, нужен токен DSH (AIHub берёт его из web.log — норма)" ;;
  *) echo "HTTP $CODE" ;;
esac
echo "--- OpenCode :${OPENCODE_SERVE_PORT:-4096} ---"
CODE=$(code_of "http://127.0.0.1:${OPENCODE_SERVE_PORT:-4096}/api/info"); CODE="${CODE:-000}"
[ "$CODE" = "404" ] && CODE=$(code_of "http://127.0.0.1:${OPENCODE_SERVE_PORT:-4096}/global/health")
case "$CODE" in
  000) echo "offline" ;;
  401|403) echo "HTTP $CODE — жив, Basic Auth (AIHub берёт пароль из vault — норма)" ;;
  *) echo "HTTP $CODE" ;;
esac
echo ""

# --- token ---
echo "--- DSH token probe ---"
"$PY" scripts/probe_token.py 2>&1 || true
echo ""

# --- kill ---
echo "--- .kill ---"
if [ -f .kill ] || [ -f "$HOME/AIHub/.kill" ]; then
  echo "АКТИВЕН — touch снят: rm -f .kill ~/AIHub/.kill"
else
  echo "нет (норма)"
fi
echo ""

# --- vault ---
echo "--- vault ---"
if [ -f data/vault.enc ]; then
  "$PY" scripts/vault_cli.py status 2>&1 | head -8 || echo "[!] vault есть, но не читается"
else
  echo "[!] vault нет — ./scripts/setup.sh"
fi
echo ""

# --- launchd ---
echo "--- launchd ---"
for s in dsh-web opencode gatekeeper tunnel-watcher; do
  if launchctl list 2>/dev/null | grep -q "ai.aihub.$s"; then
    echo "[ok] ai.aihub.$s"
  else
    echo "[ ] ai.aihub.$s не загружен"
  fi
done
if launchctl list 2>/dev/null | grep -q "ai.aihub.aggregator"; then
  echo "[!] ai.aihub.aggregator ЗАГРУЖЕН — это дубль! unload:"
  echo "    launchctl unload ~/Library/LaunchAgents/ai.aihub.aggregator.plist"
fi
echo ""

# --- recent errors in logs ---
LOG_DIR="${LOG_DIR:-$HOME/Library/Logs/AIHub}"
echo "--- ошибки в логах (если есть) ---"
if [ -d "$LOG_DIR" ]; then
  grep -h -iE 'error|traceback|exception|401|502|503' "$LOG_DIR"/*.err.log 2>/dev/null | tail -15 || echo "(нет err или пусто)"
else
  echo "каталог логов $LOG_DIR ещё не создан"
fi
echo ""

echo "=== дальше ==="
echo "  ./scripts/smoke.sh          — матрица HTTP"
echo "  ./scripts/acceptance.sh     — полная приёмка"
echo "  ./scripts/probe_cli.sh      — флаги dsh/opencode"
echo "  ./scripts/logs.sh           — хвосты логов"
echo "  ./scripts/check_once.sh     — ВСЁ сразу один раз"
echo "=== конец doctor ==="
