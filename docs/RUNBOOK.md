# Runbook AIHub v3.6.0

## Штатный старт (hybrid)

1. Tailscale на Mac залогинен
2. `./scripts/start_all.sh`
3. `./scripts/enable_tailscale_serve.sh`
4. На телефоне Tailscale VPN On
5. `./scripts/status.sh` — gatekeeper=ok, URL `*.ts.net`

## Кнопка «AIHub» не открывается

- VPN Tailscale на телефоне включён?
- `tailscale serve status` на Mac
- PUBLIC_URL в .env = https://….ts.net
- `./scripts/open_url.sh`
- `./scripts/logs.sh 80`

## DSH offline / 401

- `./scripts/probe_cli.sh`
- `./scripts/probe_token.py`
- Рестарт dsh-web через launchctl

## OpenCode offline

- `opencode serve --help` → scripts/run_opencode.sh
- Порт 4096

## Двойные уведомления

```bash
launchctl unload ~/Library/LaunchAgents/ai.aihub.aggregator.plist 2>/dev/null
```

## Откат на публичный tunnel

NETWORK_MODE=cloudflare в .env, brew install cloudflared, рестарт tunnel-watcher.

## Авария

```bash
touch ~/AIHub/.kill
rm -f ~/AIHub/.kill
```

## Не делать

- Хардкод trycloudflare при mesh
- tailscale funnel «для удобства»
- ai.aihub.aggregator sidecar
- /setmenubutton вручную в BotFather
