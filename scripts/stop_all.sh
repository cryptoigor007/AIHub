#!/bin/bash
set -euo pipefail
PLIST_DIR="$HOME/Library/LaunchAgents"
for label in ai.aihub.tunnel-watcher ai.aihub.aggregator ai.aihub.gatekeeper ai.aihub.opencode ai.aihub.dsh-web; do
  plist="$PLIST_DIR/$label.plist"
  if [ -f "$plist" ]; then
    launchctl unload "$plist" 2>/dev/null || true
    echo "unloaded $label"
  fi
done
echo "Остановлено."
