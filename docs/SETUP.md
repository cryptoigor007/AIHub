# Настройка AIHub v3.6.0

## 1. Что делает мастер

```bash
cd ~/AIHub   # или каталог репозитория
./scripts/setup.sh
```

Мастер по шагам:

1. Проверяет окружение (Python, cryptography, Keychain, `.env`, `dsh` в PATH).
2. Создаёт/проверяет ключ в macOS Keychain и файл `data/vault.enc`.
3. Запрашивает токен Telegram-бота (ввод скрыт через getpass).
4. Определяет `OWNER_TELEGRAM_ID` (getUpdates / fallback).
5. Генерирует `COOKIE_SECRET`, `SECRET_PATH`, `OPENCODE_SERVER_PASSWORD` в vault.
6. Мигрирует legacy-секреты из `.env` (scrub + chmod 600).
7. Пишет несекретные настройки в `.env` (`ENV`, `LOCAL_LOGIN=loopback`, `NETWORK_MODE=hybrid`).
8. Предлагает перезапуск сервисов.

Повторный запуск с перезаписью: `./scripts/setup.sh --force`.

## 2. Telegram пошагово

1. Откройте [@BotFather](https://t.me/BotFather) → `/newbot`.
2. Укажите имя и username (должен заканчиваться на `_bot`).
3. Скопируйте токен (`123456:ABC-DEF...`).
4. Вставьте токен в мастер (в терминале; **не** в чат и **не** в код).
5. Нажмите **Start** у своего бота в Telegram.
6. Мастер сам определит ваш ID и отправит тестовое сообщение.
7. Если ID не определился: [@userinfobot](https://t.me/userinfobot) → скопируйте id → введите вручную в мастере.

## 3. Где секреты

| Что | Где |
|-----|-----|
| Токен бота, owner id, cookie, secret path, пароль OpenCode | `data/vault.enc` (AES-256-GCM) |
| Ключ шифрования | macOS Keychain, service `ai.aihub.vault` |
| Несекретные настройки | `.env` (права 600) |

Проверка без значений:

```bash
./scripts/vault_cli.py status
```

В git и архивы `data/`, `.env`, `*.enc` не попадают.

## 4. Keychain-промпты

При первом чтении ключа из launchd/терминала macOS может показать диалог доступа.
Нажмите **Always Allow**. После обновления Python:

```bash
./scripts/vault_cli.py reauth
```

Проверено на этом Mac (24.09.2026, первый запуск v3.6.0): миграция секретов и
чтение ключа из launchd прошли без диалогов — ключ создаёт и читает тот же
Python из `.venv`.

## 5. Потеря ключа или файла vault

Повторите `./scripts/setup.sh --force`. Все сессии инвалидируются, `SECRET_PATH` меняется — старые ссылки перестанут работать.

## 6. Доступ

- **На Mac:** `http://127.0.0.1:8787` + secret path (из vault / UI).
- **Телефон (дома):** кнопка в Telegram WebApp.
- **Вне дома:** `./scripts/enable_tailscale_serve.sh` (mesh/HTTPS).

Локальный вход без Telegram: `LOCAL_LOGIN=loopback` (только 127.0.0.1/::1).  
Для теста с телефона в LAN: `LOCAL_LOGIN=lan` в `.env`.

## 7. Диагностика

```bash
./scripts/doctor.sh    # в т.ч. блок --- vault ---
./scripts/logs.sh
./scripts/smoke.sh
./scripts/check_once.sh
```
