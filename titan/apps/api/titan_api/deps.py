"""Dependências FastAPI: banco, sessão autenticada e contexto da aplicação."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session as DBSession, sessionmaker
from sqlalchemy import Engine

from titan.auth.service import AuthService
from titan.tasks.runner import TaskRunner
from titan.voice.engines import VoiceService
from titan.config.settings import Settings
from titan.db.models import Session, User

SESSION_COOKIE = "titan_session"


@dataclass
class AppContext:
    settings: Settings
    engine: Engine
    session_factory: sessionmaker[DBSession]
    auth: AuthService
    runner: "TaskRunner"
    voice: "VoiceService"


def get_ctx(request: Request) -> AppContext:
    return request.app.state.ctx


def get_db(ctx: AppContext = Depends(get_ctx)) -> Iterator[DBSession]:
    db = ctx.session_factory()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@dataclass
class CurrentUser:
    user: User
    session: Session


def current_user(
    request: Request,
    db: DBSession = Depends(get_db),
    ctx: AppContext = Depends(get_ctx),
) -> CurrentUser:
    token = request.cookies.get(SESSION_COOKIE)
    resolved = ctx.auth.resolve(db, token)
    if resolved is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Autenticação necessária.")
    session, user = resolved
    return CurrentUser(user=user, session=session)
