# Типичные сбои → что сделать один раз

| Симптом | Команда | Действие |
|---------|---------|----------|
| WebApp не открывается с LTE | Tailscale на телефоне | VPN On, тот же аккаунт |
| Дома без VPN | `./scripts/status.sh` → lan= | браузер по LAN URL (кнопка TG = HTTPS/TS) |
| нет HTTPS / certificate | `./scripts/enable_tailscale_serve.sh` | Serve + MagicDNS |
| gatekeeper DOWN | `./scripts/logs.sh 50` | gatekeeper.err.log |
| DSH offline | `./scripts/probe_cli.sh` | флаги run_dsh_web.sh |
| токен / 401 | `./scripts/probe_token.py` | regex в dsh_token.py |
| OpenCode offline | opencode serve --help | run_opencode.sh |
| PUBLIC_URL trycloudflare при mesh | grep NETWORK .env | serve.sh + сменить URL |
| Кнопка «AIHub» не обновилась | Telegram → сообщение от бота | проверить TELEGRAM_BOT_TOKEN, `tailscale serve status` |
| Нет напоминаний про Tailscale | `data/.mesh_missing_notified` | удалить файл, чтобы получить подсказку снова |
| dual notify | launchctl list | unload aggregator |
| всё 503 | ls .kill | rm -f .kill |

Полный автопрогон: `./scripts/check_once.sh`.
Сеть: `docs/NETWORK_TAILSCALE.md`.
