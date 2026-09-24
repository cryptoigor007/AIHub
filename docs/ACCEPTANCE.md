# Критерии приёмки AIHub v3.5

## Сеть (hybrid)

- [ ] NETWORK_MODE=hybrid, GATEKEEPER_HOST=0.0.0.0
- [ ] Дома: lan URL из status без Tailscale (браузер)
- [ ] Вне дома: Tailscale VPN On → кнопка AIHub
- [ ] Funnel не включён

## Сеть (mesh)
- [ ] Tailscale Mac + телефон, один аккаунт
- [ ] `./scripts/enable_tailscale_serve.sh`
- [ ] PUBLIC_URL = `https://….ts.net`
- [ ] Funnel **не** включён

## Функциональные (F1–F16)

| ID | Критерий | Как проверить | Статус кода |
|----|----------|---------------|-------------|
| F1 | Кнопка HTTPS WebApp | setChatMenuButton после туннеля | ✅ |
| F2 | initData + allowlist | чужой → 403 + notify | ✅ |
| F3 | Живая картина обеих систем | экран AIHub | ✅ |
| F4 | Real-time без reload | WebSocket | ✅ |
| F5 | Текущее действие | last_step на карточке | ✅ |
| F6 | Jobs/субагенты DSH | parent_id + subagents UI | ✅ эвристика |
| F7 | OpenCode токены/стоимость | tokens/cost | ✅ |
| F8 | Список сессий + поиск | вкладка Сессии + FTS | ✅ |
| F9 | История как штатная | fetch_remote_history | ⚠️ on-site API |
| F10 | send/interrupt/approve | карточка | ✅ |
| F11 | Полный интерфейс DSH | /dsh/ proxy | ⚠️ on-site |
| F12 | Уведомления | notifier | ✅ |
| F13 | Mac on → всё само | launchd KeepAlive | ✅ |
| F14 | Рестарт dsh прозрачен | token reread + 401 retry | ✅ |
| F15 | Нет токена/401 у владельца | proxy | ✅ |
| F16 | Полное управление | actions API | ✅ |

## Доп. 29–33

| # | Критерий | Статус |
|---|----------|--------|
| 29 | Старт без TELEGRAM_BOT_TOKEN | ✅ auth → «токен не задан» |
| 30 | Токен после рестарта | ✅ из .env |
| 31 | SECRET_PATH один раз | ✅ ensure_secrets |
| 32 | Audit на действия | ✅ logs/audit.log |
| 33 | .kill → 503 | ✅ |

## Инфра

- [x] Stub до ready gatekeeper
- [x] setChatMenuButton (mesh URL); cloudflared — только откат
- [x] launchd: dsh-web, opencode, gatekeeper (+in-process aggregator), tunnel-watcher
- [x] sidecar ai.aihub.aggregator НЕ устанавливается по умолчанию
- [x] OpenCode SSE
- [x] FTS
- [x] План Б Tailscale script
- [ ] On-site: формат token в web.log
- [ ] On-site: порт/OpenAPI OpenCode
- [ ] On-site: WebSocket DSH после proxy

## Запреты соблюдены в коде

Не трогаем оркестратор, не пишем в канал, не --trusted-host, не /setmenubutton, секреты не в URL.

## v3.5.1 extras
- [x] Circuit breaker DSH/OpenCode
- [x] Request-ID + security headers
- [x] HTML/Location rewrite proxy
- [x] doctor.sh
- [x] rename / duration / haptic UI
