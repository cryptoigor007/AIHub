#!/bin/bash
# Установка AIHub на macOS — все сервисы launchd по ТЗ
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
VER="$(cat VERSION 2>/dev/null || echo '?')"

echo "=== AIHub v${VER}: установка (hybrid: LAN + Tailscale) ==="
chmod +x scripts/*.sh scripts/*.py 2>/dev/null || true

# Python venv
if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate

pip install --upgrade pip
pip install -r requirements.txt

if [ ! -f .env ]; then
  cp .env.example .env
  echo "Создан .env — секреты настройте через ./scripts/setup.sh"
fi
# Гарантируем NETWORK_MODE=hybrid если не задан
if [ -f .env ] && ! grep -qE '^NETWORK_MODE=' .env; then
  echo "NETWORK_MODE=hybrid" >> .env
fi
if [ -f .env ] && ! grep -qE '^GATEKEEPER_HOST=' .env; then
  echo "GATEKEEPER_HOST=0.0.0.0" >> .env
fi

# shellcheck source=scripts/lib_env.sh
source "$ROOT/scripts/lib_env.sh"
# Пароль opencode теперь в vault: настраивается мастером.
if [ ! -f data/vault.enc ]; then
  echo ""
  echo "⚠ Настройка не завершена — запустите мастер: ./scripts/setup.sh"
fi

mkdir -p data logs
mkdir -p "$HOME/Library/Logs/AIHub"

# Сеть: по умолчанию Tailscale mesh (без публичного входа)
if ! command -v tailscale &>/dev/null; then
  echo "⚠ tailscale не найден. Установите: https://tailscale.com/download/mac"
  echo "  (режим NETWORK_MODE=hybrid — LAN дома + Tailscale вне дома)"
fi
# cloudflared нужен только если NETWORK_MODE=cloudflare
if [ -f .env ] && grep -qE '^NETWORK_MODE=cloudflare' .env; then
  if ! command -v cloudflared &>/dev/null; then
    echo "⚠ NETWORK_MODE=cloudflare, но cloudflared нет: brew install cloudflared"
  fi
fi

PLIST_DIR="$HOME/Library/LaunchAgents"
mkdir -p "$PLIST_DIR"
PYTHON="$ROOT/.venv/bin/python"
LOG_DIR="$HOME/Library/Logs/AIHub"
PATH_ENV="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"

install_py_plist() {
  local name="$1"
  local script="$2"
  local label="ai.aihub.$name"
  local plist="$PLIST_DIR/$label.plist"
  cat > "$plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>$label</string>
  <key>ProgramArguments</key>
  <array>
    <string>$PYTHON</string>
    <string>$ROOT/scripts/$script</string>
  </array>
  <key>WorkingDirectory</key>
  <string>$ROOT</string>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>$LOG_DIR/$name.out.log</string>
  <key>StandardErrorPath</key>
  <string>$LOG_DIR/$name.err.log</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key>
    <string>$PATH_ENV</string>
  </dict>
</dict>
</plist>
PLIST
  echo "  installed $label"
}

install_sh_plist() {
  local name="$1"
  local script="$2"
  local label="ai.aihub.$name"
  local plist="$PLIST_DIR/$label.plist"
  cat > "$plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>$label</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>$ROOT/scripts/$script</string>
  </array>
  <key>WorkingDirectory</key>
  <string>$ROOT</string>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>$LOG_DIR/$name.out.log</string>
  <key>StandardErrorPath</key>
  <string>$LOG_DIR/$name.err.log</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key>
    <string>$PATH_ENV</string>
    <key>HOME</key>
    <string>$HOME</string>
  </dict>
</dict>
</plist>
PLIST
  echo "  installed $label"
}

# Порядок по ТЗ: dsh-web, opencode → gatekeeper → tunnel-watcher
# aggregator работает in-process внутри gatekeeper (один процесс, KeepAlive gatekeeper)
install_sh_plist "dsh-web" "run_dsh_web.sh"
install_sh_plist "opencode" "run_opencode.sh"
install_py_plist "gatekeeper" "run_gatekeeper.py"
# Агрегатор по умолчанию ВНУТРИ gatekeeper (один процесс).
# Sidecar ai.aihub.aggregator — только если нужен вынос:
# install_py_plist "aggregator" "run_aggregator.py"  # OPTIONAL — НЕ включать вместе с embedded
install_py_plist "tunnel-watcher" "run_tunnel.py"

# Шаблоны в config/ (только реально установленные сервисы)
for name in dsh-web opencode gatekeeper tunnel-watcher; do
  if [ -f "$PLIST_DIR/ai.aihub.$name.plist" ]; then
    cp "$PLIST_DIR/ai.aihub.$name.plist" "$ROOT/config/ai.aihub.$name.plist.template"
  fi
done

echo ""
echo "Порядок загрузки (после заполнения .env):"
echo "  launchctl load ~/Library/LaunchAgents/ai.aihub.dsh-web.plist"
echo "  launchctl load ~/Library/LaunchAgents/ai.aihub.opencode.plist"
echo "  # подождать 3–5 с"
echo "  launchctl load ~/Library/LaunchAgents/ai.aihub.gatekeeper.plist"
echo "  # ai.aihub.aggregator НЕ нужен — агрегатор внутри gatekeeper"
echo "  launchctl load ~/Library/LaunchAgents/ai.aihub.tunnel-watcher.plist"
echo ""
echo "Или одной командой: ./scripts/start_all.sh"
echo "Проверка: ./scripts/health.sh"
echo "Стоп: ./scripts/stop_all.sh"
echo "Сеть (макс. безопасность): ./scripts/enable_tailscale_serve.sh"
echo "  (телефон + Mac в Tailscale, БЕЗ Funnel)"
echo "Публичный откат: NETWORK_MODE=cloudflare + cloudflared"
echo ""
echo "Секреты (Telegram-токен и др.) — в vault, настройка: ./scripts/setup.sh"
echo "Диагностика: ./scripts/doctor.sh"
echo "Готово."
