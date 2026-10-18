from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session as DBSession

from titan.audit import log as audit
from titan.auth.service import AuthError, LoginLocked
from titan_api.deps import (
    SESSION_COOKIE,
    AppContext,
    CurrentUser,
    current_user,
    get_ctx,
    get_db,
)
from titan_api.schemas import ErrorResponse, LoginIn, SessionOut, UserOut

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post(
    "/login",
    response_model=SessionOut,
    responses={401: {"model": ErrorResponse}, 429: {"model": ErrorResponse}},
)
def login(
    body: LoginIn,
    request: Request,
    response: Response,
    ctx: AppContext = Depends(get_ctx),
    db: DBSession = Depends(get_db),
) -> SessionOut:
    ip = request.client.host if request.client else None
    try:
        issued = ctx.auth.login(
            db, body.username, body.password, ip, request.headers.get("user-agent")
        )
    except LoginLocked as exc:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            str(exc),
            headers={"Retry-After": str(exc.retry_after)},
        )
    except AuthError as exc:
        # Registrado em transação própria: a falha não deve ser perdida no rollback.
        with ctx.session_factory.begin() as adb:
            audit.record(
                adb, "auth.login_failed", data={"username": body.username, "ip": ip}
            )
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(exc))
    audit.record(
        db,
        "auth.login",
        actor_type="user",
        actor_id=issued.user.id,
        entity_type="session",
        entity_id=str(issued.session.id),
        data={"ip": ip},
    )
    response.set_cookie(
        SESSION_COOKIE,
        issued.token,
        max_age=int(ctx.auth.ttl.total_seconds()),
        httponly=True,
        samesite="strict",
        secure=ctx.settings.cookie_secure,
        path="/",
    )
    return SessionOut(user=UserOut.model_validate(issued.user), expires_at=issued.session.expires_at)


@router.post("/logout", status_code=204, responses={401: {"model": ErrorResponse}})
def logout(
    response: Response,
    cu: CurrentUser = Depends(current_user),
    ctx: AppContext = Depends(get_ctx),
    db: DBSession = Depends(get_db),
) -> Response:
    sess = db.merge(cu.session)
    ctx.auth.revoke(db, sess)
    audit.record(db, "auth.logout", actor_type="user", actor_id=cu.user.id,
                 entity_type="session", entity_id=str(sess.id))
    response.status_code = 204
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response


@router.get("/me", response_model=SessionOut, responses={401: {"model": ErrorResponse}})
def me(cu: CurrentUser = Depends(current_user)) -> SessionOut:
    return SessionOut(user=UserOut.model_validate(cu.user), expires_at=cu.session.expires_at)
