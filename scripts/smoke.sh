#!/bin/bash
# Быстрый smoke после start_all — один проход, матрица PASS/FAIL
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
BASE="http://${HOST}:${PORT}"
PASS=0
FAIL=0
WARN=0

ok()  { echo "  [PASS] $1"; PASS=$((PASS+1)); }
bad() { echo "  [FAIL] $1 — $2"; FAIL=$((FAIL+1)); }
wrn() { echo "  [WARN] $1 — $2"; WARN=$((WARN+1)); }

# HTTP-код без -f: 404/401 тоже валидные ответы; пусто/сбой → 000
http_code() {
  local code
  code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 "$@" 2>/dev/null || true)
  echo "${code:-000}"
}

echo "=== smoke ${BASE} ==="

# 1. health
HJSON=$(curl -sf --max-time 5 "${BASE}/health" 2>/dev/null || true)
if [ -n "$HJSON" ]; then
  ok "GET /health"
  echo "$HJSON" | "$PY" -m json.tool 2>/dev/null | head -20 || echo "$HJSON"
  if echo "$HJSON" | "$PY" -c "import sys,json; sys.exit(0 if json.load(sys.stdin).get('status')=='ok' else 1)" 2>/dev/null; then
    ok "health status=ok"
  else
    bad "health status" "$HJSON"
  fi
  echo "$HJSON" | grep -q '3\.6' && ok "version present" || wrn "version" "не найдена 3.6.x"
else
  bad "GET /health" "нет ответа (gatekeeper не запущен?)"
fi

# 2. secret path from health or .env
SECRET="${SECRET_PATH:-}"
if [ -z "$SECRET" ] || [ "$SECRET" = "/p/xxxxxxxx" ]; then
  SECRET=$(echo "$HJSON" | "$PY" -c "import sys,json; d=json.load(sys.stdin); print(d.get('secret_path') or '')" 2>/dev/null || true)
fi
if [ -z "$SECRET" ]; then
  # try validate_env
  SECRET=$(PYTHONPATH="$ROOT" "$PY" -c "
from src.common.config import get_settings
s=get_settings(); print(s.secret_path)
" 2>/dev/null || true)
fi
echo "  SECRET_PATH=${SECRET:-?}"

if [ -n "$SECRET" ] && [ "$SECRET" != "/p/xxxxxxxx" ]; then
  ok "SECRET_PATH известен"
  # 3. UI
  CODE=$(http_code "${BASE}${SECRET}/")
  [ "$CODE" = "200" ] && ok "GET ${SECRET}/ → 200" || bad "GET UI" "HTTP $CODE"

  # 4. catch-all 404
  CODE=$(http_code "${BASE}/no-such-path-xyz")
  [ "$CODE" = "404" ] && ok "чужой путь → 404" || wrn "чужой путь" "HTTP $CODE (ожидали 404)"

  # 5. локальный вход (LOCAL_LOGIN: off/loopback/lan)
  CODE=$(curl -s -c /tmp/aihub_dev_cookie -o /dev/null -w "%{http_code}" -X POST --max-time 5 \
    "${BASE}${SECRET}/auth/dev" 2>/dev/null || true)
  CODE="${CODE:-000}"
  if [ "$CODE" = "200" ]; then
    ok "POST auth/dev → cookie (LOCAL_LOGIN)"
    CODE=$(http_code -b /tmp/aihub_dev_cookie "${BASE}${SECRET}/api/agents")
    [ "$CODE" = "200" ] && ok "GET /api/agents с cookie" || bad "api/agents" "HTTP $CODE"
    CODE=$(curl -s -o /tmp/aihub_diag.json -w "%{http_code}" --max-time 5 \
      -b /tmp/aihub_dev_cookie "${BASE}${SECRET}/api/diag" 2>/dev/null || true)
    CODE="${CODE:-000}"
    [ "$CODE" = "200" ] && ok "GET /api/diag" || bad "api/diag" "HTTP $CODE"
    if [ -f /tmp/aihub_diag.json ]; then
      "$PY" -m json.tool /tmp/aihub_diag.json 2>/dev/null | head -30 || true
    fi
  else
    wrn "auth/dev" "HTTP $CODE (LOCAL_LOGIN=${LOCAL_LOGIN:-loopback})"
  fi
else
  bad "SECRET_PATH" "не задан — запустите gatekeeper хотя бы раз"
fi

# 6. upstream
DSH_PORT="${DSH_WEB_PORT:-3080}"
OC_PORT="${OPENCODE_SERVE_PORT:-4096}"
CODE=$(http_code "http://127.0.0.1:${DSH_PORT}/")
[ "$CODE" != "000" ] && ok "DSH :${DSH_PORT} HTTP $CODE" || wrn "DSH" "offline (нормально, если ещё не стартовал)"
CODE=$(http_code "http://127.0.0.1:${OC_PORT}/global/health")
if [ "$CODE" = "000" ]; then
  CODE=$(http_code "http://127.0.0.1:${OC_PORT}/")
fi
[ "$CODE" != "000" ] && ok "OpenCode :${OC_PORT} HTTP $CODE" || wrn "OpenCode" "offline"

# 7. kill switch
if [ -f .kill ] || [ -f "$HOME/AIHub/.kill" ]; then
  wrn ".kill" "АКТИВЕН — все запросы 503"
else
  ok ".kill отсутствует"
fi

echo ""
echo "=== итог: PASS=$PASS  FAIL=$FAIL  WARN=$WARN ==="
[ "$FAIL" -eq 0 ] && exit 0 || exit 1
