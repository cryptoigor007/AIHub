# Проверки на месте (обязательно)

Заполнять по мере запуска на реальном Mac (`your-mac`).

## 1. Формат токена в `~/.dsh/web.log`

```
Команда: tail -n 50 ~/.dsh/web.log | grep -i token
Результат:
(вписать сюда)
```

Актуальный regex в `src/common/dsh_token.py` → TOKEN_PATTERNS.

## 2. sec-fetch-site от Telegram WebView

```
Прокси логирует входящие заголовки при первом запросе к /dsh/.
Результат: sec-fetch-site = ?
```

Ожидание: `cross-site`. Привратник переписывает в `same-origin`.

## 3. WebSocket и абсолютные ссылки

После открытия «Полный интерфейс» проверить:

- [ ] WebSocket подключается через `/p/.../dsh/...`
- [ ] Нет mixed-content / broken absolute URLs
- [ ] Cookie токена DSH устанавливается корректно

## 4. OpenAPI и SSE opencode serve

```
curl -s http://127.0.0.1:PORT/openapi.json | head
curl -sN http://127.0.0.1:PORT/events
```

Порт по умолчанию (уточнить): ______

Формат SSE: ______

## 5. Реальный порт opencode serve

```
lsof -iTCP -sTCP:LISTEN | grep opencode
# или
opencode serve --help
```

Значение в `.env`: `OPENCODE_SERVE_PORT=`

## 6. Повторный 401

1. Перезапустить dsh web
2. Убедиться, что токен в web.log обновился
3. Запрос через прокси должен пройти без 401 для клиента

## Прочие заметки

-
-

## Сеть hybrid (заполнить на Mac)

| Проверка | Результат |
|----------|-----------|
| NETWORK_MODE | |
| GATEKEEPER_HOST | |
| enable_tailscale_serve | |
| PUBLIC_URL (*.ts.net) | |
| lan_urls из /health | |
| Дома без TS, браузер LAN | |
| Вне дома, TS VPN On, кнопка | |
| Funnel выключен | |
