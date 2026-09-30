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
from .bot_dialog import BotDialog

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
        self._bot: Optional[BotDialog] = None
        self._last_serve_attempt: float = 0.0
        self._last_dns_fix: float = 0.0
        self._watch_task: Optional[asyncio.Task] = None

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

        # Owner bot dialog (D3)
        try:
            self._bot = BotDialog()
            await self._bot.start()
        except Exception as e:
            log.warning("bot_dialog_start_skip", error=str(e))

        if mode in ("cloudflare", "cf", "public"):
            await self._run_cloudflare_mode()
        else:
            # hybrid | tailscale | mesh | ts — без публичного cloudflared
            await self._run_tailscale_mode()

    # ─── Tailscale mesh (без Funnel) ─────────────────────────────────

    async def _run_tailscale_mode(self) -> None:
        """Только private mesh: URL из Tailscale Serve / DNSName, без публичного входа."""
        log.info("mode_tailscale_mesh_no_public_funnel")
        self._watch_task = asyncio.create_task(self._watch_gatekeeper_flag_only())

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
                    await self._maybe_remind_tailscale()
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
                        await self._maybe_autoserve()
                    await self._maybe_fix_acceptdns()
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
            code, out = await self._run_cli("tailscale", "serve", "status", "--json", timeout=10)
            if code == 127:
                log.error("tailscale_cli_not_found")
                return cands
            if code == 0:
                serve_known = True
                m = URL_RE_TS.search(out)
                if m:
                    add(m.group(0))
        except Exception as e:
            log.debug("serve_status_error", error=str(e))

        # 3) DNSName из status --json → https://<dnsname> (только если serve status недоступен)
        if not serve_known:
            dns = await self._dns_name()
            if dns:
                add(f"https://{dns}")
        return cands

    async def _run_cli(self, *args: str, timeout: float = 8.0) -> tuple[int, str]:
        """Асинхронный запуск CLI: не блокируем event loop (в отличие от subprocess.run).

        Возвращает (returncode, stdout+stderr). 127 — команда не найдена, 124 — таймаут.
        """
        try:
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
        except FileNotFoundError:
            return 127, ""
        try:
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            try:
                await proc.communicate()
            except Exception:
                pass
            return 124, ""
        return int(proc.returncode or 0), (out or b"").decode("utf-8", errors="replace")

    async def _dns_name(self) -> str:
        try:
            code, out = await self._run_cli("tailscale", "status", "--json", timeout=10)
            if code == 0 and out.strip():
                data = json.loads(out)
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
        """Mesh URL (*.ts.net) не найден/не отвечает: напомнить, не чаще 24 ч."""
        settings = get_settings()
        flag = Path(settings.data_dir) / ".mesh_missing_notified"
        if not notification_due(flag, ttl_sec=24 * 3600):
            return
        mark_notified(flag)
        if not settings.telegram_bot_token:
            return
        if reason == "unreachable":
            text = (
                "ℹ️ AIHub: внешний доступ (вне дома) сейчас недоступен.\n\n"
                "Обычно причина — на Mac выключен Tailscale.\n"
                "Проверить: tailscale status\n"
                "Включить: tailscale up (или кнопка в приложении Tailscale)\n\n"
                "Дома в Wi‑Fi всё работает по LAN без VPN — это напоминание, "
                "а не сбой дома."
            )
        elif shutil.which("tailscale"):
            text = (
                "ℹ️ AIHub: внешний доступ (вне дома) не настроен.\n\n"
                "Пока не настроен Tailscale Serve, кнопка «AIHub» вне дома не откроется.\n"
                "На Mac выполните:\n"
                "  ./scripts/enable_tailscale_serve.sh\n"
                "и проверьте: tailscale serve status\n\n"
                "Дома в Wi‑Fi всё работает по LAN без VPN (URL: ./scripts/status.sh)."
            )
        else:
            text = (
                "ℹ️ AIHub: Tailscale не установлен — вне дома доступ невозможен.\n\n"
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
        """D6: set default menu button AND explicit chat_id for owner."""
        settings = get_settings()
        token = settings.telegram_bot_token
        if not token:
            log.warning("set_menu_button_no_token")
            return

        secret = settings.secret_path.rstrip("/")
        webapp_url = f"{public_url.rstrip('/')}{secret}/"

        api = f"https://api.telegram.org/bot{token}/setChatMenuButton"
        menu = {
            "type": "web_app",
            "text": "AIHub",
            "web_app": {"url": webapp_url},
        }
        payloads = [{"menu_button": menu}]  # default
        owner = settings.owner_telegram_id
        if owner:
            payloads.append({"chat_id": int(owner) if str(owner).isdigit() else owner, "menu_button": menu})
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                ok_any = False
                last_status = 0
                for payload in payloads:
                    r = await client.post(api, json=payload)
                    last_status = r.status_code
                    if r.status_code == 200 and r.json().get("ok"):
                        ok_any = True
                        log.info("menu_button_updated", url=webapp_url, chat_id=payload.get("chat_id"))
                    else:
                        log.warning(
                            "menu_button_failed",
                            status=r.status_code,
                            body=r.text[:300],
                            chat_id=payload.get("chat_id"),
                        )
                if not ok_any:
                    await self._notify_menu_button_failed(last_status)
        except Exception as e:
            log.error("menu_button_error", error=str(e))


    async def _maybe_autoserve(self) -> None:
        """D1: try `tailscale serve` with hard timeout if AUTOSERVE enabled."""
        import os
        if os.environ.get("TAILSCALE_AUTOSERVE", "1") in ("0", "false", "no"):
            return
        now = time.time()
        if now - self._last_serve_attempt < 300:  # 5 min between attempts
            return
        self._last_serve_attempt = now
        settings = get_settings()
        port = settings.gatekeeper_port
        # Do not touch foreign serve config on another port
        try:
            _, out = await self._run_cli("tailscale", "serve", "status", timeout=8)
            if out.strip() and str(port) not in out and ("https" in out.lower() or "http://" in out):
                await self._notify_owner(
                    "Обнаружен чужой Tailscale Serve (не наш порт). AIHub его не трогает.",
                    key="foreign_serve",
                    hours=6,
                )
                return
        except Exception:
            pass
        cmd = [
            "tailscale", "serve", "--bg", f"--https=443",
            f"http://127.0.0.1:{port}",
        ]
        log.info("autoserve_attempt", cmd=" ".join(cmd))
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            try:
                out, _ = await asyncio.wait_for(proc.communicate(), timeout=15.0)
            except asyncio.TimeoutError:
                proc.kill()
                try:
                    await proc.communicate()
                except Exception:
                    pass
                log.warning("autoserve_timeout_killed")
                return
            text = (out or b"").decode("utf-8", errors="replace")
            log.info("autoserve_result", code=proc.returncode, out=text[:500])
            if "Serve is not enabled" in text or "serve is not enabled" in text.lower():
                m = re.search(r"https://login\.tailscale\.com/\S+", text)
                link = m.group(0) if m else "https://login.tailscale.com/admin/machines"
                await self._notify_owner(
                    f"Tailscale Serve не включён.\nВключите: {link}",
                    key="serve_not_enabled",
                    hours=3,
                )
            elif "certificate" in text.lower() or "HTTPS" in text:
                await self._notify_owner(
                    "Проблема с HTTPS-сертификатом Tailscale.\n"
                    "https://login.tailscale.com/admin/dns",
                    key="serve_cert",
                    hours=3,
                )
            elif URL_RE_TS.search(text) or proc.returncode == 0:
                # re-detect on next loop
                log.info("autoserve_likely_ok")
        except FileNotFoundError:
            log.warning("autoserve_no_tailscale_cli")
        except Exception as e:
            log.warning("autoserve_error", error=str(e))

    async def _maybe_fix_acceptdns(self) -> None:
        """D1: AcceptDNS auto-fix when TAILSCALE_AUTODNS=1."""
        import os
        if os.environ.get("TAILSCALE_AUTODNS", "1") in ("0", "false", "no"):
            return
        now = time.time()
        if now - self._last_dns_fix < 3600:
            return
        # Отмечаем попытку сразу: иначе при уже включённом accept-dns проверка
        # запускала бы `tailscale dns status` каждые 15 с (блокирующий subprocess).
        self._last_dns_fix = now
        try:
            _, out = await self._run_cli("tailscale", "dns", "status", timeout=8)
            if "accept-dns" in out.lower() and ("false" in out.lower() or "off" in out.lower()):
                await self._run_cli("tailscale", "set", "--accept-dns=true", timeout=10)
                await self._notify_owner(
                    "Включён AcceptDNS (tailscale set --accept-dns=true).",
                    key="acceptdns_on",
                    hours=12,
                )
        except Exception as e:
            log.debug("acceptdns_check_skip", error=str(e))

    async def _maybe_remind_tailscale(self) -> None:
        """D4: remind to enable Tailscale on phone ≤1/day."""
        import os
        from datetime import datetime, timezone
        if os.environ.get("TAILSCALE_REMIND", "1") in ("0", "false", "no"):
            return
        settings = get_settings()
        flag = settings.data_dir / ".ts_remind"
        if flag.exists():
            try:
                age = time.time() - flag.stat().st_mtime
                if age < 86400:
                    return
            except Exception:
                return
        # phone online? best-effort via tailscale status
        phone_seen = False
        try:
            _, out = await self._run_cli("tailscale", "status", "--json", timeout=10)
            data = json.loads(out or "{}")
            peers = data.get("Peer") or data.get("Peers") or {}
            if isinstance(peers, dict):
                for peer in peers.values():
                    os_name = str(peer.get("OS") or peer.get("os") or "")
                    if os_name.lower() in ("ios", "android"):
                        if peer.get("Online") or peer.get("Active"):
                            phone_seen = True
                            break
        except Exception:
            pass
        if phone_seen:
            return
        # check last LAN
        try:
            from ..common.netinfo import load_netstate
            net = load_netstate(settings.data_dir)
            seen_ts = net.get("last_lan_ts") or net.get("last_tailscale_ts")
            if seen_ts:
                from datetime import datetime as dt
                try:
                    ts = dt.fromisoformat(seen_ts.replace("Z", "+00:00")).timestamp()
                    if time.time() - ts < 86400:
                        return
                except Exception:
                    pass
        except Exception:
            pass
        await self._notify_owner(
            "Включите Tailscale на телефоне, чтобы открыть AIHub вне дома.",
            key="ts_remind",
            hours=24,
        )
        try:
            flag.parent.mkdir(parents=True, exist_ok=True)
            flag.write_text(datetime.now(timezone.utc).isoformat(), encoding="utf-8")
        except Exception:
            pass

    async def _notify_owner(self, text: str, *, key: str, hours: float = 1) -> None:
        """Throttled owner notification via notifier if available."""
        settings = get_settings()
        flag = Path(settings.data_dir) / f".notify_{key}"
        if not notification_due(flag, ttl_sec=hours * 3600):
            return
        mark_notified(flag)
        try:
            token = settings.telegram_bot_token
            owner = settings.owner_telegram_id
            if not token or not owner:
                return
            async with httpx.AsyncClient(timeout=15) as client:
                await client.post(
                    f"https://api.telegram.org/bot{token}/sendMessage",
                    json={"chat_id": owner, "text": text},
                )
        except Exception as e:
            log.debug("notify_owner_fail", error=str(e))

    def stop(self) -> None:
        self._running = False
        self._kill_tunnel()
        if self._stub:
            self._stub.stop()
        watch = getattr(self, "_watch_task", None)
        if watch and not watch.done():
            watch.cancel()
        bot = getattr(self, "_bot", None)
        if bot:
            bot._running = False
            task = getattr(bot, "_task", None)
            if task and not task.done():
                task.cancel()  # не ждём длинный long-poll
            self._bot = None


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
