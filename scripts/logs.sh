#!/bin/bash
# Хвосты логов всех сервисов AIHub
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOG_DIR="${LOG_DIR:-$HOME/Library/Logs/AIHub}"
LINES="${1:-80}"

echo "=== logs (last $LINES) dir=$LOG_DIR ==="
for f in gatekeeper dsh-web opencode tunnel-watcher aggregator; do
  for ext in out err; do
    path="$LOG_DIR/$f.$ext.log"
    if [ -f "$path" ]; then
      echo ""
      echo "----- $f.$ext.log -----"
      tail -n "$LINES" "$path" 2>/dev/null || true
    fi
  done
done

if [ -f .env ]; then
  # shellcheck disable=SC1091
  set -a; source .env; set +a
fi
DSH_LOG="${DSH_WEB_LOG:-$HOME/.dsh/web.log}"
if [ -f "$DSH_LOG" ]; then
  echo ""
  echo "----- dsh web.log (last 30) -----"
  tail -n 30 "$DSH_LOG" 2>/dev/null || true
fi
echo "=== конец logs ==="
