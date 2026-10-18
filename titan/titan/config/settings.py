"""Configuração centralizada e validada do TITAN.

Toda regra financeira e de privacidade é aplicada aqui, no backend: uma
configuração conflitante impede a inicialização (falha segura) em vez de ser
corrigida silenciosamente.
"""

from __future__ import annotations

import ipaddress
from enum import Enum
from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Valor usado em .env.example; nunca aceito fora de testes.
EXAMPLE_AUTH_SECRET = "troque-este-valor-por-um-segredo-local-de-64-caracteres"

LOCAL_MODEL_PROVIDERS = {"none", "mock", "ollama", "llamacpp"}
TEST_ONLY_MODEL_PROVIDERS = {"mock"}
# Provedores externos e pagos: só com autorização explícita completa (ver _enforce_policies).
EXTERNAL_PAID_PROVIDERS = {"anthropic"}
MAX_DAILY_BUDGET_BRL = 1000.0  # trava contra erro de digitação


class Environment(str, Enum):
    development = "development"
    production = "production"
    test = "test"


class DeploymentMode(str, Enum):
    local = "local"


class ConfigurationError(ValueError):
    """Configuração insegura ou conflitante."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="TITAN_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    env: Environment = Environment.development
    deployment_mode: DeploymentMode = DeploymentMode.local
    local_only: bool = True

    host: str = "127.0.0.1"
    port: int = Field(default=8000, ge=1, le=65535)
    # Redes cujos clientes podem falar com a API. Padrão: apenas o próprio notebook.
    allowed_networks: str = "127.0.0.1/32,::1/128"

    database_url: str = Field(
        default="sqlite:///./var/titan.db",
        validation_alias="DATABASE_URL",
    )
    data_dir: Path = Path("./var")
    workspace_root: Path = Path("./var/workspaces")

    auth_secret: SecretStr = SecretStr("")
    session_ttl_hours: int = Field(default=12, ge=1, le=24 * 30)
    # Marca o cookie como Secure; só funciona com HTTPS (ver docs/security.md).
    cookie_secure: bool = False
    login_max_attempts: int = Field(default=5, ge=1, le=100)
    login_lockout_seconds: int = Field(default=300, ge=10)

    backup_dir: Path = Path("./backups")
    backup_keep: int = Field(default=7, ge=1, le=365)
    approval_ttl_hours: int = Field(default=24, ge=1, le=24 * 30)
    # "inline" executa tarefas na própria requisição (somente testes).
    task_runner: str = "thread"

    sandbox_enabled: bool = False
    sandbox_network: bool = False
    max_runtime_seconds: int = Field(default=30, ge=1, le=3600)
    max_repair_attempts: int = Field(default=3, ge=0, le=10)

    model_provider: str = "none"
    model_name: str = ""
    allow_external_models: bool = False
    allow_paid_apis: bool = False
    daily_paid_budget_brl: float = 0.0
    # Cotação usada para converter o custo em dólar; definida pelo usuário (sem valor padrão).
    usd_brl_rate: float = 0.0
    model_max_output_tokens: int = Field(default=2048, ge=64, le=32000)
    model_effort: str = "low"
    model_timeout_seconds: int = Field(default=90, ge=5, le=600)
    model_connect_timeout_seconds: int = Field(default=10, ge=2, le=60)
    # IPv6 doméstico quebrado faz o Python esperar ~1 min antes de tentar IPv4.
    network_force_ipv4: bool = True
    anthropic_fallbacks: bool = True
    anthropic_api_key: SecretStr = Field(
        default=SecretStr(""), validation_alias="ANTHROPIC_API_KEY"
    )

    log_level: str = "INFO"
    log_max_bytes: int = Field(default=1_000_000, ge=10_000)
    log_backup_count: int = Field(default=3, ge=0, le=20)

    serve_web: bool = True
    web_dist_dir: Path = Path("./apps/web/dist")

    @field_validator("log_level")
    @classmethod
    def _log_level(cls, v: str) -> str:
        v = v.upper()
        if v not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError("TITAN_LOG_LEVEL inválido")
        return v

    @field_validator("model_provider")
    @classmethod
    def _provider(cls, v: str) -> str:
        return v.strip().lower()

    @field_validator("allowed_networks")
    @classmethod
    def _networks(cls, v: str) -> str:
        for item in v.split(","):
            item = item.strip()
            if item:
                ipaddress.ip_network(item, strict=False)
        return v

    @model_validator(mode="after")
    def _enforce_policies(self) -> "Settings":
        errors: list[str] = []

        # Orçamento: APIs pagas exigem autorização explícita E orçamento diário > 0.
        budget = self.daily_paid_budget_brl
        if budget < 0 or budget > MAX_DAILY_BUDGET_BRL:
            errors.append(
                f"TITAN_DAILY_PAID_BUDGET_BRL deve estar entre 0 e {MAX_DAILY_BUDGET_BRL:.0f}."
            )
        if self.allow_paid_apis and budget <= 0:
            errors.append(
                "TITAN_ALLOW_PAID_APIS=true exige TITAN_DAILY_PAID_BUDGET_BRL maior que 0."
            )
        if not self.allow_paid_apis and budget != 0:
            errors.append(
                "TITAN_DAILY_PAID_BUDGET_BRL deve ser 0 enquanto TITAN_ALLOW_PAID_APIS=false."
            )

        # Privacidade: modo local não aceita provedores externos.
        if self.local_only and self.allow_external_models:
            errors.append(
                "Conflito: TITAN_LOCAL_ONLY=true e TITAN_ALLOW_EXTERNAL_MODELS=true."
            )
        if self.model_provider in EXTERNAL_PAID_PROVIDERS:
            missing = []
            if self.local_only:
                missing.append("TITAN_LOCAL_ONLY=false")
            if not self.allow_external_models:
                missing.append("TITAN_ALLOW_EXTERNAL_MODELS=true")
            if not self.allow_paid_apis:
                missing.append("TITAN_ALLOW_PAID_APIS=true")
            if budget <= 0:
                missing.append("TITAN_DAILY_PAID_BUDGET_BRL > 0")
            if self.usd_brl_rate <= 0:
                missing.append("TITAN_USD_BRL_RATE > 0")
            if not self.anthropic_api_key.get_secret_value().strip():
                missing.append("ANTHROPIC_API_KEY")
            if not self.model_name.strip():
                missing.append("TITAN_MODEL_NAME")
            if missing:
                errors.append(
                    f"O provedor '{self.model_provider}' envia dados a terceiros e é pago; "
                    "faltam autorizações/configurações: " + ", ".join(missing) + "."
                )
        elif self.model_provider not in LOCAL_MODEL_PROVIDERS:
            errors.append(
                f"Provedor de modelo '{self.model_provider}' desconhecido ou não suportado."
            )
        if self.task_runner not in {"thread", "inline"}:
            errors.append("TITAN_TASK_RUNNER deve ser 'thread' ou 'inline'.")
        elif self.task_runner == "inline" and self.env != Environment.test:
            errors.append("TITAN_TASK_RUNNER=inline só é permitido em TITAN_ENV=test.")
        if self.model_effort not in {"low", "medium", "high", "xhigh", "max"}:
            errors.append("TITAN_MODEL_EFFORT deve ser low, medium, high, xhigh ou max.")
        if (
            self.model_provider in TEST_ONLY_MODEL_PROVIDERS
            and self.env != Environment.test
        ):
            errors.append("O provedor 'mock' só pode ser usado em TITAN_ENV=test.")

        # Sandbox: rede dentro do sandbox exige decisão futura explícita.
        if self.sandbox_network:
            errors.append("TITAN_SANDBOX_NETWORK=true não é permitido nesta versão.")

        secret = self.auth_secret.get_secret_value()
        if self.env != Environment.test:
            if len(secret) < 32:
                errors.append(
                    "TITAN_AUTH_SECRET ausente ou curto (mínimo 32 caracteres). "
                    "Gere com: python -m titan.cli gen-secret"
                )
            elif secret == EXAMPLE_AUTH_SECRET:
                errors.append("TITAN_AUTH_SECRET ainda é o valor de exemplo.")

        # Rede local: escutar fora do loopback exige restringir as redes permitidas.
        if not _is_loopback_host(self.host):
            nets = [n.strip() for n in self.allowed_networks.split(",") if n.strip()]
            for n in nets:
                net = ipaddress.ip_network(n, strict=False)
                if net.prefixlen == 0:
                    errors.append(
                        f"TITAN_ALLOWED_NETWORKS contém '{n}' (qualquer endereço); "
                        "restrinja à sua rede local, ex.: 192.168.0.0/24."
                    )
                elif net.is_global:
                    errors.append(
                        f"TITAN_ALLOWED_NETWORKS contém a rede pública '{n}'; "
                        "o TITAN não deve ser exposto à internet."
                    )

        if errors:
            raise ConfigurationError("Configuração recusada:\n- " + "\n- ".join(errors))
        return self

    # --- utilidades ---------------------------------------------------------

    @property
    def networks(self) -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
        return [
            ipaddress.ip_network(n.strip(), strict=False)
            for n in self.allowed_networks.split(",")
            if n.strip()
        ]

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    def public_view(self) -> dict:
        """Configuração segura para exibir na interface (sem segredos)."""
        return {
            "env": self.env.value,
            "deployment_mode": self.deployment_mode.value,
            "local_only": self.local_only,
            "host": self.host,
            "port": self.port,
            "database_backend": "sqlite" if self.is_sqlite else "postgresql",
            "sandbox_enabled": self.sandbox_enabled,
            "sandbox_network": self.sandbox_network,
            "max_runtime_seconds": self.max_runtime_seconds,
            "max_repair_attempts": self.max_repair_attempts,
            "model_provider": self.model_provider,
            "model_name": self.model_name,
            "allow_external_models": self.allow_external_models,
            "allow_paid_apis": self.allow_paid_apis,
            "daily_paid_budget_brl": self.daily_paid_budget_brl,
            "usd_brl_rate": self.usd_brl_rate,
            "model_max_output_tokens": self.model_max_output_tokens,
            "model_effort": self.model_effort,
            "external_provider_active": self.model_provider in EXTERNAL_PAID_PROVIDERS,
            "anthropic_api_key_configured": bool(self.anthropic_api_key.get_secret_value()),
            "log_level": self.log_level,
        }


def _is_loopback_host(host: str) -> bool:
    if host in {"localhost"}:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


@lru_cache
def get_settings() -> Settings:
    return Settings()
