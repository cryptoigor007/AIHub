# Как тестировать один раз, а не 200

## Золотой путь

```bash
cd ~/AIHub
./scripts/install.sh          # один раз
# .env: TELEGRAM_BOT_TOKEN=...  и для локального UI без бота:
# LOCAL_LOGIN=loopback (или lan для теста с телефона); ENV=development только для не-Secure cookie

./scripts/start_all.sh
./scripts/check_once.sh       # ← весь автопрогон
```

`check_once.sh` сам гоняет: validate_env, unit-тесты, probe CLI/token, doctor, smoke, acceptance.

## Для локального UI без Telegram

В `.env`:

```env
LOCAL_LOGIN=loopback (или lan для теста с телефона); ENV=development только для не-Secure cookie
```

Тогда:
- cookie **без** Secure (работает на http://127.0.0.1)
- `POST /p/<secret>/auth/dev` выдаёт сессию владельца
- JS сам вызывает `/auth/dev`, если нет `initData`

Откройте в Safari/Chrome:

```
http://127.0.0.1:8787/p/<SECRET_PATH>/
```

`SECRET_PATH` смотрите: `./scripts/validate_env.py` или `/health` (на Mac; для посторонних `/health` скрывает secret).

## Матрица скриптов

| Команда | Зачем |
|---------|--------|
| `./scripts/check_once.sh` | **всё сразу** |
| `./scripts/doctor.sh` | диагностика окружения + логи |
| `./scripts/smoke.sh` | HTTP-матрица PASS/FAIL |
| `./scripts/acceptance.sh` | приёмка по ТЗ + отчёт в `data/` |
| `./scripts/probe_token.py` | токен из web.log (без утечки) |
| `./scripts/probe_cli.sh` | `dsh`/`opencode --help` → правки run_*.sh |
| `./scripts/logs.sh` | хвосты всех логов |
| `./scripts/restart.sh` | stop + start |
| `./scripts/health.sh` | только JSON /health |
| `./scripts/wait_ready.sh` | ждать /health после старта |
| `make check` | то же, что check_once |

## Что остаётся ручным (1 раз в боте)

1. Кнопка «AIHub» открывает WebApp  
2. Карточки агентов видны  
3. Send / Interrupt  
4. «Полный интерфейс» DSH  
5. Смена mesh URL (tailscale serve) → кнопка сама обновилась  

Всё остальное закрывает `check_once`.

## Если FAIL

1. `./scripts/logs.sh 120`  
2. `./scripts/probe_token.py` — если токен не найден, допишите regex  
3. `./scripts/probe_cli.sh` — сверьте флаги с `run_dsh_web.sh` / `run_opencode.sh`  
4. Убедитесь, что **нет** `ai.aihub.aggregator` в launchctl  

## Авария

```bash
touch .kill          # всё → 503
rm -f .kill          # обратно
```

| `./scripts/open_url.sh` | local / LAN / mesh URL |
