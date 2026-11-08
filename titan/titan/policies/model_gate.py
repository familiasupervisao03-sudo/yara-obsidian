"""Política de uso de modelos: aplicada no backend antes de qualquer chamada."""

from __future__ import annotations

from dataclasses import dataclass

from titan.config.settings import Settings


@dataclass(frozen=True)
class ProviderInfo:
    name: str
    local: bool
    paid: bool


class ProviderBlocked(Exception):
    """Chamada recusada por política (externa e/ou paga)."""


def assert_provider_allowed(info: ProviderInfo, settings: Settings) -> None:
    if info.paid and (not settings.allow_paid_apis or settings.daily_paid_budget_brl <= 0):
        raise ProviderBlocked(
            f"Provedor '{info.name}' é pago e APIs pagas estão bloqueadas "
            "(orçamento diário R$ 0)."
        )
    if not info.local and (settings.local_only or not settings.allow_external_models):
        raise ProviderBlocked(
            f"Provedor '{info.name}' é externo e o modo local proíbe envio de dados "
            "a terceiros sem autorização explícita."
        )
