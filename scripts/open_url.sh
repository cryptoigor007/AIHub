#!/bin/bash
# Печатает URL экрана AIHub: local / LAN / mesh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
# shellcheck source=scripts/lib_env.sh
source "$ROOT/scripts/lib_env.sh"
aihub_load_env
PY="$(aihub_python)"

SECRET="${SECRET_PATH:-}"
if [ -z "$SECRET" ] || [ "$SECRET" = "/p/xxxxxxxx" ]; then
  SECRET=$(PYTHONPATH="$ROOT" "$PY" -c "
from src.common.config import get_settings
print(get_settings().secret_path)
" 2>/dev/null || true)
fi

HOST="$(aihub_gk_host)"
PORT="$(aihub_gk_port)"
PUBLIC="${PUBLIC_URL:-}"
MODE="${NETWORK_MODE:-hybrid}"

echo "mode:   ${MODE}"
echo "local:  http://${HOST}:${PORT}${SECRET}/"
if [ -n "$PUBLIC" ]; then
  echo "mesh:   ${PUBLIC}${SECRET}/"
else
  echo "mesh:   (нет PUBLIC_URL — ./scripts/enable_tailscale_serve.sh)"
fi

PYTHONPATH="$ROOT" "$PY" - << PY 2>/dev/null || true
from src.common.netinfo import lan_http_urls, network_hint_message
import os
secret = os.environ.get("SECRET_PATH") or "${SECRET}"
port = int(os.environ.get("GATEKEEPER_PORT") or "${PORT}")
pub = os.environ.get("PUBLIC_URL") or "${PUBLIC}"
lans = lan_http_urls(port, secret or "/p/x")
if lans:
    print("lan:")
    for u in lans[:5]:
        print(f"  {u}")
else:
    print("lan:    (не определены — смотрите ifconfig)")
print()
print(network_hint_message(has_mesh_url=bool(pub and ".ts.net" in pub), lan_urls=lans))
PY
