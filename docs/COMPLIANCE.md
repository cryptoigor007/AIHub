# Соответствие ТЗ v3.5

Единственный источник истины: ТЗ v3.5 от 2026-09-24.
Этот документ — карта «требование → реализация».

## F1–F16 (MVP)

| ID | Требование | Реализация | Статус |
|----|------------|------------|--------|
| F1 | Кнопка → HTTPS WebApp | tunnel watcher + setChatMenuButton | ✅ |
| F2 | initData + allowlist | `telegram_auth.py` + `OWNER_TELEGRAM_ID` | ✅ |
| F3 | Живая картина обеих систем | aggregator + UI карточки | ✅ |
| F4 | Real-time без reload | WS `/ws` + client | ✅ |
| F5 | Текущее действие | `last_step` / meta | ✅ |
| F6 | Jobs/субагенты DSH | poll DSH + parent_id | ✅ |
| F7 | Сессии OC (токены/cost) | OpenCodeClient + meta | ✅ |
| F8 | Список + поиск | `/api/sessions` + FTS `/api/search` | ✅ |
| F9 | История | `/api/agents/{id}/history` | ✅ |
| F10 | send / interrupt / permission | actions API + UI | ✅ |
| F11 | Полный интерфейс DSH | proxy `/dsh/*` + HTML rewrite | ✅ |
| F12 | Уведомления | notifier + throttle 60s | ✅ |
| F13 | Mac reboot → self-heal | launchd KeepAlive | ✅ |
| F14 | Рестарт dsh прозрачен | 401 → invalidate → retry | ✅ |
| F15 | Нет токена/401 у владельца | proxy server-side only | ✅ |
| F16 | Полное управление | actions + full UI | ✅ |

## Приёмка 29–33

| # | Критерий | Статус |
|---|----------|--------|
| 29 | Старт без TELEGRAM_BOT_TOKEN | ✅ |
| 30 | Токен после рестарта | ✅ `.env` |
| 31 | SECRET_PATH один раз | ✅ `ensure_secrets` |
| 32 | Audit на действия | ✅ `audit.py` |
| 33 | `.kill` → 503 | ✅ |

## Безопасность (§4)

| Слой | Файл |
|------|------|
| initData HMAC + freshness 300s | `telegram_auth.py` |
| Cookie HttpOnly; Secure на HTTPS; SameSite=Lax | `app.py` auth |
| SECRET_PATH | `config.py` + catch_all 404 |
| Rate-limit 10/5мин, 120/мин + prune | `rate_limit.py` |
| Audit JSON-lines | `audit.py` |
| `.kill` | `config.is_kill_switch_active` |
| Без `--trusted-host` | `run_dsh_web.sh` |
| Host/Origin/sec-fetch rewrite | `proxy.py` |

## Архитектурное решение: aggregator

ТЗ §12 перечисляет `ai.aihub.aggregator` как launchd-сервис.
**Реализовано in-process внутри gatekeeper** — намеренно:

- устраняет dual-poll / dual-notify / гонку за `state.json`;
- один KeepAlive-процесс;
- sidecar остаётся опциональным (`run_aggregator.py`), **не** ставится install.sh.

## On-site (обязательно на Mac)

См. `docs/ON_SITE.md` и `docs/IDEAL_STACK.md`.

## Сеть (v3.6.0)

- По умолчанию NETWORK_MODE=hybrid: LAN HTTP дома, Tailscale HTTPS вне дома.
- Menu Button — HTTPS (*.ts.net); LAN URL для браузера в той же Wi-Fi (`./scripts/status.sh`).
- `/health` отдаёт `lan_urls`/`network_hint` только loopback/сессии владельца (SECRET_PATH не утекает).
- Владелец получает Telegram-подсказку: нет `*.ts.net` (раз в 6 ч) или кнопка не обновилась (раз в час).
- Funnel / cloudflare — только явный откат.
