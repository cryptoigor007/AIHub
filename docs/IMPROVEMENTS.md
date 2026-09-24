# Глубокий анализ и улучшения (v3.5+)

## Найденные слабости (до доработки)

1. OpenCode/DSH — разрозненные эвристики URL без единого клиента
2. Proxy DSH не переписывал HTML-ссылки на localhost → битый «полный интерфейс»
3. Нет security headers
4. История — слабая нормализация parts[]
5. Уведомления без проекта/модели/стоимости
6. Нет очистки старых completed агентов → рост памяти
7. UI без длительности работы и haptic

## Что добавлено

| Улучшение | Файл |
|-----------|------|
| `DSHClient` с 401-retry | `src/common/dsh_client.py` |
| `OpenCodeClient` (офиц. API) | `src/common/opencode_client.py` |
| HTML rewrite в proxy | `src/gatekeeper/proxy.py` + `security.py` |
| Security headers middleware | `gatekeeper/security.py` |
| Redact секретов | `common/redact.py` |
| История parts[] + client API | `aggregator/service.py` |
| Cleanup 24ч | `_cleanup_loop` |
| Rich notify | `notifier/service.py` |
| ⏱ duration + haptic | `static/js/aihub.js` |
| Permissions once/always/reject | UI + opencode_client |

## Рекомендации владельцу (не код)

1. Заполнить `ON_SITE.md` (regex токена DSH)
2. `opencode serve --port 4096 --hostname 127.0.0.1`
3. Опционально: grinev bot параллельно для чат-UX OpenCode
4. Не открывать gatekeeper в LAN без tunnel+secret

## Не делали намеренно

- STT/TTS, scheduler, file browser (вне ТЗ)
- Копирование кода grinev
- Multi-user
