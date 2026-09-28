# AIHub v3.7.0 — управление DSH + OpenCode из Telegram

Единый WebApp-дашборд для **DeepSeek Harness** и **OpenCode**.
Сеть по умолчанию: **hybrid** — дома LAN без Tailscale, вне дома Tailscale Serve (mesh HTTPS).

---

## Что нового в 3.7.0

- Полный редизайн UI (mobile-first, тема auto, splash, drawer)
- Pin / archive / локальные названия чатов
- Автонейминг технических сессий
- DSH rename + iframe embed
- Автопилот Tailscale Serve (timeout 15 с), AcceptDNS, напоминания
- Бот: `/start` `/link` + кнопки LAN / mesh
- `./scripts/go.sh` — быстрый старт

---

## Установка (macOS)

```bash
cd ~/AIHub
chmod +x scripts/*.sh scripts/*.py
./scripts/install.sh
./scripts/setup.sh      # мастер: Telegram + шифрованное хранилище
```

Нужны: Python 3.11+, `dsh`, `opencode`, **Tailscale** на Mac и телефоне (один аккаунт).

**Секреты** — в `data/vault.enc` (AES-256-GCM), ключ в macOS Keychain. В `.env` секретов нет.

---

## Запуск

```bash
./scripts/go.sh                 # start → health → status → open URL
# или по шагам:
./scripts/start_all.sh
./scripts/enable_tailscale_serve.sh   # с таймаутом 15 с
./scripts/doctor.sh
./scripts/status.sh                   # + last_in= канал клиента
```

На телефоне: Tailscale → VPN On → кнопка «AIHub» в боте (или `/link`).

---

## Проверки

```bash
./scripts/check_once.sh         # pytest + smoke + acceptance
PYTHONPATH=src python -m pytest tests/ -q
```

---

## Сеть (hybrid)

| Где | Как |
|-----|-----|
| Дома (LAN) | `http://<IP-Mac>:8787/p/…/` без VPN |
| Вне дома | Tailscale Serve → `https://*.ts.net/p/…/` |

Выключатели: `TAILSCALE_AUTOSERVE`, `TAILSCALE_AUTODNS`, `TAILSCALE_REMIND` (default `1`).

Подробнее: [docs/NETWORK_TAILSCALE.md](docs/NETWORK_TAILSCALE.md), [docs/RUNBOOK.md](docs/RUNBOOK.md).

---

## Структура

```
src/gatekeeper   UI-шелл, auth, API, proxy DSH, WS
src/aggregator   поллинг DSH+OpenCode, действия, autoname
src/tunnel       watcher + bot_dialog + autoserve
src/common       config, vault, clients, chat_meta, netinfo
static/          WebApp (HTML/CSS/JS)
scripts/         start/stop/doctor/smoke/go/setup
tests/           pytest
```

Лицензия и соответствие: [docs/COMPLIANCE.md](docs/COMPLIANCE.md).
