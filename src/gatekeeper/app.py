"""FastAPI-приложение привратника."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Optional

from fastapi import (
    Depends,
    FastAPI,
    HTTPException,
    Request,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from ..common.audit import audit
from ..common.authpolicy import local_login_allowed
from ..common.config import get_settings, read_public_url_live
from ..common.netinfo import lan_http_urls, network_hint_message, is_loopback_ip
from ..common.logging import get_logger, setup_logging
from ..common.models import AuthRequest, AuthResponse, HealthResponse
from ..common.session import COOKIE_NAME, create_session_token, verify_session_token
from ..common.telegram_auth import validate_init_data
from .proxy import proxy_http, proxy_websocket
from .rate_limit import auth_limiter, general_limiter
from .security import SecurityHeadersMiddleware
from .middleware import RequestIdMiddleware

log = get_logger(__name__)


def _app_version() -> str:
    try:
        return Path(__file__).resolve().parents[2].joinpath("VERSION").read_text().strip() or "3.6.0"
    except Exception:
        return "3.6.0"


# Глобальные ссылки (заполняются при lifespan)
_aggregator: Any = None
_notifier: Any = None


def get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "0.0.0.0"


def require_session(request: Request) -> dict:
    """Dependency: проверяет cookie сессии."""
    settings = get_settings()
    if settings.is_kill_switch_active:
        raise HTTPException(status_code=503, detail="Сервис временно отключён")

    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=401, detail="Требуется авторизация")

    data = verify_session_token(token)
    if not data:
        raise HTTPException(status_code=401, detail="Сессия недействительна")
    return data


def _is_trusted_client(request: Request) -> bool:
    """Доверенная сторона для деталей /health: loopback (Mac, Tailscale Serve)
    или валидная сессия владельца. X-Forwarded-For НЕ используем — его можно
    подделать из LAN, а в lan_urls/network_hint входит SECRET_PATH."""
    settings = get_settings()
    if settings.env == "development":
        return True
    peer = request.client.host if request.client else ""
    if is_loopback_ip(peer):
        return True
    token = request.cookies.get(COOKIE_NAME)
    return bool(token and verify_session_token(token))


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    settings = get_settings()
    settings.ensure_secrets()
    settings.ensure_dirs()
    log.info(
        "gatekeeper_start",
        host=settings.gatekeeper_host,
        port=settings.gatekeeper_port,
        secret_path_set=bool(settings.secret_path and settings.secret_path not in ("/p/xxxxxxxx", "/p/", "")),
        token_set=bool(settings.telegram_bot_token),
    )

    # Ленивый импорт агрегатора
    global _aggregator, _notifier
    try:
        from ..aggregator.service import AggregatorService
        from ..notifier.service import NotifierService

        _notifier = NotifierService()
        _aggregator = AggregatorService(notifier=_notifier)
        await _aggregator.start()
        log.info("aggregator_started")
    except Exception as e:
        log.error("aggregator_start_failed", error=str(e))
        _aggregator = None
        _notifier = None

    # Периодическая очистка rate-limit словарей (защита от роста)
    async def _rate_prune_loop() -> None:
        while True:
            try:
                await asyncio.sleep(300)
                n1 = auth_limiter.prune()
                n2 = general_limiter.prune()
                if n1 or n2:
                    log.debug("rate_limit_pruned", auth=n1, general=n2)
            except asyncio.CancelledError:
                break
            except Exception as e:
                log.warning("rate_prune_error", error=str(e))

    prune_task = asyncio.create_task(_rate_prune_loop(), name="rate_prune")

    yield

    prune_task.cancel()
    try:
        await prune_task
    except asyncio.CancelledError:
        pass
    if _aggregator:
        await _aggregator.stop()
    log.info("gatekeeper_stop")


def create_app() -> FastAPI:
    settings = get_settings()
    # Генерируем секреты до создания app
    settings.ensure_secrets()

    app = FastAPI(
        title="AIHub",
        version=_app_version(),
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RequestIdMiddleware)

    # Статика
    static_dir = Path(__file__).resolve().parent.parent.parent / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    # ---------- Health (без secret path) ----------
    @app.get("/health", response_model=HealthResponse)
    async def health(request: Request):
        settings = get_settings()
        dsh_status = "unknown"
        oc_status = "unknown"
        if _aggregator:
            dsh_status = "online" if _aggregator.dsh_online else "offline"
            oc_status = "online" if _aggregator.opencode_online else "offline"
        pub = read_public_url_live() or settings.public_url
        # lan_urls/network_hint содержат SECRET_PATH — только доверенной стороне
        trusted = _is_trusted_client(request)
        lans = lan_http_urls(settings.gatekeeper_port, settings.secret_path) if trusted else []
        hint = (
            network_hint_message(has_mesh_url=bool(pub and ".ts.net" in pub), lan_urls=lans)
            if trusted
            else ""
        )
        return HealthResponse(
            status="ok" if not settings.is_kill_switch_active else "killed",
            version=_app_version(),
            dsh=dsh_status,
            opencode=oc_status,
            token_configured=bool(settings.telegram_bot_token),
            kill_switch=settings.is_kill_switch_active,
            public_url=pub,
            secret_path=settings.secret_path if (trusted or settings.env != "production") else "",
            network_mode=getattr(settings, "network_mode", "hybrid") or "hybrid",
            lan_urls=lans,
            network_hint=hint,
        )

    # ---------- Secret path prefix ----------
    secret = settings.secret_path.rstrip("/") or "/p/local"

    # CSS/JS под secret path (относительные пути из index.html)
    if static_dir.exists():
        css_dir = static_dir / "css"
        js_dir = static_dir / "js"
        if css_dir.exists():
            app.mount(secret + "/css", StaticFiles(directory=str(css_dir)), name="aihub_css")
        if js_dir.exists():
            app.mount(secret + "/js", StaticFiles(directory=str(js_dir)), name="aihub_js")

    # ---------- Auth ----------
    @app.post(f"{secret}/auth", response_model=AuthResponse)
    async def auth(request: Request, body: AuthRequest):
        settings = get_settings()
        if settings.is_kill_switch_active:
            return AuthResponse(ok=False, message="Сервис временно отключён")

        if not settings.telegram_bot_token:
            return AuthResponse(ok=False, message="Токен бота ещё не задан")

        ip = get_client_ip(request)
        if not auth_limiter.is_allowed(ip):
            log.warning("auth_rate_limited", ip=ip)
            raise HTTPException(status_code=429, detail="Слишком много попыток")

        result = validate_init_data(body.init_data)
        if not result.ok:
            if result.user and result.user.id != settings.owner_telegram_id:
                # Уведомление владельцу
                if _notifier:
                    await _notifier.notify_unauthorized(
                        user_id=result.user.id,
                        username=result.user.username,
                        first_name=result.user.first_name,
                    )
                audit(
                    "auth_denied",
                    user_id=result.user.id if result.user else None,
                    username=result.user.username if result.user else None,
                    ip=ip,
                    error=result.error,
                )
            return AuthResponse(ok=False, message=result.error or "Отказ")

        assert result.user is not None
        token = create_session_token(result.user.id)
        response = JSONResponse(
            content=AuthResponse(ok=True, message="OK").model_dump()
        )
        # path=SECRET_PATH; Secure только на HTTPS (LAN http иначе ломает сессию)
        cookie_path = settings.secret_path.rstrip("/") or "/"
        secure = (request.url.scheme == "https") and (settings.env != "development")
        response.set_cookie(
            key=COOKIE_NAME,
            value=token,
            httponly=True,
            secure=secure,
            samesite="lax",
            path=cookie_path,
            max_age=7 * 24 * 3600,
        )
        audit("auth_success", user_id=result.user.id, ip=ip)
        log.info("auth_ok", user_id=result.user.id)
        return response

    # ---------- DEV auth (политика LOCAL_LOGIN) ----------
    @app.post(f"{secret}/auth/dev")
    async def auth_dev(request: Request):
        """Локальный вход без Telegram по политике LOCAL_LOGIN."""
        settings = get_settings()
        peer = request.client.host if request.client else ""
        if not local_login_allowed(getattr(settings, "local_login", "loopback"), peer):
            raise HTTPException(status_code=404, detail="Not Found")
        token = create_session_token(settings.owner_telegram_id)
        response = JSONResponse(
            content={"ok": True, "message": "dev session", "user_id": settings.owner_telegram_id}
        )
        cookie_path = settings.secret_path.rstrip("/") or "/"
        response.set_cookie(
            key=COOKIE_NAME,
            value=token,
            httponly=True,
            secure=False,
            samesite="lax",
            path=cookie_path,
            max_age=7 * 24 * 3600,
        )
        audit("auth_dev", user_id=settings.owner_telegram_id, ip=get_client_ip(request))
        return response

    @app.get(f"{secret}/api/diag")
    async def api_diag(request: Request):
        """Диагностика для скриптов acceptance (без секретов в production-ответе)."""
        settings = get_settings()
        # В production требуем сессию; в development — нет
        if settings.env != "development":
            token = request.cookies.get(COOKIE_NAME)
            sess = verify_session_token(token) if token else None
            if not sess:
                raise HTTPException(status_code=401, detail="Unauthorized")
        from ..common.dsh_token import get_dsh_token
        from ..common.circuit import dsh_circuit, opencode_circuit
        tok = get_dsh_token()
        return {
            "env": settings.env,
            "version": _app_version(),
            "secret_path": settings.secret_path,
            "public_url": read_public_url_live() or settings.public_url,
            "network_mode": getattr(settings, "network_mode", "hybrid"),
            "lan_urls": lan_http_urls(settings.gatekeeper_port, settings.secret_path),
            "token_configured": bool(settings.telegram_bot_token),
            "dsh_token_present": bool(tok),
            "dsh_token_len": len(tok) if tok else 0,
            "dsh_online": bool(getattr(_aggregator, "dsh_online", False)) if _aggregator else False,
            "opencode_online": bool(getattr(_aggregator, "opencode_online", False)) if _aggregator else False,
            "agents": len(getattr(_aggregator, "_agents", {})) if _aggregator else 0,
            "ws_subscribers": len(getattr(_aggregator, "_subscribers", [])) if _aggregator else 0,
            "circuit": {
                "dsh": dsh_circuit.state(),
                "opencode": opencode_circuit.state(),
            },
            "kill_switch": settings.is_kill_switch_active,
            "dsh_base": settings.dsh_web_base,
            "opencode_base": settings.opencode_base,
        }

    # ---------- Главная страница AIHub ----------
    @app.get(f"{secret}/", response_class=HTMLResponse)
    @app.get(f"{secret}", response_class=HTMLResponse)
    async def aihub_index(request: Request):
        """HTML отдаём без cookie — JS сам делает /auth и дальше ходит с сессией."""
        settings = get_settings()
        if settings.is_kill_switch_active:
            raise HTTPException(status_code=503, detail="Сервис временно отключён")
        if not general_limiter.is_allowed(get_client_ip(request)):
            raise HTTPException(status_code=429, detail="Rate limit")

        index_path = static_dir / "index.html"
        if index_path.exists():
            return FileResponse(index_path)
        return HTMLResponse(
            content="<h1>AIHub</h1><p>static/index.html не найден</p>",
            status_code=200,
        )

    # ---------- API агрегатора ----------
    @app.get(f"{secret}/api/agents")
    async def api_agents(
        request: Request,
        session: dict = Depends(require_session),
        system: Optional[str] = None,
        status_filter: Optional[str] = None,
        active_only: bool = False,
    ):
        if not general_limiter.is_allowed(get_client_ip(request)):
            raise HTTPException(status_code=429, detail="Rate limit")
        if not _aggregator:
            return JSONResponse({"agents": [], "error": "aggregator offline"})
        agents = _aggregator.get_agents(
            system=system, status=status_filter, active_only=active_only
        )
        return {"agents": [a.to_dict() for a in agents]}

    @app.get(f"{secret}/api/agents/{{agent_id}}")
    async def api_agent_detail(
        agent_id: str,
        request: Request,
        session: dict = Depends(require_session),
    ):
        if not _aggregator:
            raise HTTPException(status_code=503, detail="aggregator offline")
        agent = _aggregator.get_agent(agent_id)
        if not agent:
            raise HTTPException(status_code=404, detail="Агент не найден")
        data = agent.to_dict()
        data["history"] = _aggregator.get_history(agent_id)
        return data

    @app.get(f"{secret}/api/agents/{{agent_id}}/history")
    async def api_agent_history(
        agent_id: str,
        request: Request,
        session: dict = Depends(require_session),
    ):
        if not _aggregator:
            raise HTTPException(status_code=503, detail="aggregator offline")
        hist = await _aggregator.fetch_remote_history(agent_id)
        return {"history": hist}

    @app.get(f"{secret}/api/search")
    async def api_search(
        request: Request,
        session: dict = Depends(require_session),
        q: str = "",
    ):
        if not _aggregator:
            return {"agents": []}
        agents = _aggregator.search(q) if q else _aggregator.get_agents()
        return {"agents": [a.to_dict() for a in agents], "q": q}

    @app.post(f"{secret}/api/agents/{{agent_id}}/action")
    async def api_agent_action(
        agent_id: str,
        request: Request,
        session: dict = Depends(require_session),
    ):
        if not general_limiter.is_allowed(get_client_ip(request)):
            raise HTTPException(status_code=429, detail="Rate limit")
        body = await request.json()
        action = body.get("action")
        payload = body.get("payload", {})
        if not action:
            raise HTTPException(status_code=400, detail="action required")

        audit(
            "agent_action",
            agent_id=agent_id,
            action=action,
            user_id=session.get("uid"),
            ip=get_client_ip(request),
            confirmed=bool(payload.get("_confirmed")),
        )

        if not _aggregator:
            raise HTTPException(status_code=503, detail="aggregator offline")

        result = await _aggregator.perform_action(agent_id, action, payload)
        return result

    @app.get(f"{secret}/api/sessions")
    async def api_sessions(
        request: Request,
        session: dict = Depends(require_session),
        q: Optional[str] = None,
    ):
        if not _aggregator:
            return {"sessions": []}
        return {"sessions": _aggregator.list_sessions(query=q)}

    @app.post(f"{secret}/api/sessions/new")
    async def api_new_session(
        request: Request,
        session: dict = Depends(require_session),
    ):
        """Создание новой сессии (дорогая операция — требует _confirmed)."""
        if not general_limiter.is_allowed(get_client_ip(request)):
            raise HTTPException(status_code=429, detail="Rate limit")
        body = await request.json()
        system = body.get("system", "dsh")
        payload = body.get("payload", {})
        audit(
            "new_session",
            system=system,
            user_id=session.get("uid"),
            ip=get_client_ip(request),
            confirmed=bool(payload.get("_confirmed")),
        )
        if not _aggregator:
            raise HTTPException(status_code=503, detail="aggregator offline")
        # Используем фиктивный agent_id для маршрутизации по system
        fake_id = f"{system}:_new"
        from ..common.models import AgentState, SystemType, AgentStatus
        from datetime import datetime, timezone

        temp = AgentState(
            id=fake_id,
            system=SystemType.DSH if system == "dsh" else SystemType.OPENCODE,
            title="new",
            status=AgentStatus.UNKNOWN,
            updated_at=datetime.now(timezone.utc),
        )
        _aggregator._agents[fake_id] = temp
        try:
            result = await _aggregator.perform_action(fake_id, "new_session", payload)
        finally:
            _aggregator._agents.pop(fake_id, None)
        return result


    @app.get(f"{secret}/api/projects")
    async def api_projects(request: Request, session: dict = Depends(require_session)):
        if not general_limiter.is_allowed(get_client_ip(request)):
            raise HTTPException(status_code=429, detail="Rate limit")
        try:
            from ..common.opencode_client import get_opencode_client
            projects = await get_opencode_client().list_projects()
        except Exception:
            projects = []
        return {"projects": projects}

    @app.get(f"{secret}/api/models")
    async def api_models(request: Request, session: dict = Depends(require_session)):
        if not general_limiter.is_allowed(get_client_ip(request)):
            raise HTTPException(status_code=429, detail="Rate limit")
        try:
            from ..common.opencode_client import get_opencode_client
            models = await get_opencode_client().list_models()
        except Exception:
            models = []
        return {"models": models}

    @app.get(f"{secret}/api/metrics")
    async def api_metrics(request: Request, session: dict = Depends(require_session)):
        from ..common.circuit import dsh_circuit, opencode_circuit
        agents = _aggregator.get_agents() if _aggregator else []
        by_status = {}
        by_system = {}
        for a in agents:
            by_status[a.status.value] = by_status.get(a.status.value, 0) + 1
            by_system[a.system.value] = by_system.get(a.system.value, 0) + 1
        return {
            "agents_total": len(agents),
            "by_status": by_status,
            "by_system": by_system,
            "dsh_online": getattr(_aggregator, "dsh_online", False) if _aggregator else False,
            "opencode_online": getattr(_aggregator, "opencode_online", False) if _aggregator else False,
            "circuit": {"dsh": dsh_circuit.state(), "opencode": opencode_circuit.state()},
            "ws_subscribers": len(getattr(_aggregator, "_subscribers", [])) if _aggregator else 0,
        }

    @app.get(f"{secret}/api/settings")
    async def api_settings_get(request: Request, session: dict = Depends(require_session)):
        settings = get_settings()
        return {
            "owner_id": settings.owner_telegram_id,
            "token_configured": bool(settings.telegram_bot_token),
            "public_url": read_public_url_live() or settings.public_url,
            "dsh_port": settings.dsh_web_port,
            "opencode_port": settings.opencode_serve_port,
            "env": settings.env,
            "version": _app_version(),
            "kill_switch": settings.is_kill_switch_active,
        }

        # ---------- WebSocket единого потока ----------
    @app.websocket(f"{secret}/ws")
    async def ws_events(websocket: WebSocket):
        # Проверяем cookie вручную (WS не поддерживает Depends так же)
        settings = get_settings()
        if settings.is_kill_switch_active:
            await websocket.close(code=1013)
            return

        token = websocket.cookies.get(COOKIE_NAME)
        if not token or not verify_session_token(token):
            await websocket.close(code=1008)
            return

        await websocket.accept()
        if not _aggregator:
            await websocket.send_json({"type": "error", "message": "aggregator offline"})
            await websocket.close()
            return

        queue = await _aggregator.subscribe()
        try:
            # Сразу отправляем snapshot
            snapshot = _aggregator.get_snapshot()
            await websocket.send_json(snapshot)

            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=30.0)
                    await websocket.send_json(event)
                except asyncio.TimeoutError:
                    # keepalive
                    await websocket.send_json({"type": "ping"})
        except WebSocketDisconnect:
            pass
        except Exception as e:
            log.debug("ws_events_error", error=str(e))
        finally:
            await _aggregator.unsubscribe(queue)

    # ---------- Прокси DSH ----------
    @app.api_route(
        f"{secret}/dsh/{{path:path}}",
        methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
    )
    async def dsh_proxy(
        path: str,
        request: Request,
        session: dict = Depends(require_session),
    ):
        if not general_limiter.is_allowed(get_client_ip(request)):
            raise HTTPException(status_code=429, detail="Rate limit")
        return await proxy_http(request, path)

    @app.websocket(f"{secret}/dsh/{{path:path}}")
    async def dsh_ws(websocket: WebSocket, path: str):
        settings = get_settings()
        if settings.is_kill_switch_active:
            await websocket.close(code=1013)
            return
        token = websocket.cookies.get(COOKIE_NAME)
        if not token or not verify_session_token(token):
            await websocket.close(code=1008)
            return
        await proxy_websocket(websocket, path)

    # ---------- 404 для всего остального ----------
    @app.api_route("/{full_path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"])
    async def catch_all(full_path: str):
        raise HTTPException(status_code=404, detail="Не найдено")

    return app


app = create_app()
