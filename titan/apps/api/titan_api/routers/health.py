from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from titan import __version__
from titan.db.engine import ping
from titan.db.migrate import current_revision, head_revision
from titan_api.deps import AppContext, get_ctx
from titan_api.schemas import CheckOut, HealthOut, ReadyOut

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthOut)
def health() -> HealthOut:
    """Processo ativo. Não consulta dependências."""
    return HealthOut(status="ok", service="titan", version=__version__)


@router.get("/ready", response_model=ReadyOut, responses={503: {"model": ReadyOut}})
def ready(ctx: AppContext = Depends(get_ctx)):
    """Pronto para atender: banco acessível e migrações aplicadas."""
    checks: list[CheckOut] = []
    try:
        ping(ctx.engine)
        checks.append(CheckOut(name="database", ok=True, detail="conectado"))
        current, head = current_revision(ctx.engine), head_revision()
        checks.append(
            CheckOut(
                name="migrations",
                ok=current == head,
                detail=f"atual={current} esperado={head}",
            )
        )
    except Exception as exc:  # o detalhe é registrado sem expor credenciais
        checks.append(CheckOut(name="database", ok=False, detail=type(exc).__name__))
    ok = all(c.ok for c in checks)
    body = ReadyOut(status="ready" if ok else "not_ready", checks=checks)
    return JSONResponse(body.model_dump(), status_code=200 if ok else 503)
