#!/bin/bash
# Снимает --help у dsh/opencode и подсказывает флаги для run_*.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
OUT_DIR="$ROOT/data/probes"
mkdir -p "$OUT_DIR"

export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

echo "=== probe CLI ==="

probe_bin() {
  local name="$1"
  local bin
  bin="$(command -v "$name" 2>/dev/null || true)"
  if [ -z "$bin" ]; then
    echo "[!] $name не в PATH"
    return 1
  fi
  echo "[ok] $name → $bin"
  echo "  version: $($bin --version 2>&1 | head -1 || true)"
  return 0
}

probe_bin dsh || true
probe_bin opencode || true
probe_bin cloudflared || true

echo ""
echo "--- dsh web --help (первые 40 строк) ---"
if command -v dsh >/dev/null 2>&1; then
  dsh web --help 2>&1 | head -40 | tee "$OUT_DIR/dsh_web_help.txt" || true
  echo ""
  echo "Ищите флаги: --host / --hostname / --port / --bind"
  echo "Текущий run_dsh_web.sh:"
  grep -E 'exec|web |--' "$ROOT/scripts/run_dsh_web.sh" || true
else
  echo "dsh нет — пропуск"
fi

echo ""
echo "--- opencode serve --help (первые 40 строк) ---"
if command -v opencode >/dev/null 2>&1; then
  opencode serve --help 2>&1 | head -40 | tee "$OUT_DIR/opencode_serve_help.txt" || true
  echo ""
  echo "Ищите флаги: --hostname / --host / --port"
  echo "Текущий run_opencode.sh:"
  grep -E 'exec|serve|--' "$ROOT/scripts/run_opencode.sh" || true
else
  echo "opencode нет — пропуск"
fi

echo ""
echo "Полный вывод сохранён в data/probes/"
echo "=== конец probe_cli ==="
