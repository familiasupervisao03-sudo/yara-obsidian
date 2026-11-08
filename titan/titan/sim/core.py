"""Estruturas comuns das rodadas de simulação."""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Optional


@dataclass
class Check:
    name: str
    ok: bool
    detail: str = ""


@dataclass
class Failure:
    """Uma falha encontrada no TITAN, com o necessário para reproduzir."""

    what: str
    repro: dict[str, Any]


@dataclass
class RoundResult:
    kind: str
    seed: int
    checks: list[Check] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    failures: list[Failure] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    skipped: Optional[str] = None  # motivo, se a rodada não pôde rodar (ex.: voz não instalada)
    seconds: float = 0.0

    @property
    def ok(self) -> bool:
        return self.skipped is None and all(c.ok for c in self.checks) and not self.failures

    def check(self, name: str, ok: bool, detail: str = "") -> bool:
        self.checks.append(Check(name, bool(ok), detail))
        return bool(ok)

    def fail(self, what: str, **repro: Any) -> None:
        self.failures.append(Failure(what, repro))

    def to_dict(self) -> dict:
        d = asdict(self)
        d["ok"] = self.ok
        return d


class Context:
    """O que um cenário recebe: semente, duração, pasta de trabalho, servidor isolado e
    um jeito de saber se o usuário pediu para parar (o cenário só usa isso para
    encurtar esperas longas; a rodada sempre termina inteira)."""

    def __init__(self, seed: int, seconds: float, workdir, server_factory: Callable,
                 stop_requested: Callable[[], bool], quick: bool = False) -> None:
        self.seed = seed
        self.seconds = seconds
        self.workdir = workdir
        self._server_factory = server_factory
        self.stop_requested = stop_requested
        self.quick = quick

    def server(self):
        return self._server_factory()


def timed(fn: Callable[[], Any]) -> tuple[Any, float]:
    t0 = time.perf_counter()
    out = fn()
    return out, (time.perf_counter() - t0) * 1000


def percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    v = sorted(values)
    return v[min(len(v) - 1, int(round(q * (len(v) - 1))))]
