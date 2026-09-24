"""Отдельный HTTP-процесс агрегатора (launchd ai.aihub.aggregator).

Слушает 127.0.0.1:8789 — только localhost.
Gatekeeper может работать со встроенным агрегатором ИЛИ проксировать сюда
(если AGGREGATOR_URL задан).
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
import uvicorn

from src.common.config import get_settings
from src.common.logging import setup_logging, get_logger
from src.aggregator.service import AggregatorService
from src.notifier.service import NotifierService

log = get_logger(__name__)
_agg: AggregatorService | None = None


def create_aggregator_app() -> FastAPI:
    app = FastAPI(title="AIHub Aggregator", docs_url=None, redoc_url=None)

    @app.on_event("startup")
    async def _start():
        global _agg
        setup_logging()
        settings = get_settings()
        settings.ensure_dirs()
        notifier = NotifierService()
        _agg = AggregatorService(notifier=notifier)
        await _agg.start()
        log.info("aggregator_standalone_started")

    @app.on_event("shutdown")
    async def _stop():
        if _agg:
            await _agg.stop()

    @app.get("/health")
    async def health():
        return {
            "status": "ok",
            "dsh_online": _agg.dsh_online if _agg else False,
            "opencode_online": _agg.opencode_online if _agg else False,
        }

    @app.get("/snapshot")
    async def snapshot():
        if not _agg:
            return JSONResponse({"error": "not ready"}, status_code=503)
        return _agg.get_snapshot()

    @app.get("/agents")
    async def agents(system: str | None = None, status: str | None = None, active_only: bool = False):
        if not _agg:
            return {"agents": []}
        return {
            "agents": [
                a.to_dict()
                for a in _agg.get_agents(system=system, status=status, active_only=active_only)
            ]
        }

    @app.get("/agents/{agent_id}")
    async def agent_detail(agent_id: str):
        if not _agg:
            return JSONResponse({"error": "not ready"}, status_code=503)
        a = _agg.get_agent(agent_id)
        if not a:
            return JSONResponse({"error": "not found"}, status_code=404)
        data = a.to_dict()
        data["history"] = _agg.get_history(agent_id)
        return data

    @app.get("/agents/{agent_id}/history")
    async def agent_history(agent_id: str):
        if not _agg:
            return {"history": []}
        return {"history": _agg.get_history(agent_id)}

    @app.get("/sessions")
    async def sessions(q: str | None = None):
        if not _agg:
            return {"sessions": []}
        return {"sessions": _agg.list_sessions(query=q)}

    @app.post("/agents/{agent_id}/action")
    async def action(agent_id: str, body: dict):
        if not _agg:
            return JSONResponse({"error": "not ready"}, status_code=503)
        return await _agg.perform_action(
            agent_id, body.get("action", ""), body.get("payload") or {}
        )

    @app.websocket("/ws")
    async def ws(websocket: WebSocket):
        await websocket.accept()
        if not _agg:
            await websocket.close()
            return
        q = await _agg.subscribe()
        try:
            await websocket.send_json(_agg.get_snapshot())
            while True:
                try:
                    event = await asyncio.wait_for(q.get(), timeout=30.0)
                    await websocket.send_json(event)
                except asyncio.TimeoutError:
                    await websocket.send_json({"type": "ping"})
        except WebSocketDisconnect:
            pass
        finally:
            await _agg.unsubscribe(q)

    return app


def main() -> None:
    settings = get_settings()
    port = int(getattr(settings, "aggregator_port", 8789) or 8789)
    uvicorn.run(
        create_aggregator_app(),
        host="127.0.0.1",
        port=port,
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    main()
