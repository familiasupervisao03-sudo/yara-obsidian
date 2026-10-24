"""Fábrica da aplicação FastAPI do TITAN."""

from __future__ import annotations

import logging
import mimetypes
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from titan import __version__
from titan.auth.service import AuthService, LoginThrottle
from titan.config.settings import Settings, get_settings
from titan.core.runtime import prepare_runtime
from titan.db.engine import make_engine, make_session_factory
from titan_api.deps import AppContext
from titan.tasks.runner import TaskRunner
from titan.tasks.service import recover_on_startup
from titan.voice.engines import VoiceService
from titan_api.routers import auth, conversations, health, preferences, system, tasks, voice
from titan_api.security import (
    CSRFMiddleware,
    NetworkAllowlistMiddleware,
    SecurityHeadersMiddleware,
)

log = logging.getLogger("titan.api")
mimetypes.add_type("application/manifest+json", ".webmanifest")

_STATUS_CODES = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    422: "validation_error",
    429: "too_many_requests",
}


@asynccontextmanager
async def _lifespan(app: FastAPI):
    _recover_interrupted(app.state.ctx)
    yield
    app.state.ctx.engine.dispose()


def _recover_interrupted(ctx: AppContext) -> None:
    """Tarefas em execução quando o servidor parou viram INTERRUPTED (retomada manual)."""
    try:
        with ctx.session_factory.begin() as db:
            n = recover_on_startup(db)
        if n:
            log.warning("%d tarefa(s) marcadas como INTERRUPTED após reinício.", n)
    except Exception:
        log.exception("Recuperação de tarefas não executada (banco sem migrações?)")


def create_app(settings: Optional[Settings] = None) -> FastAPI:
    settings = settings or get_settings()
    prepare_runtime(settings)

    engine = make_engine(settings.database_url)
    session_factory = make_session_factory(engine)
    ctx = AppContext(
        settings=settings,
        engine=engine,
        session_factory=session_factory,
        runner=TaskRunner(settings, session_factory, inline=settings.task_runner == "inline"),
        voice=VoiceService(settings),
        auth=AuthService(
            settings.auth_secret.get_secret_value() or "test-only-secret",
            settings.session_ttl_hours,
            LoginThrottle(settings.login_max_attempts, settings.login_lockout_seconds),
        ),
    )

    app = FastAPI(
        title="TITAN API",
        version=__version__,
        description="API local do TITAN. Todas as rotas /api/v1 exigem sessão, exceto login.",
        # Documentação interativa só em desenvolvimento.
        docs_url="/docs" if settings.env.value == "development" else None,
        redoc_url=None,
        openapi_url="/openapi.json" if settings.env.value != "production" else None,
        lifespan=_lifespan,
    )
    app.state.ctx = ctx

    # Ordem: o último adicionado executa primeiro (allowlist antes de tudo).
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(CSRFMiddleware)
    app.add_middleware(NetworkAllowlistMiddleware, settings=settings)

    _install_error_handlers(app)

    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(conversations.router)
    app.include_router(system.router)
    app.include_router(tasks.router)
    app.include_router(voice.router)
    app.include_router(preferences.router)

    if settings.serve_web:
        _mount_web(app, settings.web_dist_dir)

    return app


def _install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(StarletteHTTPException)
    async def http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = _STATUS_CODES.get(exc.status_code, "error")
        return JSONResponse(
            {"error": {"code": code, "message": str(exc.detail)}},
            status_code=exc.status_code,
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        details = [
            {"loc": list(e.get("loc", [])), "msg": e.get("msg"), "type": e.get("type")}
            for e in exc.errors()
        ]
        return JSONResponse(
            {"error": {"code": "validation_error", "message": "Entrada inválida.",
                       "details": details}},
            status_code=422,
        )

    @app.exception_handler(Exception)
    async def unhandled(_: Request, exc: Exception) -> JSONResponse:
        log.exception("Erro interno não tratado")
        return JSONResponse(
            {"error": {"code": "internal_error", "message": "Erro interno. Consulte os logs."}},
            status_code=500,
        )


def _mount_web(app: FastAPI, dist: Path) -> None:
    dist = dist.resolve()
    index = dist / "index.html"
    if not index.is_file():
        log.warning("Interface web não compilada em %s (execute npm run build).", dist)

        @app.get("/", include_in_schema=False)
        def no_ui() -> JSONResponse:
            return JSONResponse(
                {"error": {"code": "ui_not_built",
                           "message": "Interface não compilada. Execute: npm run build"}},
                status_code=503,
            )
        return

    if (dist / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path.startswith(("api/", "health", "ready")):
            raise HTTPException(404, "Rota não encontrada.")
        candidate = (dist / path).resolve()
        if path and candidate.is_file() and candidate.is_relative_to(dist):
            return FileResponse(candidate)
        return FileResponse(index)
