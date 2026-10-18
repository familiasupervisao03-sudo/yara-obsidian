"""Interface de modelos de linguagem, independente de provedor.

Provedores: ``none`` (nenhum modelo), ``mock`` (somente testes) e
``anthropic`` (externo e pago; exige autorização explícita completa e
orçamento diário). Adaptadores locais (Ollama/llama.cpp) chegam na Fase 4.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from titan.config.settings import Environment, Settings
from titan.policies.model_gate import ProviderInfo, assert_provider_allowed


@dataclass(frozen=True)
class ChatTurn:
    role: str
    content: str


@dataclass(frozen=True)
class ModelReply:
    content: str
    provider: str
    model: str


class ModelUnavailable(Exception):
    """Nenhum modelo utilizável. Nunca é convertido em resposta fictícia."""


class ModelProvider(Protocol):
    info: ProviderInfo

    def chat(self, history: list[ChatTurn]) -> ModelReply: ...


class MockProvider:
    """Provedor determinístico para testes automatizados. Bloqueado fora de TITAN_ENV=test."""

    info = ProviderInfo(name="mock", local=True, paid=False)

    def __init__(self, model: str = "mock-echo") -> None:
        self.model = model or "mock-echo"

    def chat(self, history: list[ChatTurn]) -> ModelReply:
        last = history[-1].content if history else ""
        return ModelReply(content=f"[mock] {last}", provider="mock", model=self.model)


def get_provider(settings: Settings, session_factory=None) -> ModelProvider:
    """Seleciona o provedor configurado, aplicando as políticas antes de qualquer chamada.

    ``session_factory`` é necessário para provedores pagos (controle de orçamento).
    """
    name = settings.model_provider
    if name == "none":
        raise ModelUnavailable(
            "Nenhum modelo de linguagem configurado (TITAN_MODEL_PROVIDER=none)."
        )
    if name == "mock":
        if settings.env != Environment.test:
            raise ModelUnavailable("Provedor 'mock' só é permitido em testes.")
        provider: ModelProvider = MockProvider(settings.model_name)
    elif name == "anthropic":
        # Bloqueio de política ANTES de construir o cliente.
        from titan.models.anthropic_provider import AnthropicProvider
        from titan.policies.budget import BudgetGuard

        assert_provider_allowed(AnthropicProvider.info, settings)
        if session_factory is None:
            raise ModelUnavailable("Provedor pago exige o controle de orçamento (banco).")
        provider = AnthropicProvider(settings, BudgetGuard(settings, session_factory))
    elif name in {"ollama", "llamacpp"}:
        raise ModelUnavailable(
            f"Adaptador local '{name}' ainda não implementado (previsto para a Fase 4)."
        )
    else:
        raise ModelUnavailable(f"Provedor desconhecido: {name}")
    assert_provider_allowed(provider.info, settings)
    return provider
