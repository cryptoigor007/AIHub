#!/bin/bash
# Одна строка статуса — удобно в цикле / watch
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
# shellcheck source=scripts/lib_env.sh
source "$ROOT/scripts/lib_env.sh"
aihub_load_env
HOST="$(aihub_gk_host)"
PORT="$(aihub_gk_port)"
PY="$(aihub_python)"
H=$(curl -sf --max-time 2 "http://${HOST}:${PORT}/health" 2>/dev/null || true)
if [ -z "$H" ]; then
  echo "gatekeeper=DOWN dsh=? oc=? kill=? url=${PUBLIC_URL:-—}"
  exit 1
fi
"$PY" - "$H" << 'PY'
import json
import sys

d = json.loads(sys.argv[1])
lans = d.get("lan_urls") or []
lan = lans[0] if lans else "—"
print(
    f"gatekeeper={d.get('status')} dsh={d.get('dsh')} oc={d.get('opencode')} "
    f"kill={d.get('kill_switch')} ver={d.get('version')} "
    f"mode={d.get('network_mode') or '—'} "
    f"mesh={d.get('public_url') or '—'} lan={lan}"
)
PY
