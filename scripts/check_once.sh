#!/bin/bash
# ОДИН прогон всего, что можно проверить автоматически.
# Не нужно гонять 200 раз одно и то же — смотрите итоговую матрицу.
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
mkdir -p data

# shellcheck source=scripts/lib_env.sh
source "$ROOT/scripts/lib_env.sh"
PY="$(aihub_python)"

echo "╔══════════════════════════════════════════╗"
echo "║  AIHub check_once — полный автопрогон   ║"
echo "╚══════════════════════════════════════════╝"
echo ""

STEP=0
run() {
  STEP=$((STEP+1))
  echo ""
  echo "▶ [$STEP] $1"
  echo "────────────────────────────────────────"
  shift
  if "$@"; then
    echo "✓ ok"
    return 0
  else
    echo "✗ fail (продолжение)"
    return 0  # не останавливаем весь прогон
  fi
}

run "validate_env" bash -c "PYTHONPATH='$ROOT' '$PY' scripts/validate_env.py"
run "unit tests" bash -c "set -o pipefail; PYTHONPATH='$ROOT' '$PY' -m pytest tests/ -q --tb=line 2>&1 | tail -20"
run "probe_cli (dsh/opencode --help)" bash scripts/probe_cli.sh
run "probe_token" "$PY" scripts/probe_token.py
run "tailscale (mesh)" bash -c 'command -v tailscale >/dev/null && tailscale status --self 2>&1 | head -3 || echo "no tailscale CLI"'

run "wait_ready (если gatekeeper стартует)" bash -c "scripts/wait_ready.sh 15 || true"
run "doctor" bash scripts/doctor.sh
run "smoke" bash scripts/smoke.sh
run "acceptance" bash scripts/acceptance.sh

echo ""
echo "╔══════════════════════════════════════════╗"
echo "║  Готово. Отчёты:                         ║"
echo "║  data/acceptance_report.txt              ║"
echo "║  data/probes/                            ║"
echo "║                                          ║"
echo "║  Ручное (один раз в Telegram):           ║"
echo "║  0) дома: LAN URL из status (без TS)     ║"
echo "║  1) кнопка AIHub (вне дома + Tailscale)  ║"
echo "║  2) видны агенты                         ║"
echo "║  3) send/interrupt                       ║"
echo "║  4) «Полный интерфейс» DSH               ║"
echo "║  5) после смены tunnel — кнопка жива     ║"
echo "╚══════════════════════════════════════════╝"
