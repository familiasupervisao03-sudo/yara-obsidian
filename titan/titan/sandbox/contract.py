"""Contrato do executor isolado (Fase 3). EXECUÇÃO DESATIVADA nesta versão.

O executor real só será habilitado depois que um mecanismo de isolamento for
escolhido para o notebook e passar nos testes de fuga (ver docs/sandbox.md).
Até lá, ``get_sandbox`` sempre devolve ``DisabledSandbox``, que recusa e
explica o motivo. Nunca há fallback para execução direta no sistema.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from titan.config.settings import Settings


@dataclass(frozen=True)
class Limits:
    timeout_seconds: int = 30
    memory_mb: int = 256
    cpu_seconds: int = 30
    max_processes: int = 32
    max_file_mb: int = 16
    max_output_kb: int = 256
    network: bool = False  # rede desligada por padrão; ligar exige decisão futura


@dataclass(frozen=True)
class SandboxRequest:
    language: str
    files: dict[str, str]  # caminho relativo dentro do workspace -> conteúdo
    command: list[str]
    limits: Limits = field(default_factory=Limits)


@dataclass
class SandboxResult:
    exit_code: int | None
    stdout: str
    stderr: str
    timed_out: bool
    killed_by_limit: str | None
    artifacts: dict[str, int]  # arquivo -> tamanho em bytes
    profile: dict


class SandboxUnavailable(Exception):
    pass


class Sandbox(Protocol):
    name: str

    def run(self, request: SandboxRequest) -> SandboxResult: ...


class DisabledSandbox:
    name = "disabled"

    def __init__(self, reason: str) -> None:
        self.reason = reason

    def run(self, request: SandboxRequest) -> SandboxResult:
        raise SandboxUnavailable(self.reason)


def get_sandbox(settings: Settings) -> Sandbox:
    if settings.sandbox_enabled:
        return DisabledSandbox(
            "TITAN_SANDBOX_ENABLED=true, mas nenhum executor foi validado neste notebook "
            "(testes de fuga pendentes). A execução continua bloqueada.")
    return DisabledSandbox("Execução de código desativada até existir sandbox validado (Fase 3).")
