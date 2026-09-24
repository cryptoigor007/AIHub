#!/bin/bash
# ПУБЛИЧНЫЙ вход через Tailscale Funnel (слабее mesh-only).
# Используйте только если телефон НЕ может быть в Tailscale.
set -euo pipefail
PORT="${GATEKEEPER_PORT:-8787}"
echo "=== Tailscale Funnel (PUBLIC internet) ==="
echo "Это ОТКРЫВАЕТ сервис в интернет. Для макс. безопасности используйте:"
echo "  ./scripts/enable_tailscale_serve.sh"
echo ""
echo "Если всё же нужно:"
echo "  sudo tailscale funnel $PORT"
echo "  затем PUBLIC_URL=https://… в .env и NETWORK_MODE=tailscale"
echo "Доки: https://tailscale.com/kb/1223/funnel"
