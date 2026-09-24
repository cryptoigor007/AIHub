# Идеальный вариант эксплуатации

## Продуктовое разделение

| Задача | Инструмент |
|--------|------------|
| Единый дашборд DSH + OpenCode | **AIHub** (этот репозиторий) |
| Полный UI DeepSeek Harness | AIHub → proxy `/dsh/*` |
| Писать агенту OpenCode как в чат | **grinev** `@grinev/opencode-telegram-bot` |
| STT / TTS / /task / /ls / skills | grinev (не AIHub) |
| Авария / kill switch | `touch .kill` (AIHub) |

## Обязательный P0 (без этого «без проблем» не обещать)

На **Mac**, один раз после `install.sh`:

1. `TELEGRAM_BOT_TOKEN` в `.env`
2. `./scripts/start_all.sh` → `./scripts/doctor.sh` → `./scripts/health.sh`
3. `dsh web --help` / `opencode serve --help` → при расхождении правок 1–2 строки в `run_*.sh`
4. `tail ~/.dsh/web.log | grep -i token` → при необходимости regex в `dsh_token.py`
5. E2E: auth → список агентов → send/interrupt → «Полный интерфейс» DSH
6. Смена mesh URL (tailscale serve) → кнопка «AIHub» в боте обновилась

## Необязательно, но сильно

- 30 мин логов под нагрузкой (нет 401/502 циклов)
- Рестарт dsh web → proxy сам берёт новый токен
- `npx @grinev/opencode-telegram-bot@latest` рядом (тот же `:4096`)
- План Б: `./scripts/enable_tailscale_funnel.sh` (публичный вход, не рекомендуется)

## Чего не делать

- Не ставить `ai.aihub.aggregator` (дубль poll/notify)
- Не тащить STT/TTS/scheduler в AIHub
- Не открывать gatekeeper в LAN без tunnel + SECRET_PATH
- Не `uvicorn --reload` в prod (`app = create_app()` фиксирует secret рано)

## Итог одной фразой

**Код готов. «Без проблем» = P0 на Mac + (опционально) grinev для chat-UX OpenCode.**
