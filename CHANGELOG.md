# Changelog

## 3.6.0 — мастер настройки + шифрованное хранилище

- Мастер первого запуска `./scripts/setup.sh` (Telegram BotFather → токен → OWNER_TELEGRAM_ID)
- Секреты в `data/vault.enc` (AES-256-GCM), ключ в macOS Keychain; миграция из `.env` со scrubbing
- `LOCAL_LOGIN` (off | loopback | lan) для `/auth/dev` без Telegram
- CLI: `scripts/vault_cli.py` (status/get/set/gen/delete/migrate/reauth)
- Зависимость: `cryptography>=43`
- В `.env` больше нет секретов (TELEGRAM_BOT_TOKEN, OWNER_TELEGRAM_ID, COOKIE_SECRET, SECRET_PATH, OPENCODE_SERVER_PASSWORD)

## 3.5.5 — проверки не врут


- `pytest` в requirements.txt (acceptance/check_once гоняют тесты в .venv деплоя)
- acceptance: отсутствие deps → SKIP («No module named …»), а не FAIL
- check_once: `set -o pipefail` — провал тестов больше не маскируется `| tail`

## 3.5.4 — диагностика без ложных «offline»

- `doctor.sh`: DSH/OpenCode с HTTP 401 = «жив, нужна авторизация» (а не offline);
  PATH как в run_*.sh (виден тот же opencode, что запускает сервис)
- tunnel-watcher: warning про отсутствие mesh URL — не чаще раза в 5 минут (лог-гигиена)

## 3.5.3 — реальный запуск: OpenCode V2, защита от дублей

### OpenCode V2
- Клиент понимает оба API: V1 (`/session`, `/event`) и V2 (`/api/session`, `/api/event`, `/api/info`)
- Определение «вкуса» по `/api/info`; HTML web-UI V2 (200) больше не принимается за данные
- SSE: проверка `content-type: text/event-stream` и Basic Auth (V2 требует пароль)
- `opencode serve` V2: пароль фиксируется через `OPENCODE_SERVER_PASSWORD` (генерируется в .env)
- `change_model`: V2 `POST /api/session/{id}/model` (с разбором `provider/model`), V1 — PATCH

### Запуск / launchd
- `run_dsh_web.sh`, `run_opencode.sh`: не поднимают второй экземпляр на занятом порту (ждут)
- `dsh_token_found` → debug; пустой `state.json` не считается ошибкой

### Тесты
- +8 тестов: OpenCode V2 (MockTransport), V1-fallback, event_urls

## 3.5.2 — аудит и LAN-стратегия

### Сеть (hybrid)
- Уведомления владельцу: mesh URL (`*.ts.net`) не найден → подсказка про Tailscale (не чаще 6 ч);
  кнопка в Telegram не обновилась → предупреждение (не чаще 1 ч)
- `/health`: `lan_urls` и `network_hint` только доверенной стороне (loopback / сессия владельца) —
  SECRET_PATH больше не утекает без авторизации; X-Forwarded-For не используется для доверия
- `network_hint_message` без `<IP-Mac>` — текст безопасен для Telegram HTML parse_mode
- `validate_env.py`: `NETWORK_MODE=tailscale` без tailscale CLI → ошибка; hybrid → предупреждение
- `doctor.sh`: версия из VERSION, дефолт hybrid, строка про LAN без Tailscale

### Надёжность / стандартизация
- `src/common/envfile.py` — единый upsert/read `.env` (config, tunnel-watcher)
- `src/common/throttle.py` — троттлинг уведомлений по файлу-флагу
- watcher читает PUBLIC_URL live (обход lru_cache), `/api/settings` тоже
- `NotifierService.send_text` — публичный API вместо приватного `_send`
- удалён мёртвый `check_secret_path`, неиспользуемые импорты; netinfo закрывает сокет
- тесты: envfile, throttle, netinfo+loopback; `test_models` — importorskip (standalone-прогон без deps)
- `check_once.sh`: починен вывод рамки

### Версионирование
- Версия 3.5.2: VERSION, pyproject, README, RUNBOOK, HealthResponse
- `scripts/install.sh` и `doctor.sh` читают VERSION вместо хардкода

## 3.5.1 — hybrid LAN + Tailscale

- NETWORK_MODE=hybrid: дома Wi‑Fi без обязательного Tailscale; вне дома — VPN On
- Gatekeeper bind 0.0.0.0, lan_urls + network_hint в /health
- Cookie path=SECRET_PATH, Secure только на HTTPS
- PUBLIC_URL live read (обход lru_cache), notify-подсказка владельцу
- UI banner при потере WS; enable_tailscale_serve без silent fail
- Тесты: netinfo + telegram_auth зелёные

## 3.5.1 — Tailscale mesh by default

- NETWORK_MODE=tailscale (default): no public cloudflared
- scripts/enable_tailscale_serve.sh — HTTPS only inside tailnet
- tunnel-watcher detects *.ts.net and updates menu button
- Funnel discouraged; cloudflare is opt-in rollback
- doctor/install/README aligned

## 3.5.1 — dev-контур и проверки

- DEV auth (/auth/dev) + /api/diag для локального теста без Telegram
- scripts/check_once.sh — полный автопрогон одним заходом
- scripts/smoke.sh, acceptance.sh, probe_token.py, probe_cli.sh, logs.sh, restart.sh
- docs/TESTING.md — как тестировать один раз
- docs/COMPLIANCE.md, IDEAL_STACK.md
- Rate-limit prune, TOKEN_PATTERNS, dual-aggregator fix

## 3.5.1 — notes

- Circuit breaker, Request-ID, security headers
- DSHClient + OpenCodeClient (официальный API)
- HTML/Location rewrite proxy
- Permissions once/always/reject, fork/revert/rename
- Projects/models/metrics/settings API
- FTS, cleanup 24h, rich notifications
- UI: duration, haptic, live WS, sessions tab
- doctor.sh, validate_env.py, Dockerfile
- Агрегатор только in-process (sidecar отключён по умолчанию)
- Atomic state.json snapshot
- Rate-limit prune каждые 5 мин
- Расширенные TOKEN_PATTERNS для web.log
- Версия единообразно 3.5.1

## 3.5.0
- MVP по ТЗ v3.5: gatekeeper, aggregator, tunnel, notifier, launchd
