"""Configuração centralizada e validada do TITAN.

Toda regra financeira e de privacidade é aplicada aqui, no backend: uma
configuração conflitante impede a inicialização (falha segura) em vez de ser
corrigida silenciosamente.
"""

from __future__ import annotations

import ipaddress
import re
from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import Optional

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
    # HTTPS local (ver docs/mobile.md). Com os dois arquivos, o servidor usa TLS.
    tls_cert_file: Optional[Path] = None
    tls_key_file: Optional[Path] = None
    # Escutar na rede local SEM HTTPS exige este aceite explícito do risco.
    lan_acknowledge_http_risk: bool = False
    login_max_attempts: int = Field(default=5, ge=1, le=100)
    login_lockout_seconds: int = Field(default=300, ge=10)

    # Voz local (opcional; ver docs/voice.md).
    voice_vosk_model_dir: Path = Path("./var/models/vosk-model-small-pt-0.3")
    voice_piper_model: Path = Path("./var/models/piper/pt_BR-faber-medium.onnx")
    voice_max_utterance_seconds: int = Field(default=60, ge=5, le=300)
    # Voz do TITAN: "piper" (local) ou "edge" (voz natural on-line da Microsoft:
    # o texto das respostas sai do notebook; exige TITAN_ALLOW_EXTERNAL_VOICE=true).
    voice_tts: str = "piper"
    voice_edge_voice: str = "pt-BR-AntonioNeural"
    allow_external_voice: bool = False
    # Reconhecimento da fala: "vosk" (local), "groq" (Whisper on-line da Groq) ou "xai"
    # (Grok, da xAI). Nos on-line o ÁUDIO da sua fala sai do notebook; exigem
    # TITAN_ALLOW_EXTERNAL_VOICE=true e a chave (GROQ_API_KEY ou XAI_API_KEY).
    voice_stt: str = "vosk"
    groq_api_key: SecretStr = Field(default=SecretStr(""), validation_alias="GROQ_API_KEY")
    voice_groq_model: str = "whisper-large-v3-turbo"
    xai_api_key: SecretStr = Field(default=SecretStr(""), validation_alias="XAI_API_KEY")
    voice_xai_model: str = "grok-voice-transcribe-2.0"
    # Teto de minutos de áudio enviados por dia ao reconhecimento on-line (protege o custo).
    voice_cloud_max_minutes_day: int = Field(default=60, ge=1, le=1440)
    # Com reconhecimento on-line ligado, rodar também o Vosk ao vivo (texto parcial na tela)?
    # Pesa no processador de notebooks fracos; desligado, o Vosk só entra se o on-line falhar.
    voice_local_partials: bool = False

    # Sócio (memória, lembretes, mensagens do TITAN). Modelo usado para "entender" as
    # conversas e escrever as mensagens; vazio = o mesmo das conversas. Recomendado: o
    # mais barato (ex.: claude-haiku-5-5), porque roda depois de cada mensagem.
    brain_model_name: str = ""
    # Mensagens do TITAN por conta própria (bom dia, lembretes...): o agendador roda no servidor.
    brain_scheduler: bool = True

    # TITAN Casa (automação). "demo" = aparelhos de demonstração (nada sai do notebook);
    # "tuya" = sua conta Tuya/Smart Life pela nuvem da Tuya (os comandos saem do notebook).
    casa_provider: str = "demo"
    tuya_access_id: str = ""
    tuya_access_secret: SecretStr = Field(default=SecretStr(""), validation_alias="TUYA_ACCESS_SECRET")
    # Centro de dados da conta: us (Américas, inclui Brasil), eu, cn, in, ueaz, weaz.
    tuya_region: str = "us"
    # Comandos por minuto por casa (proteção contra abuso e laços).
    casa_max_commands_per_minute: int = Field(default=40, ge=5, le=600)
    # Abaixar o som do notebook (música, vídeo...) enquanto você fala com o TITAN e enquanto
    # ele responde; volta ao volume de antes no final. Nível = % do volume original.
    audio_duck: bool = True
    audio_duck_level: int = Field(default=20, ge=1, le=90)

    # TITAN Central (tela da TV): clima da sua cidade (Open-Meteo, grátis e sem chave).
    # Configure com: titan central-clima "Sua cidade". Vazio = sem cartão de clima.
    central_city: str = ""
    central_lat: Optional[float] = Field(default=None, ge=-90, le=90)
    central_lon: Optional[float] = Field(default=None, ge=-180, le=180)

    # Pesquisa na internet (opcional; ver docs/pesquisa-internet.md). Desligada por padrão:
    # a pergunta pesquisada sai do notebook para a fonte de busca e para os sites lidos.
    web_enabled: bool = False
    # SearXNG local (ex.: http://127.0.0.1:8888). Vazio: usa a API pública da Wikipédia.
    web_searxng_url: str = ""
    web_timeout_seconds: int = Field(default=10, ge=2, le=60)
    web_max_page_bytes: int = Field(default=2_000_000, ge=50_000, le=10_000_000)
    web_max_results: int = Field(default=5, ge=1, le=10)
    web_max_pages: int = Field(default=3, ge=0, le=5)
    web_max_searches_per_minute: int = Field(default=6, ge=1, le=60)
    web_max_searches_per_day: int = Field(default=150, ge=1, le=5000)

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

        # Voz on-line: só com autorização explícita (o texto sai do notebook).
        if self.voice_tts not in {"piper", "edge"}:
            errors.append("TITAN_VOICE_TTS deve ser 'piper' (local) ou 'edge' (on-line).")
        if self.local_only and self.allow_external_voice:
            errors.append("Conflito: TITAN_LOCAL_ONLY=true e TITAN_ALLOW_EXTERNAL_VOICE=true.")
        if self.voice_tts == "edge":
            missing = []
            if self.local_only:
                missing.append("TITAN_LOCAL_ONLY=false")
            if not self.allow_external_voice:
                missing.append("TITAN_ALLOW_EXTERNAL_VOICE=true")
            if missing:
                errors.append("A voz on-line envia o texto das respostas à Microsoft; faltam "
                              "autorizações: " + ", ".join(missing) + ".")
        if self.casa_provider not in {"demo", "tuya"}:
            errors.append("TITAN_CASA_PROVIDER deve ser 'demo' ou 'tuya'.")
        if self.casa_provider == "tuya":
            if self.local_only:
                errors.append("TITAN_CASA_PROVIDER=tuya exige TITAN_LOCAL_ONLY=false (os comandos vão à nuvem da Tuya).")
            if not self.tuya_access_id.strip() or not self.tuya_access_secret.get_secret_value().strip():
                errors.append("TITAN_CASA_PROVIDER=tuya exige TITAN_TUYA_ACCESS_ID e TUYA_ACCESS_SECRET.")
        if self.tuya_region not in {"us", "eu", "cn", "in", "ueaz", "weaz"}:
            errors.append("TITAN_TUYA_REGION deve ser us, eu, cn, in, ueaz ou weaz.")
        if self.voice_stt not in {"vosk", "groq", "xai"}:
            errors.append("TITAN_VOICE_STT deve ser 'vosk' (local), 'groq' ou 'xai' (on-line).")
        if self.voice_stt in {"groq", "xai"}:
            company, key_name, key = (("Groq", "GROQ_API_KEY", self.groq_api_key) if self.voice_stt == "groq"
                                      else ("xAI", "XAI_API_KEY", self.xai_api_key))
            missing = []
            if self.local_only:
                missing.append("TITAN_LOCAL_ONLY=false")
            if not self.allow_external_voice:
                missing.append("TITAN_ALLOW_EXTERNAL_VOICE=true")
            if not key.get_secret_value().strip():
                missing.append(key_name)
            if missing:
                errors.append(f"O reconhecimento on-line envia o áudio da sua fala à {company}; faltam: "
                              + ", ".join(missing) + ".")
        for name, model in (("TITAN_VOICE_GROQ_MODEL", self.voice_groq_model),
                            ("TITAN_VOICE_XAI_MODEL", self.voice_xai_model)):
            if not re.fullmatch(r"[a-z0-9][a-z0-9.-]{2,60}", model):
                errors.append(f"{name} inválido.")
        if not re.fullmatch(r"[a-z]{2}-[A-Z]{2}-[A-Za-z]+Neural", self.voice_edge_voice):
            errors.append("TITAN_VOICE_EDGE_VOICE inválida (ex.: pt-BR-AntonioNeural).")

        # Internet: só com autorização explícita (a pergunta sai do notebook).
        if self.web_enabled and self.local_only:
            errors.append("TITAN_WEB_ENABLED=true exige TITAN_LOCAL_ONLY=false "
                          "(a pesquisa envia a pergunta à internet).")
        if self.web_searxng_url:
            from urllib.parse import urlsplit

            u = urlsplit(self.web_searxng_url)
            try:
                loopback = ipaddress.ip_address(u.hostname or "").is_loopback
            except ValueError:
                loopback = u.hostname == "localhost"
            if u.scheme not in ("http", "https") or not loopback or u.path not in ("", "/") \
                    or u.query or u.username:
                errors.append("TITAN_WEB_SEARXNG_URL deve ser o SearXNG no próprio notebook, "
                              "ex.: http://127.0.0.1:8888")

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

        if bool(self.tls_cert_file) != bool(self.tls_key_file):
            errors.append("Defina TITAN_TLS_CERT_FILE e TITAN_TLS_KEY_FILE juntos.")
        for f in (self.tls_cert_file, self.tls_key_file):
            if f is not None and not Path(f).expanduser().is_file():
                errors.append(f"Arquivo TLS não encontrado: {f}")

        # Rede local: escutar fora do loopback exige restringir as redes permitidas.
        if not _is_loopback_host(self.host):
            if not self.tls_enabled and not self.lan_acknowledge_http_risk:
                errors.append(
                    "Escutar na rede local sem HTTPS expõe senha, cookie e conversas a quem "
                    "estiver na mesma Wi-Fi. Configure HTTPS (docs/mobile.md) ou, ciente do "
                    "risco, defina TITAN_LAN_ACKNOWLEDGE_HTTP_RISK=true."
                )
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
    def tls_enabled(self) -> bool:
        return bool(self.tls_cert_file and self.tls_key_file)

    @property
    def secure_cookies(self) -> bool:
        return self.cookie_secure or self.tls_enabled

    @property
    def lan_enabled(self) -> bool:
        return not _is_loopback_host(self.host)

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
            "lan_enabled": self.lan_enabled,
            "tls_enabled": self.tls_enabled,
            "database_backend": "sqlite" if self.is_sqlite else "postgresql",
            "voice_tts": self.voice_tts,
            "voice_stt": self.voice_stt,
            "groq_api_key_configured": bool(self.groq_api_key.get_secret_value()),
            "xai_api_key_configured": bool(self.xai_api_key.get_secret_value()),
            "casa_provider": self.casa_provider,
            "tuya_region": self.tuya_region,
            "central_city": self.central_city,
            "voice_edge_voice": self.voice_edge_voice,
            "allow_external_voice": self.allow_external_voice,
            "web_enabled": self.web_enabled,
            "web_provider": ("searxng" if self.web_searxng_url else "wikipedia") if self.web_enabled else "none",
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
