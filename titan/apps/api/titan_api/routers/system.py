from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session as DBSession

from titan import PHASE, __version__
from titan.audit.log import verify_chain
from titan.config.settings import EXTERNAL_PAID_PROVIDERS
from titan.policies.budget import BudgetGuard
from titan.db.engine import ping
from titan.models.providers import ModelUnavailable, get_provider
from titan.policies.model_gate import ProviderBlocked
from titan_api.deps import AppContext, CurrentUser, current_user, get_ctx, get_db
from titan_api.schemas import ErrorResponse, ServiceStatus, SettingsOut, SystemStatusOut

router = APIRouter(prefix="/api/v1", tags=["system"], responses={401: {"model": ErrorResponse}})


@router.get("/settings", response_model=SettingsOut)
def get_settings_view(
    _: CurrentUser = Depends(current_user), ctx: AppContext = Depends(get_ctx)
) -> SettingsOut:
    """Configuração efetiva (somente leitura, sem segredos)."""
    s = ctx.settings
    return SettingsOut(
        config=s.public_view(),
        policies={
            "paid_apis": "blocked" if not s.allow_paid_apis else "allowed",
            "external_provider_active": s.model_provider in EXTERNAL_PAID_PROVIDERS,
            "daily_paid_budget_brl": s.daily_paid_budget_brl,
            "external_models": "blocked" if not s.allow_external_models else "allowed",
            "sandbox_network": "disabled" if not s.sandbox_network else "enabled",
            "settings_writable_by_model": False,
            "public_exposure": "none (sem túneis nem encaminhamento de portas)",
        },
    )


@router.get("/system/status", response_model=SystemStatusOut)
def system_status(
    _: CurrentUser = Depends(current_user),
    ctx: AppContext = Depends(get_ctx),
    db: DBSession = Depends(get_db),
) -> SystemStatusOut:
    s = ctx.settings
    services: list[ServiceStatus] = []
    try:
        ping(ctx.engine)
        backend = "SQLite" if s.is_sqlite else "PostgreSQL"
        services.append(ServiceStatus(name="database", state="online", detail=backend))
    except Exception as exc:
        services.append(ServiceStatus(name="database", state="offline", detail=type(exc).__name__))

    try:
        p = get_provider(s, ctx.session_factory)
        detail = p.info.name
        if not p.info.local:
            detail = (f"{p.info.name} · {s.model_name} — EXTERNO"
                      + (" e PAGO" if p.info.paid else "")
                      + ": as conversas são enviadas a este provedor")
        services.append(ServiceStatus(name="model", state="online", detail=detail))
    except (ModelUnavailable, ProviderBlocked) as exc:
        services.append(ServiceStatus(name="model", state="unavailable", detail=str(exc)))

    services.append(
        ServiceStatus(
            name="sandbox",
            state="disabled",
            detail="Execução de código desativada: sandbox isolado ainda não implementado "
            "e validado (Fase 3)." if not s.sandbox_enabled else
            "TITAN_SANDBOX_ENABLED=true, mas o executor ainda não existe; execução bloqueada.",
        )
    )
    services.append(ServiceStatus(name="orchestrator", state="online",
                                  detail="Tarefas, planos versionados e aprovações (Fase 2)."))
    chain_ok, _bad = verify_chain(db)
    return SystemStatusOut(
        version=__version__,
        phase=PHASE,
        services=services,
        paid_apis_blocked=not s.allow_paid_apis,
        external_models_blocked=not s.allow_external_models,
        external_provider_active=s.model_provider in EXTERNAL_PAID_PROVIDERS,
        paid_budget_brl=s.daily_paid_budget_brl,
        paid_spent_today_brl=round(BudgetGuard(s, ctx.session_factory).spent_today(db), 4),
        audit_chain_ok=chain_ok,
    )
