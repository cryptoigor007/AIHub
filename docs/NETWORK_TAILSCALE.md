# Сеть: hybrid (LAN + Tailscale)

## Поведение

| Где вы | Tailscale на телефоне | Как открыть AIHub |
|--------|----------------------|-------------------|
| Дома, Wi‑Fi Mac | **Необязателен** | Браузер: `http://<IP-Mac>:8787/p/…/` (см. `./scripts/status.sh` или `./scripts/open_url.sh`) |
| Вне дома / LTE | **Обязателен (VPN On)** | Кнопка «AIHub» → `https://….ts.net/p/…/` |

`/health` намеренно **не отдаёт** `lan_urls`/`network_hint` посторонним (в них входит SECRET_PATH) — только loopback на Mac, Tailscale Serve или сессии владельца. Для LAN URL используйте `status.sh` / `open_url.sh`.

Telegram WebApp-кнопка использует **HTTPS** (`*.ts.net`). Чистый HTTP LAN в Menu Button Telegram обычно **не** принимается — дома для кнопки удобнее всё же VPN On, либо браузер по LAN.

## Настройка

```bash
# .env
NETWORK_MODE=hybrid
GATEKEEPER_HOST=0.0.0.0

./scripts/start_all.sh
./scripts/enable_tailscale_serve.sh
```

## Режимы

- `hybrid` — по умолчанию (LAN + mesh)
- `tailscale` — только mesh, без акцента на LAN
- `cloudflare` — публичный quick tunnel (слабее)

**Funnel не использовать** для max-security.
