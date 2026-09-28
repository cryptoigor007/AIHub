"""Telegram bot dialog for owner: /start /link + inline buttons (LAN / mesh).

Long-polling runs inside TunnelWatcher. Only OWNER_TELEGRAM_ID is answered.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Optional

import httpx

from ..common.config import get_settings, read_public_url_live
from ..common.logging import get_logger
from ..common.netinfo import lan_http_urls, load_netstate

log = get_logger(__name__)


class BotDialog:
    def __init__(self) -> None:
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._offset = 0
        self._commands_set = False

    def _offset_path(self) -> Path:
        return get_settings().data_dir / "tg_offset.json"

    def _load_offset(self) -> int:
        p = self._offset_path()
        if not p.exists():
            return 0
        try:
            return int(json.loads(p.read_text() or "{}").get("offset") or 0)
        except Exception:
            return 0

    def _save_offset(self, offset: int) -> None:
        p = self._offset_path()
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps({"offset": offset}), encoding="utf-8")
        except Exception:
            pass

    def _pause_file(self) -> Path:
        return get_settings().data_dir / ".tg_poll_pause"

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._offset = self._load_offset()
        self._task = asyncio.create_task(self._loop(), name="bot_dialog")

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except Exception:
                pass
            self._task = None

    async def _loop(self) -> None:
        backoff = 5
        # skip backlog once
        await self._drain_once()
        while self._running:
            if self._pause_file().exists():
                await asyncio.sleep(2)
                continue
            try:
                await self._poll()
                backoff = 5
            except Exception as e:
                log.warning("bot_dialog_poll_error", error=str(e))
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)

    async def _drain_once(self) -> None:
        """Skip old backlog on startup."""
        settings = get_settings()
        token = settings.telegram_bot_token
        if not token:
            return
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                r = await client.get(
                    f"https://api.telegram.org/bot{token}/getUpdates",
                    params={"offset": -1, "limit": 1, "timeout": 0},
                )
                data = r.json()
                results = data.get("result") or []
                if results:
                    self._offset = int(results[-1]["update_id"]) + 1
                    self._save_offset(self._offset)
        except Exception as e:
            log.debug("bot_dialog_drain_skip", error=str(e))

    async def _poll(self) -> None:
        settings = get_settings()
        token = settings.telegram_bot_token
        if not token:
            await asyncio.sleep(30)
            return
        async with httpx.AsyncClient(timeout=35) as client:
            r = await client.get(
                f"https://api.telegram.org/bot{token}/getUpdates",
                params={"offset": self._offset, "timeout": 25, "allowed_updates": json.dumps(["message", "callback_query"])},
            )
            data = r.json()
            if not data.get("ok"):
                await asyncio.sleep(5)
                return
            for upd in data.get("result") or []:
                self._offset = int(upd["update_id"]) + 1
                self._save_offset(self._offset)
                await self._handle(client, token, upd)

    async def _handle(self, client: httpx.AsyncClient, token: str, upd: dict) -> None:
        settings = get_settings()
        owner = str(settings.owner_telegram_id or "")
        msg = upd.get("message") or {}
        cb = upd.get("callback_query") or {}
        chat_id = str((msg.get("chat") or {}).get("id") or (cb.get("from") or {}).get("id") or "")
        if not chat_id or chat_id != owner:
            return  # silent ignore non-owner
        if cb:
            await self._on_callback(client, token, cb)
            return
        text = (msg.get("text") or "").strip()
        if text.startswith("/start") or text.startswith("/link"):
            await self._send_status(client, token, chat_id)

    async def _send_status(self, client: httpx.AsyncClient, token: str, chat_id: str) -> None:
        settings = get_settings()
        pub = read_public_url_live() or settings.public_url or ""
        net = load_netstate(settings.data_dir)
        channel = net.get("last_channel") or "—"
        serve_ok = bool(pub and pub.startswith("https://"))
        lines = [
            "AIHub",
            f"Внешний доступ: {'ок' if serve_ok else 'настраивается / выключен'}",
            f"Последний вход: {channel}",
        ]
        keyboard: list[list[dict[str, str]]] = []
        lan = lan_http_urls(settings.gatekeeper_port, settings.secret_path)
        row: list[dict[str, str]] = []
        if lan:
            row.append({"text": "Дома без VPN", "url": lan[0]})
        if serve_ok and pub:
            row.append({"text": "Вне дома", "url": pub if pub.endswith("/") else pub + "/"})
        if row:
            keyboard.append(row)
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "text": "\n".join(lines),
        }
        if keyboard:
            payload["reply_markup"] = json.dumps({"inline_keyboard": keyboard})
        try:
            await client.post(f"https://api.telegram.org/bot{token}/sendMessage", json=payload)
            # set commands once
            if not self._commands_set:
                r = await client.post(
                    f"https://api.telegram.org/bot{token}/setMyCommands",
                    json={"commands": [
                        {"command": "start", "description": "Статус и ссылки"},
                        {"command": "link", "description": "Ссылки AIHub"},
                    ]},
                )
                self._commands_set = bool(r.status_code == 200)
        except Exception as e:
            log.warning("bot_dialog_send_error", error=str(e))

    async def _on_callback(self, client: httpx.AsyncClient, token: str, cb: dict) -> None:
        # url buttons don't need callback handling; answer any residual
        try:
            await client.post(
                f"https://api.telegram.org/bot{token}/answerCallbackQuery",
                json={"callback_query_id": cb.get("id")},
            )
        except Exception:
            pass
