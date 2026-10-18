"""Adaptador da API da Anthropic (Claude). EXTERNO e PAGO.

Só é construído quando a configuração contém todas as autorizações explícitas
(ver ``Settings._enforce_policies``). Antes de cada chamada o orçamento diário
reserva o custo máximo possível; sem orçamento, nada é enviado.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from titan.config.settings import Settings
from titan.models.providers import ChatTurn, ModelReply, ModelUnavailable
from titan.policies.budget import BudgetExceeded, BudgetGuard
from titan.policies.model_gate import ProviderBlocked, ProviderInfo

log = logging.getLogger("titan.models.anthropic")

SYSTEM_PROMPT = (
    "Você é o TITAN, assistente pessoal do usuário, rodando a partir do notebook dele. "
    "Responda em português do Brasil, de forma clara e direta. Seja honesto: se não "
    "souber algo ou não puder fazer algo, diga. Você não executa programas nem acessa "
    "arquivos do computador nesta versão; não afirme ter feito ações que não fez."
)

# Modelos que aceitam o fallback automático do servidor no modo "default".
FALLBACK_MODELS = {"claude-fable-5-1", "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5"}
FALLBACK_BETA = "server-side-fallback-2026-07-01"

# Estimativa conservadora: ~3 caracteres por token (português tende a ~4).
CHARS_PER_TOKEN = 3
MAX_HISTORY_MESSAGES = 40


def to_api_messages(history: list[ChatTurn]) -> list[dict[str, str]]:
    """Converte o histórico em turnos alternados user/assistant, começando por user."""
    msgs: list[dict[str, str]] = []
    for turn in history[-MAX_HISTORY_MESSAGES:]:
        if turn.role not in ("user", "assistant") or not turn.content.strip():
            continue
        if msgs and msgs[-1]["role"] == turn.role:
            msgs[-1]["content"] += "\n\n" + turn.content
        else:
            msgs.append({"role": turn.role, "content": turn.content})
    while msgs and msgs[0]["role"] != "user":
        msgs.pop(0)
    return msgs


def estimate_input_tokens(messages: list[dict[str, str]]) -> int:
    chars = len(SYSTEM_PROMPT) + sum(len(m["content"]) + 16 for m in messages)
    return chars // CHARS_PER_TOKEN + 64


class AnthropicProvider:
    info = ProviderInfo(name="anthropic", local=False, paid=True)

    def __init__(self, settings: Settings, budget: BudgetGuard, client: Any = None) -> None:
        self.settings = settings
        self.budget = budget
        self.model = settings.model_name
        self._client = client  # injetável nos testes (nenhuma chamada real)

    def _get_client(self) -> Any:
        if self._client is None:
            try:
                import anthropic
            except ImportError as exc:  # pragma: no cover - depende da instalação
                raise ModelUnavailable(
                    "Biblioteca 'anthropic' não instalada. Rode: "
                    ".venv/bin/pip install -e '.[anthropic]'"
                ) from exc
            self._client = anthropic.Anthropic(
                api_key=self.settings.anthropic_api_key.get_secret_value(),
                timeout=float(self.settings.model_timeout_seconds),
                max_retries=0,  # sem reenvios automáticos: cada envio é contabilizado
            )
        return self._client

    def chat(self, history: list[ChatTurn]) -> ModelReply:
        messages = to_api_messages(history)
        if not messages:
            raise ModelUnavailable("Nenhuma mensagem do usuário para enviar.")
        max_out = self.settings.model_max_output_tokens
        try:
            reservation = self.budget.reserve(
                "anthropic", self.model, estimate_input_tokens(messages), max_out
            )
        except BudgetExceeded as exc:
            raise ProviderBlocked(str(exc)) from exc

        client = self._get_client()
        params: dict[str, Any] = dict(
            model=self.model,
            max_tokens=max_out,
            system=SYSTEM_PROMPT,
            messages=messages,
            output_config={"effort": self.settings.model_effort},
        )
        try:
            if self.settings.anthropic_fallbacks and self.model in FALLBACK_MODELS:
                response = client.beta.messages.create(
                    **params, betas=[FALLBACK_BETA], fallbacks="default"
                )
            else:
                response = client.messages.create(**params)
        except Exception as exc:
            self._handle_error(exc, reservation)  # registra e levanta ModelUnavailable

        usage = response.usage
        served_by = getattr(response, "model", None) or self.model
        cost = self.budget.finalize(
            reservation, served_by,
            int(getattr(usage, "input_tokens", 0) or 0)
            + int(getattr(usage, "cache_creation_input_tokens", 0) or 0)
            + int(getattr(usage, "cache_read_input_tokens", 0) or 0),
            int(getattr(usage, "output_tokens", 0) or 0),
            getattr(response, "_request_id", None),
        )
        log.info("anthropic: modelo=%s custo=R$ %.4f stop=%s", served_by, cost,
                 response.stop_reason)

        if response.stop_reason == "refusal":
            details = getattr(response, "stop_details", None)
            category = getattr(details, "category", None) if details else None
            return ModelReply(
                content="[A Anthropic recusou esta solicitação"
                        + (f" — categoria: {category}" if category else "") + ".]",
                provider="anthropic", model=served_by,
            )
        text = "".join(b.text for b in response.content if getattr(b, "type", "") == "text").strip()
        if response.stop_reason == "max_tokens":
            text += "\n\n[Resposta interrompida pelo limite TITAN_MODEL_MAX_OUTPUT_TOKENS.]"
        if not text:
            raise ModelUnavailable(
                f"A API respondeu sem texto (stop_reason={response.stop_reason})."
            )
        return ModelReply(content=text, provider="anthropic", model=served_by)

    def _handle_error(self, exc: Exception, reservation) -> None:
        name = type(exc).__name__
        # Erros HTTP com status (4xx/5xx) chegam antes da geração: não há cobrança.
        status: Optional[int] = getattr(exc, "status_code", None)
        billed_unknown = status is None  # timeout/conexão: incerto, mantém a reserva
        self.budget.fail(reservation, f"{name} status={status}", billed_unknown=billed_unknown)
        messages = {
            401: "Chave da Anthropic inválida (ANTHROPIC_API_KEY).",
            403: "A chave da Anthropic não tem permissão para este modelo.",
            404: f"Modelo '{self.model}' não encontrado na Anthropic.",
            429: "Limite de uso da Anthropic atingido (ou créditos esgotados). Tente mais tarde.",
            400: "A Anthropic recusou a requisição (400). Verifique créditos e o modelo.",
        }
        if status in messages:
            detail = messages[status]
        elif status is not None and status >= 500:
            detail = f"Erro no servidor da Anthropic ({status}). Tente mais tarde."
        else:
            detail = f"Falha de conexão com a Anthropic ({name}). Verifique a internet."
        log.warning("anthropic: erro %s status=%s", name, status)
        raise ModelUnavailable(detail) from exc
