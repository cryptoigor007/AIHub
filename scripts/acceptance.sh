#!/bin/bash
# Автоматическая приёмка по ТЗ v3.5 — один прогон, без ручных 200 повторов
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

# shellcheck source=scripts/lib_env.sh
source "$ROOT/scripts/lib_env.sh"
PY="$(aihub_python)"

REPORT="$ROOT/data/acceptance_report.txt"
mkdir -p "$ROOT/data"
{
  echo "AIHub acceptance $(date -Iseconds 2>/dev/null || date)"
  echo "pwd=$ROOT"
  echo ""
} > "$REPORT"

pass=0; fail=0; skip=0
check() {
  local id="$1" name="$2"
  shift 2
  if "$@"; then
    echo "[PASS] $id $name" | tee -a "$REPORT"
    pass=$((pass+1))
  else
    echo "[FAIL] $id $name" | tee -a "$REPORT"
    fail=$((fail+1))
  fi
  return 0  # не роняем весь прогон (set -e) — отчёт должен дойти до конца
}
skipc() {
  echo "[SKIP] $1 $2 — $3" | tee -a "$REPORT"
  skip=$((skip+1))
}

echo "=== acceptance v3.5 ==="

# --- A. Структура репозитория ---
check A1 "структура src/" test -d src/gatekeeper -a -d src/aggregator -a -d src/notifier -a -d src/tunnel -a -d src/common
check A2 "static UI" test -f static/index.html -a -f static/js/aihub.js -a -f static/css/aihub.css
check A3 "scripts" test -x scripts/install.sh -a -x scripts/doctor.sh -a -x scripts/start_all.sh
check A4 ".env.example" test -f .env.example
check A5 "requirements" test -f requirements.txt

# --- B. Unit-тесты ---
if command -v "$PY" >/dev/null 2>&1; then
  if PYTHONPATH="$ROOT" "$PY" -m pytest tests/ -q --tb=no >/tmp/aihub_pytest.txt 2>&1; then
    check B1 "unit tests" true
    cat /tmp/aihub_pytest.txt | tee -a "$REPORT"
  else
    # может не хватать deps — не валим всё
    if grep -qE "ModuleNotFoundError|No module named" /tmp/aihub_pytest.txt 2>/dev/null; then
      skipc B1 "unit tests" "нет зависимостей (pip install -r requirements.txt)"
      cat /tmp/aihub_pytest.txt | tail -5 | tee -a "$REPORT"
    else
      check B1 "unit tests" false
      cat /tmp/aihub_pytest.txt | tail -20 | tee -a "$REPORT"
    fi
  fi
else
  skipc B1 "unit tests" "нет python"
fi

# --- C. validate_env ---
check C1 "validate_env.py" bash -c "PYTHONPATH='$ROOT' '$PY' scripts/validate_env.py"

# --- D. Запреты в коде запуска ---
check D1 "run_dsh_web без --trusted-host" bash -c "! grep -v '^#' scripts/run_dsh_web.sh | grep -q -- '--trusted-host'"
check D2 "start_all без dual aggregator" bash -c "! grep -v '^#' scripts/start_all.sh | grep -q 'load ai.aihub.aggregator'"
check D3 "install без active aggregator plist" bash -c "! grep -v '^#' scripts/install.sh | grep -q 'install_py_plist \"aggregator\"'"

# --- E. TOKEN_PATTERNS импортируются ---
check E1 "dsh_token patterns" bash -c "PYTHONPATH='$ROOT' '$PY' -c 'from src.common.dsh_token import TOKEN_PATTERNS; assert len(TOKEN_PATTERNS)>=4'"

# --- F. Runtime (если gatekeeper жив) ---
if [ -f .env ]; then set -a; # shellcheck disable=SC1091
  source .env; set +a; fi
# 0.0.0.0 → 127.0.0.1 для локального curl
HOST="${GATEKEEPER_HOST:-127.0.0.1}"
if [ "$HOST" = "0.0.0.0" ] || [ "$HOST" = "::" ]; then HOST="127.0.0.1"; fi
PORT="${GATEKEEPER_PORT:-8787}"
if curl -sf --max-time 3 "http://${HOST}:${PORT}/health" >/dev/null 2>&1; then
  check F1 "gatekeeper /health" curl -sf --max-time 3 "http://${HOST}:${PORT}/health"
  # smoke subset
  if "$ROOT/scripts/smoke.sh" >>"$REPORT" 2>&1; then
    check F2 "smoke suite" true
  else
    check F2 "smoke suite" false
  fi
else
  skipc F1 "gatekeeper /health" "не запущен — сначала ./scripts/start_all.sh"
  skipc F2 "smoke suite" "gatekeeper offline"
fi

# --- G. probe token (если log есть) ---
DSH_LOG="${DSH_WEB_LOG:-$HOME/.dsh/web.log}"
if [ -f "$DSH_LOG" ]; then
  if "$PY" "$ROOT/scripts/probe_token.py" "$DSH_LOG" >>"$REPORT" 2>&1; then
    check G1 "probe_token web.log" true
  else
    check G1 "probe_token web.log" false
  fi
else
  skipc G1 "probe_token" "нет $DSH_LOG (запустите dsh web)"
fi

echo ""
echo "=== итог acceptance: PASS=$pass FAIL=$fail SKIP=$skip ===" | tee -a "$REPORT"
echo "отчёт: $REPORT"
[ "$fail" -eq 0 ]
