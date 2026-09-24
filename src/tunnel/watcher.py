"""
Сторож доступа к WebApp:

NETWORK_MODE=hybrid (по умолчанию) / tailscale:
  - НЕ поднимает cloudflared в интернет
  - ждёт gatekeeper, берёт HTTPS URL из Tailscale Serve / MagicDNS
  - обновляет PUBLIC_URL + setChatMenuButton
  - дома в LAN доступ по http://<IP-Mac>:<port>/p/…/ без Tailscale
  - если mesh URL нет — раз в 6 ч подсказка владельцу в Telegram

NETWORK_MODE=cloudflare:
  - quick tunnel trycloudflare.com (публичный вход)
  - заглушка → gatekeeper, парсинг URL, menu button
"""

from __future__ import annotations

import asyncio
import json
import re
import shutil
import signal
import subprocess
import time
from pathlib import Path
from typing import Optional

import httpx

from ..common.config import get_settings, read_public_url_live
from ..common.envfile import upsert_env
from ..common.logging import get_logger, setup_logging
from ..common.netinfo import lan_http_urls, network_hint_message
from ..common.throttle import mark_notified, notification_due
from .stub import StubServer

log = get_logger(__name__)

URL_RE_CF = re.compile(
    r"https://[a-zA-Z0-9.-]+\.trycloudflare\.com",
    re.IGNORECASE,
)
URL_RE_TS = re.compile(
    r"https://[a-zA-Z0-9.-]+\.ts\.net",
    re.IGNORECASE,
)


class TunnelWatcher:
    def __init__(self) -> None:
        self._proc: Optional[subprocess.Popen] = None
        self._current_url: str = ""
        self._running = False
        self._gatekeeper_ready = False
        self._stub: Optional[StubServer] = None
        self._target: str = ""
        self._last_missing_log: float = 0.0

    def _log_missing(self, event: str, **kw: object) -> None:
        """Не спамить один и тот же warning каждые 15 с — раз в 5 минут."""
        now = time.time()
        if now - self._last_missing_log >= 300:
            self._last_missing_log = now
            log.warning(event, **kw)

    @property
    def gatekeeper_url(self) -> str:
        s = get_settings()
        return f"http://{s.gatekeeper_host}:{s.gatekeeper_port}"

    @property
    def stub_url(self) -> str:
        s = get_settings()
        return f"http://{s.gatekeeper_host}:{s.gatekeeper_port + 1}"

    async def start(self) -> None:
        self._running = True
        setup_logging()
        settings = get_settings()
        mode = (settings.network_mode or "hybrid").strip().lower()
        log.info("tunnel_watcher_start", mode=mode)

        if mode in ("cloudflare", "cf", "public"):
            await self._run_cloudflare_mode()
        else:
            # hybrid | tailscale | mesh | ts — без публичного cloudflared
            await self._run_tailscale_mode()

    # ─── Tailscale mesh (без Funnel) ─────────────────────────────────

    async def _run_tailscale_mode(self) -> None:
        """Только private mesh: URL из Tailscale Serve / DNSName, без публичного входа."""
        log.info("mode_tailscale_mesh_no_public_funnel")
        asyncio.create_task(self._watch_gatekeeper_flag_only())

        while self._running:
            try:
                if not self._gatekeeper_ready:
                    await asyncio.sleep(2)
                    continue
                urls = await self._detect_tailscale_urls()
                live = ""
                for cand in urls:
                    if await self._url_responds(cand):
                        live = cand
                        break
                if live:
                    if live != self._current_url:
                        await self._on_new_url(live)
                else:
                    if urls:
                        self._log_missing("tailscale_url_unreachable", candidates=urls)
                        await self._notify_mesh_missing(reason="unreachable")
                    else:
                        self._log_missing(
                            "tailscale_url_missing",
                            hint="запустите: ./scripts/enable_tailscale_serve.sh",
                        )
                        await self._notify_mesh_missing(reason="missing")
            except Exception as e:
                log.error("tailscale_watch_error", error=str(e))
            await asyncio.sleep(15)

    async def _detect_tailscale_urls(self) -> list[str]:
        """Кандидаты HTTPS URL: PUBLIC_URL из .env, `tailscale serve status`, DNSName.

        DNSName — только эвристика для старых CLI, где `serve status --json` недоступен:
        он ничего не говорит о том, что Serve реально настроен. Доступность кандидата
        проверяет `_url_responds`."""
        cands: list[str] = []

        def add(u: str) -> None:
            u = u.rstrip("/")
            if u and u not in cands:
                cands.append(u)

        # 1) PUBLIC_URL из .env (live — обход lru_cache после enable_tailscale_serve.sh)
        pub = read_public_url_live()
        if pub and ".ts.net" in pub:
            add(pub)

        # 2) tailscale serve status --json
        serve_known = False
        try:
            r = subprocess.run(
                ["tailscale", "serve", "status", "--json"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if r.returncode == 0:
                serve_known = True
                m = URL_RE_TS.search(r.stdout or "")
                if m:
                    add(m.group(0))
        except FileNotFoundError:
            log.error("tailscale_cli_not_found")
            return cands
        except Exception as e:
            log.debug("serve_status_error", error=str(e))

        # 3) DNSName из status --json → https://<dnsname> (только если serve status недоступен)
        if not serve_known:
            dns = self._dns_name()
            if dns:
                add(f"https://{dns}")
        return cands

    def _dns_name(self) -> str:
        try:
            r = subprocess.run(
                ["tailscale", "status", "--json"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if r.returncode == 0 and r.stdout.strip():
                data = json.loads(r.stdout)
                dns = (data.get("Self") or {}).get("DNSName") or ""
                return dns.rstrip(".")
        except Exception as e:
            log.debug("status_json_error", error=str(e))
        return ""

    async def _url_responds(self, url: str) -> bool:
        """Serve реально работает: /health отвечает 200 и это наш AIHub."""
        try:
            async with httpx.AsyncClient(timeout=4.0) as client:
                r = await client.get(f"{url.rstrip('/')}/health")
                if r.status_code != 200:
                    return False
                try:
                    return str(r.json().get("status", "")) in ("ok", "killed")
                except Exception:
                    return False
        except Exception:
            return False

    async def _watch_gatekeeper_flag_only(self) -> None:
        async with httpx.AsyncClient(timeout=3.0) as client:
            while self._running:
                try:
                    r = await client.get(f"{self.gatekeeper_url}/health")
                    if r.status_code == 200:
                        if not self._gatekeeper_ready:
                            self._gatekeeper_ready = True
                            log.info("gatekeeper_ready")
                    else:
                        self._gatekeeper_ready = False
                except Exception:
                    self._gatekeeper_ready = False
                await asyncio.sleep(3)

    # ─── Cloudflare quick tunnel (публичный) ─────────────────────────

    async def _run_cloudflare_mode(self) -> None:
        settings = get_settings()
        self._stub = StubServer(settings.gatekeeper_host, settings.gatekeeper_port + 1)
        self._stub.start()
        self._target = self.stub_url
        log.info("tunnel_points_to_stub", url=self._target)
        asyncio.create_task(self._watch_gatekeeper_cf())

        while self._running:
            try:
                await self._run_cloudflared(self._target)
            except Exception as e:
                log.error("tunnel_error", error=str(e))
            if self._running:
                log.info("tunnel_restart_in_5s")
                await asyncio.sleep(5)

        if self._stub:
            self._stub.stop()

    async def _watch_gatekeeper_cf(self) -> None:
        async with httpx.AsyncClient(timeout=3.0) as client:
            while self._running:
                try:
                    r = await client.get(f"{self.gatekeeper_url}/health")
                    if r.status_code == 200:
                        if not self._gatekeeper_ready:
                            self._gatekeeper_ready = True
                            log.info("gatekeeper_ready_switching_tunnel")
                            self._target = self.gatekeeper_url
                            self._kill_tunnel()
                        await asyncio.sleep(15)
                        continue
                except Exception:
                    if self._gatekeeper_ready:
                        log.warning("gatekeeper_lost_falling_back_to_stub")
                        self._gatekeeper_ready = False
                        self._target = self.stub_url
                        self._kill_tunnel()
                await asyncio.sleep(2)

    def _kill_tunnel(self) -> None:
        if self._proc and self._proc.poll() is None:
            try:
                self._proc.send_signal(signal.SIGTERM)
                self._proc.wait(timeout=5)
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass
            self._proc = None

    async def _run_cloudflared(self, target: str) -> None:
        cmd = [
            "cloudflared",
            "tunnel",
            "--url",
            target,
            "--no-autoupdate",
        ]
        log.info("starting_cloudflared", cmd=" ".join(cmd), target=target)
        self._proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        assert self._proc.stdout is not None
        loop = asyncio.get_event_loop()

        while self._running and self._proc.poll() is None:
            line = await loop.run_in_executor(None, self._proc.stdout.readline)
            if not line:
                await asyncio.sleep(0.1)
                continue
            line = line.strip()
            if line:
                log.debug("cloudflared", line=line[:200])
            m = URL_RE_CF.search(line)
            if m:
                url = m.group(0)
                if url != self._current_url:
                    await self._on_new_url(url)

        if self._proc and self._proc.poll() is not None:
            log.warning("cloudflared_exited", code=self._proc.returncode)

    # ─── общее ───────────────────────────────────────────────────────

    async def _on_new_url(self, url: str) -> None:
        log.info("public_url_detected", url=url)
        self._current_url = url
        self._update_env("PUBLIC_URL", url)
        try:
            from ..common.config import clear_settings_cache
            clear_settings_cache()
        except Exception:
            pass
        settings = get_settings()
        settings.public_url = url
        if self._gatekeeper_ready:
            await self._set_menu_button(url)
            await self._notify_network_hint(url)
        else:
            log.info("menu_button_skipped_not_ready")

    async def _notify_network_hint(self, public_url: str) -> None:
        """Один раз подсказать владельцу про LAN vs Tailscale."""
        settings = get_settings()
        flag = Path(settings.data_dir) / ".network_hint_sent"
        try:
            if flag.exists():
                return
            text = network_hint_message(
                has_mesh_url=bool(public_url and ".ts.net" in public_url),
                lan_urls=lan_http_urls(settings.gatekeeper_port, settings.secret_path),
            )
            from ..notifier.service import NotifierService

            ok = await NotifierService().send_text(text)
            if ok:
                flag.write_text(public_url, encoding="utf-8")
                log.info("network_hint_sent")
        except Exception as e:
            log.debug("network_hint_skip", error=str(e))

    async def _notify_mesh_missing(self, reason: str = "missing") -> None:
        """Mesh URL (*.ts.net) не найден/не отвечает: напомнить, не чаще 6 ч."""
        settings = get_settings()
        flag = Path(settings.data_dir) / ".mesh_missing_notified"
        if not notification_due(flag, ttl_sec=6 * 3600):
            return
        mark_notified(flag)
        if not settings.telegram_bot_token:
            return
        if reason == "unreachable":
            text = (
                "⚠️ AIHub: внешний HTTPS (*.ts.net) не отвечает.\n\n"
                "Проверьте на Mac: tailscale serve status\n"
                "и при необходимости: ./scripts/enable_tailscale_serve.sh\n\n"
                "Дома в Wi‑Fi всё работает по LAN без VPN (URL: ./scripts/status.sh)."
            )
        elif shutil.which("tailscale"):
            text = (
                "⚠️ AIHub: внешний доступ (*.ts.net) не найден.\n\n"
                "Вне дома кнопка «AIHub» не откроется, пока не настроен Tailscale Serve.\n"
                "На Mac выполните:\n"
                "  ./scripts/enable_tailscale_serve.sh\n"
                "и проверьте: tailscale serve status\n\n"
                "Дома в Wi‑Fi всё работает по LAN без VPN (URL: ./scripts/status.sh)."
            )
        else:
            text = (
                "⚠️ AIHub: Tailscale не установлен — вне дома доступ невозможен.\n\n"
                "1. Установите Tailscale на Mac и телефон: https://tailscale.com/download/mac\n"
                "2. На Mac: ./scripts/enable_tailscale_serve.sh\n"
                "3. На телефоне включите VPN Tailscale.\n\n"
                "Дома в Wi‑Fi всё работает по LAN без VPN (URL: ./scripts/status.sh)."
            )
        from ..notifier.service import NotifierService

        await NotifierService().send_text(text)
        log.info(
            "mesh_missing_notified",
            reason=reason,
            tailscale=bool(shutil.which("tailscale")),
        )

    async def _notify_menu_button_failed(self, status: int) -> None:
        """Кнопка в Telegram не обновилась — сказать владельцу, не чаще раза в час."""
        settings = get_settings()
        if not settings.telegram_bot_token:
            return
        flag = Path(settings.data_dir) / ".menu_button_failed_notified"
        if not notification_due(flag, ttl_sec=3600):
            return
        mark_notified(flag)
        from ..notifier.service import NotifierService

        await NotifierService().send_text(
            "⚠️ AIHub: не удалось обновить кнопку «AIHub» в Telegram "
            f"(HTTP {status}).\n"
            "Проверьте TELEGRAM_BOT_TOKEN и права бота."
        )

    def _update_env(self, key: str, value: str) -> None:
        upsert_env(Path(".env"), key, value)

    async def _set_menu_button(self, public_url: str) -> None:
        settings = get_settings()
        token = settings.telegram_bot_token
        if not token:
            log.warning("set_menu_button_no_token")
            return

        secret = settings.secret_path.rstrip("/")
        webapp_url = f"{public_url.rstrip('/')}{secret}/"

        api = f"https://api.telegram.org/bot{token}/setChatMenuButton"
        payload = {
            "menu_button": {
                "type": "web_app",
                "text": "AIHub",
                "web_app": {"url": webapp_url},
            }
        }
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                r = await client.post(api, json=payload)
                if r.status_code == 200 and r.json().get("ok"):
                    log.info("menu_button_updated", url=webapp_url)
                else:
                    log.warning(
                        "menu_button_failed",
                        status=r.status_code,
                        body=r.text[:300],
                    )
                    await self._notify_menu_button_failed(r.status_code)
        except Exception as e:
            log.error("menu_button_error", error=str(e))

    def stop(self) -> None:
        self._running = False
        self._kill_tunnel()
        if self._stub:
            self._stub.stop()


async def main() -> None:
    watcher = TunnelWatcher()

    def _signal_handler(*_args):
        watcher.stop()

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _signal_handler)
        except NotImplementedError:
            pass

    await watcher.start()


if __name__ == "__main__":
    asyncio.run(main())
