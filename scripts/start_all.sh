#!/bin/bash
# Поднять все сервисы AIHub в правильном порядке
set -euo pipefail
PLIST_DIR="$HOME/Library/LaunchAgents"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
if [ ! -f data/vault.enc ]; then
  echo "⚠ vault не настроен — Telegram-бот работать не будет. Запустите: ./scripts/setup.sh"
fi


load() {
  local label="$1"
  local plist="$PLIST_DIR/$label.plist"
  if [ ! -f "$plist" ]; then
    echo "нет $plist — сначала ./scripts/install.sh"
    return 1
  fi
  launchctl unload "$plist" 2>/dev/null || true
  launchctl load "$plist"
  echo "loaded $label"
}

load ai.aihub.dsh-web
load ai.aihub.opencode
sleep 3
load ai.aihub.gatekeeper
# load ai.aihub.aggregator  # НЕ включать: дублирует poll/notify с gatekeeper
sleep 2
load ai.aihub.tunnel-watcher

echo ""
echo "Ждём health..."
sleep 2
"$ROOT/scripts/health.sh" || echo "gatekeeper ещё поднимается — проверьте логи ~/Library/Logs/AIHub/"

# Дождаться gatekeeper (до 30с) — чтобы сразу можно было smoke
bash "$ROOT/scripts/wait_ready.sh" 30 || echo "gatekeeper ещё поднимается — ./scripts/logs.sh"


