# Архитектура

**Сеть по умолчанию:** `NETWORK_MODE=hybrid` — дома LAN (HTTP) без Tailscale, вне дома Tailscale Serve (HTTPS, без публичного Funnel).
Опционально `NETWORK_MODE=cloudflare` — quick tunnel (только явный откат).

# Архитектура AIHub v3.5

```
Телефон
├── дома (Wi‑Fi): HTTP → http://<IP-Mac>:8787/p/…/     (браузер, без VPN)
└── вне дома: HTTPS → Tailscale Serve (mesh) → 127.0.0.1:8787
                         │ (опциональный откат: cloudflared → stub :8788 → gatekeeper)
                         ▼
ПРИВРАТНИК (FastAPI)
├── /health               (lan_urls/network_hint — только доверенной стороне)
├── /p/<secret>/auth
├── /p/<secret>/          UI
├── /p/<secret>/api/*     REST
├── /p/<secret>/ws        события
└── /p/<secret>/dsh/*     proxy → 127.0.0.1:3080

АГРЕГАТОР (in-process gatekeeper)
├── poll DSH ~3s
├── poll OpenCode ~5s
├── SSE OpenCode /events (reconnect)
├── state.json snapshot 30s
└── → WS + notifier

launchd KeepAlive:
  ai.aihub.dsh-web
  ai.aihub.opencode
  ai.aihub.gatekeeper   (+ aggregator)
  ai.aihub.tunnel-watcher (+ stub)
```

## Безопасность

SECRET_PATH, initData HMAC + owner allowlist, cookie (HttpOnly; Secure на HTTPS), rate-limit, audit, .kill.
Токен DSH только server-side. Без --trusted-host.
`/health` не раскрывает SECRET_PATH: lan_urls/network_hint отдаются только loopback (Mac, Tailscale Serve) или сессии владельца.
