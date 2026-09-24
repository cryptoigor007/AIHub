# AIHub v3.6.0 — управление DSH + OpenCode из Telegram

Единый WebApp-дашборд для **DeepSeek Harness** и **OpenCode**.
Соответствует ТЗ v3.6. **Сеть по умолчанию: hybrid — дома LAN без Tailscale, вне дома Tailscale.**

---

## Установка (macOS)

```bash
cd ~/AIHub
chmod +x scripts/*.sh scripts/*.py
./scripts/install.sh
./scripts/setup.sh      # мастер: Telegram + шифрованное хранилище
```

Нужны: Python 3.11+, `dsh`, `opencode`, **Tailscale** на Mac и телефоне (один аккаунт).

`cloudflared` не нужен в hybrid/tailscale.

**Секреты** хранятся в `data/vault.enc` (AES-256-GCM), ключ — в macOS Keychain.
В `.env` секретов нет. Статус: `./scripts/vault_cli.py status`.

---

## Запуск (безопасный контур)

```bash
./scripts/start_all.sh
./scripts/enable_tailscale_serve.sh
./scripts/doctor.sh
./scripts/status.sh
```

На телефоне: Tailscale → VPN On → кнопка «AIHub» в боте.

Порядок launchd: dsh-web → opencode → gatekeeper → tunnel-watcher.
Sidecar `ai.aihub.aggregator` не поднимать.

---

## Сеть

| Режим | .env | Поверхность |
|-------|------|-------------|
| **hybrid (по умолчанию)** | NETWORK_MODE=hybrid | Дома LAN HTTP; вне дома Tailscale HTTPS |
| tailscale | NETWORK_MODE=tailscale | Только mesh |
| cloudflare | NETWORK_MODE=cloudflare | Публичный trycloudflare |

См. `docs/NETWORK_TAILSCALE.md`. Не включайте `tailscale funnel`.
Дома URL: `./scripts/status.sh` или `./scripts/open_url.sh`.

---

## Безопасность

- Нет входа из публичного интернета (mesh)
- Только OWNER_TELEGRAM_ID
- UI/API под /p/&lt;secret&gt;/
- initData HMAC + cookie HttpOnly; Secure; SameSite=Lax
- Rate-limit, audit, .kill → 503
- DSH/OpenCode только 127.0.0.1

---

## Проверки

```bash
./scripts/check_once.sh
```

Ручной E2E: `docs/ACCEPTANCE.md`.

Опционально рядом: grinev/opencode-telegram-bot на :4096 для чат-OpenCode.

## Авария

```bash
touch .kill
rm -f .kill
./scripts/logs.sh
```
