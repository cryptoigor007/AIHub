"""Отправка уведомлений владельцу в Telegram."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

import httpx

from ..common.config import get_settings
from ..common.logging import get_logger

if TYPE_CHECKING:
    from ..common.models import AgentState

log = get_logger(__name__)

TEMPLATES = {
    "completed": 'Агент «{title}» ({system}) завершил работу.{extra}',
    "failed": 'Агент «{title}» ({system}) упал.{extra}',
    "waiting": 'Агент «{title}» ({system}) ждёт подтверждения / ответа.{extra}',
}


class NotifierService:
    async def send_text(self, text: str) -> bool:
        """Публичная отправка произвольного текста владельцу (HTML parse mode)."""
        settings = get_settings()
        token = settings.telegram_bot_token
        if not token:
            log.debug("notifier_no_token")
            return False
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {
            "chat_id": settings.owner_telegram_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                r = await client.post(url, json=payload)
                if r.status_code != 200:
                    log.warning(
                        "telegram_send_failed",
                        status=r.status_code,
                        body=(r.text or "")[:200],
                    )
                    return False
                return True
        except Exception as e:
            log.error("telegram_send_error", error=str(e))
            return False

    def _extra(self, agent: "AgentState") -> str:
        parts = []
        if agent.project:
            parts.append(f"\n📁 {agent.project}")
        model = (agent.meta or {}).get("model")
        if model:
            variant = (agent.meta or {}).get("variant")
            parts.append(f"\n🤖 {model}" + (f" ({variant})" if variant else ""))
        if agent.last_step:
            parts.append(f"\n→ {agent.last_step[:120]}")
        if agent.cost is not None:
            parts.append(f"\n💰 ${float(agent.cost):.4f}")
        return "".join(parts)

    async def notify_agent(self, kind: str, agent: "AgentState") -> None:
        tpl = TEMPLATES.get(kind)
        if not tpl:
            return
        text = tpl.format(
            title=agent.title or agent.id,
            system=agent.system.value.upper(),
            extra=self._extra(agent),
        )
        await self.send_text(text)
        log.info("notified", kind=kind, agent_id=agent.id)

    async def notify_unauthorized(
        self,
        user_id: int,
        username: str = "",
        first_name: str = "",
    ) -> None:
        text = (
            f"⚠️ Попытка доступа к AIHub\n"
            f"user_id: <code>{user_id}</code>\n"
            f"username: @{username or '—'}\n"
            f"имя: {first_name or '—'}\n"
            f"время: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC"
        )
        await self.send_text(text)
