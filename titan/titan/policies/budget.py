"""Orçamento diário de APIs pagas, aplicado no backend antes de cada chamada.

Fluxo: ``reserve`` grava o custo MÁXIMO possível da chamada (em transação
própria, sob lock) e recusa se ultrapassar o orçamento do dia; depois da
chamada, ``finalize`` troca a reserva pelo custo real informado pelo provedor.
Se a chamada falhar de forma incerta, a reserva fica como gasto (conservador).
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass
from datetime import date
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session as DBSession, sessionmaker

from titan.config.settings import Settings
from titan.db.models import ModelUsage

# Preço em US$ por milhão de tokens (entrada, saída) — tabela oficial da Anthropic
# (cache de 2026-10-06). Modelo desconhecido usa o preço mais alto (conservador).
ANTHROPIC_PRICES_USD_PER_MTOK: dict[str, tuple[float, float]] = {
    "claude-fable-5-1": (10.0, 50.0),
    "claude-fable-5": (10.0, 50.0),
    "claude-opus-5-5": (4.0, 20.0),
    "claude-opus-5": (5.0, 25.0),
    "claude-opus-4-8": (5.0, 25.0),
    "claude-opus-4-7": (5.0, 25.0),
    "claude-opus-4-6": (5.0, 25.0),
    "claude-sonnet-5-5": (2.0, 10.0),
    "claude-sonnet-5": (2.0, 10.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    # Haiku 5.5: preço até 100K tokens de entrada; acima disso US$ 0,50/2,50.
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-haiku-4-5": (1.0, 5.0),
}
WORST_CASE_PRICE = max(ANTHROPIC_PRICES_USD_PER_MTOK.values(), key=lambda p: p[1])


def price_for(model: str) -> tuple[float, float]:
    price = ANTHROPIC_PRICES_USD_PER_MTOK.get(model, WORST_CASE_PRICE)
    if model == "claude-haiku-5-5":
        return (0.50, 2.50)  # conservador: assume a faixa acima de 100K
    return price


def cost_brl(settings: Settings, model: str, input_tokens: int, output_tokens: int) -> float:
    pin, pout = price_for(model)
    usd = (input_tokens * pin + output_tokens * pout) / 1_000_000
    return round(usd * settings.usd_brl_rate, 6)


class BudgetExceeded(Exception):
    pass


@dataclass
class Reservation:
    id: uuid.UUID
    estimated_brl: float


_lock = threading.Lock()


def today() -> str:
    return date.today().isoformat()  # fuso local do notebook


class BudgetGuard:
    def __init__(self, settings: Settings, session_factory: sessionmaker[DBSession]) -> None:
        self.settings = settings
        self.session_factory = session_factory

    def spent_today(self, db: Optional[DBSession] = None) -> float:
        def q(s: DBSession) -> float:
            return float(
                s.scalar(
                    select(func.coalesce(func.sum(ModelUsage.cost_brl), 0.0)).where(
                        ModelUsage.day == today()
                    )
                )
                or 0.0
            )

        if db is not None:
            return q(db)
        with self.session_factory() as s:
            return q(s)

    def reserve(self, provider: str, model: str, max_input_tokens: int,
                max_output_tokens: int) -> Reservation:
        s = self.settings
        if not s.allow_paid_apis or s.daily_paid_budget_brl <= 0 or s.usd_brl_rate <= 0:
            raise BudgetExceeded("APIs pagas não autorizadas (orçamento diário R$ 0).")
        # Pior caso: o modelo mais caro da tabela (cobre o fallback automático).
        pin, pout = WORST_CASE_PRICE
        worst = (max_input_tokens * pin + max_output_tokens * pout) / 1_000_000 * s.usd_brl_rate
        worst = round(worst, 6)
        with _lock, self.session_factory.begin() as db:
            spent = self.spent_today(db)
            if spent + worst > s.daily_paid_budget_brl:
                raise BudgetExceeded(
                    f"Orçamento diário atingido: gasto hoje R$ {spent:.4f}, esta chamada "
                    f"pode custar até R$ {worst:.4f}, limite R$ {s.daily_paid_budget_brl:.2f}. "
                    "A chamada NÃO foi enviada."
                )
            row = ModelUsage(day=today(), provider=provider, model=model, status="RESERVED",
                             cost_brl=worst)
            db.add(row)
            db.flush()
            return Reservation(id=row.id, estimated_brl=worst)

    def finalize(self, res: Reservation, model: str, input_tokens: int, output_tokens: int,
                 request_id: Optional[str]) -> float:
        actual = cost_brl(self.settings, model, input_tokens, output_tokens)
        with _lock, self.session_factory.begin() as db:
            row = db.get(ModelUsage, res.id)
            row.status = "FINAL"
            row.model = model
            row.input_tokens = input_tokens
            row.output_tokens = output_tokens
            row.cost_brl = actual
            row.request_id = request_id
        return actual

    def fail(self, res: Reservation, detail: str, *, billed_unknown: bool) -> None:
        """Erro na chamada. Se não dá para saber se houve cobrança, mantém a reserva."""
        with _lock, self.session_factory.begin() as db:
            row = db.get(ModelUsage, res.id)
            row.status = "FAILED"
            row.detail = detail[:500]
            if not billed_unknown:
                row.cost_brl = 0.0
