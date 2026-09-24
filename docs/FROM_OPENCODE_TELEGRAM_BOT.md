# Анализ grinev/opencode-telegram-bot → что взяли в AIHub

Проект: https://github.com/grinev/opencode-telegram-bot (MIT, ~1.2k ⭐, npm `@grinev/opencode-telegram-bot`)

## Разные продукты

| | grinev bot | AIHub (наш) |
|--|------------|-------------|
| UX | Чат Telegram + команды | WebApp «дашборд» |
| Системы | Только OpenCode | **DSH + OpenCode** |
| Сеть | Без открытых портов (long polling) | Cloudflare tunnel + secret path |
| Полнота OpenCode | Очень высокая (TUI-parity) | Дашборд + proxy DSH |

**Не заменяем grinev ботом.** Можно запускать **параллельно** на том же `opencode serve :4096`.

## Что взяли (идеи и контракт API, НЕ код)

1. **Официальный OpenCode Server API** (`opencode.ai/docs/server`):
   - порт **4096**
   - `GET /global/health`, `GET /session`, `POST /session`, `GET /session/:id`
   - `GET /session/status`, `GET /session/:id/children`
   - `GET /event` SSE (`server.connected` → bus)
   - статусы: `idle` | `active` | `error`

2. **Потоки взаимодействия**:
   - permission: once / always / reject
   - question.reply
   - abort vs «просто смотреть» (у нас interrupt)
   - children = субагенты
   - session.diff → список изменённых файлов на карточке

3. **Операционка**:
   - фиксированный `opencode serve --port 4096`
   - опциональный Basic Auth сервера
   - whitelist user id (у нас уже)

## Что сознательно НЕ переносили (вне ТЗ AIHub)

- STT/TTS, scheduled `/task`, `/ls` file browser
- Chat-streaming ответов в Telegram
- Полный TUI-parity model picker / skills / MCP UI
- Копирование TypeScript-кода grinev (запрет ТЗ)

## Реализация в AIHub

- `src/common/opencode_client.py` — свой HTTP-клиент по docs
- Агрегатор: poll + SSE на официальных путях
- UI: once/always/reject, ответ на вопрос, changed files


## Идеальный стек (рекомендация)

```
┌─ Mac (локально) ─────────────────────────────────────────┐
│  opencode serve :4096                                    │
│  dsh web :3080                                           │
│                                                          │
│  ┌─ AIHub (этот репо) ─────────────────────────────┐    │
│  │  gatekeeper :8787 + aggregator in-process         │    │
│  │  tunnel-watcher → cloudflared → Telegram WebApp   │    │
│  │  DSH+OpenCode дашборд, proxy полного UI DSH       │    │
│  └──────────────────────────────────────────────────┘    │
│                                                          │
│  ┌─ grinev bot (опционально, параллельно) ─────────┐    │
│  │  npx @grinev/opencode-telegram-bot@latest         │    │
│  │  чат-UX OpenCode: промпты, STT/TTS, /task, /ls    │    │
│  │  тот же :4096, long-polling Telegram, без tunnel  │    │
│  └──────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────┘
```

**Не мержить продукты.** AIHub = единый экран DSH+OpenCode + полный Harness UI.
grinev = лучший chat-клиент только для OpenCode. Вместе они закрывают 100% сценариев.

### Что взять из grinev (уже взято как контракт API)

| Идея | В AIHub |
|------|----------|
| Official Server API paths | `opencode_client.py` |
| SSE `/event` + fallback poll | aggregator |
| permission once/always/reject | UI + API |
| question.reply | UI + API |
| children / subagents | meta + card |
| session.diff → changed files | meta.changed_files |
| abort / fork / revert / rename | actions |
| whitelist user id | OWNER_TELEGRAM_ID |
| Basic Auth opencode server | config |

### Что НЕ переносить в AIHub

STT, TTS, `/task` scheduler, `/ls` file browser, streaming ответов в чат,
skills/MCP UI, worktree switcher, message queue — это другой UX и раздувает
поверхность багов. Для них ставьте grinev рядом.

### Если хочется «ещё ближе к grinev» без нового продукта

1. В карточке OpenCode: кнопка «Открыть в чат-боте» (deep-link к grinev, если запущен)
2. Показывать `variant` рядом с model (уже есть)
3. Health monitor opencode с авто-рестартом — у grinev есть; у нас KeepAlive launchd достаточно
