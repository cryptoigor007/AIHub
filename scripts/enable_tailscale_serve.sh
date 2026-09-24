#!/bin/bash
# Tailscale Serve (mesh HTTPS). Для hybrid: вне дома; дома можно LAN без VPN.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
# shellcheck source=scripts/lib_env.sh
source "$ROOT/scripts/lib_env.sh"
PY="$(aihub_python)"
if [ -f .env ]; then set -a; # shellcheck disable=SC1091
  source .env; set +a; fi

PORT="${GATEKEEPER_PORT:-8787}"
HOST="${GATEKEEPER_HOST:-0.0.0.0}"
# serve всегда на localhost target
TARGET_HOST="127.0.0.1"
if [ "$HOST" != "0.0.0.0" ] && [ "$HOST" != "::" ]; then
  TARGET_HOST="$HOST"
fi

echo "=== Tailscale Serve (mesh HTTPS, без Funnel) ==="

if ! command -v tailscale >/dev/null 2>&1; then
  echo "FAIL: tailscale не установлен — https://tailscale.com/download/mac"
  exit 1
fi
if ! tailscale status >/dev/null 2>&1; then
  echo "FAIL: tailscale не залогинен"
  exit 1
fi

echo "1) Serve HTTPS → http://${TARGET_HOST}:${PORT}"
set +e
if tailscale serve --help 2>&1 | grep -q '\-\-bg'; then
  tailscale serve --bg --https=443 "http://${TARGET_HOST}:${PORT}"
  RC=$?
else
  tailscale serve https / "http://${TARGET_HOST}:${PORT}"
  RC=$?
fi
set -e
if [ "$RC" -ne 0 ]; then
  echo "FAIL: tailscale serve exit $RC"
  exit "$RC"
fi

echo "2) serve status:"
tailscale serve status 2>&1 || true

DNS=$(tailscale status --json 2>/dev/null | "$PY" -c "import sys,json;d=json.load(sys.stdin);print((d.get('Self') or {}).get('DNSName') or '')" 2>/dev/null || true)
DNS="${DNS%.}"
if [ -z "$DNS" ]; then
  echo "FAIL: DNSName пуст"
  exit 1
fi
URL="https://${DNS}"
echo "3) URL: $URL"

"$PY" - << PY
from pathlib import Path
env = Path(".env")
lines = env.read_text().splitlines() if env.exists() else []
def upsert(k, v):
    global lines
    found = False
    out = []
    for line in lines:
        if line.startswith(k + "=") or line.startswith(k + " ="):
            out.append(f"{k}={v}")
            found = True
        else:
            out.append(line)
    if not found:
        out.append(f"{k}={v}")
    lines = out
upsert("PUBLIC_URL", "${URL}")
# не затираем hybrid
mode = "hybrid"
for line in lines:
    if line.startswith("NETWORK_MODE="):
        mode = line.split("=",1)[1].strip() or "hybrid"
if mode not in ("hybrid", "tailscale", "cloudflare"):
    mode = "hybrid"
upsert("NETWORK_MODE", mode if mode != "cloudflare" else "hybrid")
env.write_text("\\n".join(lines) + "\\n")
print("   .env обновлён PUBLIC_URL + NETWORK_MODE=", mode)
PY

echo "4) Дома в Wi‑Fi: Tailscale на телефоне необязателен (LAN URL из ./scripts/status.sh)"
echo "   Вне дома: Tailscale VPN On → кнопка «AIHub»"
echo "5) kickstart: launchctl kickstart -k gui/\$(id -u)/ai.aihub.tunnel-watcher"
echo "НЕ включайте: tailscale funnel"
echo "=== готово ==="
