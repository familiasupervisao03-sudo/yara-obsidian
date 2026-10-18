"""Modelos ORM. Compatíveis com SQLite e PostgreSQL."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    TypeDecorator,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

TASK_STATES = (
    "RECEIVED",
    "PLANNING",
    "PENDING_APPROVAL",
    "READY",
    "RUNNING",
    "VERIFYING",
    "WAITING_FOR_USER",
    "CANCEL_REQUESTED",
    "CANCELLED",
    "INTERRUPTED",
    "COMPLETED",
    "FAILED",
)
APPROVAL_STATES = ("PENDING", "APPROVED", "REJECTED", "INVALIDATED", "EXPIRED")
MESSAGE_ROLES = ("user", "assistant", "system")
USER_ROLES = ("owner", "member")
ACTOR_TYPES = ("user", "system", "model")

# Inteiro autoincremental portátil (BIGINT no PostgreSQL, INTEGER no SQLite).
BigIntPK = BigInteger().with_variant(Integer(), "sqlite")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UTCDateTime(TypeDecorator):
    """Data/hora sempre em UTC e com fuso, inclusive no SQLite (que não guarda fuso)."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: Optional[datetime], dialect: Any) -> Any:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("datetime sem fuso horário")
        value = value.astimezone(timezone.utc)
        return value.replace(tzinfo=None) if dialect.name == "sqlite" else value

    def process_result_value(self, value: Optional[datetime], dialect: Any) -> Any:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class Base(DeclarativeBase):
    type_annotation_map = {dict[str, Any]: JSON, list[Any]: JSON}


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utcnow, nullable=False
    )


class User(TimestampMixin, Base):
    __tablename__ = "users"
    __table_args__ = (CheckConstraint(_in("role", USER_ROLES), name="ck_users_role"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False, default="owner")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utcnow, onupdate=utcnow, nullable=False
    )


class Session(TimestampMixin, Base):
    __tablename__ = "sessions"
    __table_args__ = (Index("ix_sessions_user_expires", "user_id", "expires_at"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # Apenas o HMAC do token é armazenado; o token em si nunca vai ao banco.
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime(), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utcnow, nullable=False
    )
    revoked_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime())
    client_ip: Mapped[Optional[str]] = mapped_column(String(64))
    user_agent: Mapped[Optional[str]] = mapped_column(String(256))

    user: Mapped[User] = relationship()


class Conversation(TimestampMixin, Base):
    __tablename__ = "conversations"
    __table_args__ = (Index("ix_conversations_user_updated", "user_id", "updated_at"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utcnow, nullable=False
    )

    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation",
        order_by="Message.created_at",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class Message(TimestampMixin, Base):
    __tablename__ = "messages"
    __table_args__ = (
        CheckConstraint(_in("role", MESSAGE_ROLES), name="ck_messages_role"),
        UniqueConstraint(
            "conversation_id", "client_request_id", name="uq_messages_client_request"
        ),
        Index("ix_messages_conversation_created", "conversation_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    model_provider: Mapped[Optional[str]] = mapped_column(String(32))
    model_name: Mapped[Optional[str]] = mapped_column(String(128))
    # Chave de idempotência enviada pelo cliente para evitar duplicatas.
    client_request_id: Mapped[Optional[str]] = mapped_column(String(64))
    # complete | interrupted (usuário interrompeu) | error
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="complete")
    # Até onde a resposta foi efetivamente mostrada/falada antes da interrupção.
    interrupted_at_char: Mapped[Optional[int]] = mapped_column(Integer)

    conversation: Mapped[Conversation] = relationship(back_populates="messages")


class Task(TimestampMixin, Base):
    __tablename__ = "tasks"
    __table_args__ = (
        CheckConstraint(_in("status", TASK_STATES), name="ck_tasks_status"),
        UniqueConstraint("user_id", "idempotency_key", name="uq_tasks_idempotency"),
        Index("ix_tasks_user_status", "user_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    conversation_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("conversations.id", ondelete="SET NULL")
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    request: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="RECEIVED")
    plan_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    idempotency_key: Mapped[Optional[str]] = mapped_column(String(64))
    error: Mapped[Optional[str]] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utcnow, nullable=False
    )


class TaskStep(Base):
    __tablename__ = "task_steps"
    __table_args__ = (
        UniqueConstraint("task_id", "plan_version", "position", name="uq_task_steps_pos"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    task_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False
    )
    plan_version: Mapped[int] = mapped_column(Integer, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    action_type: Mapped[str] = mapped_column(String(64), nullable=False)
    parameters: Mapped[dict[str, Any]] = mapped_column(nullable=False, default=dict)
    requires_approval: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    depends_on: Mapped[list[Any]] = mapped_column(nullable=False, default=list)
    success_criteria: Mapped[list[Any]] = mapped_column(nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="PENDING")


class Approval(TimestampMixin, Base):
    __tablename__ = "approvals"
    __table_args__ = (
        CheckConstraint(_in("status", APPROVAL_STATES), name="ck_approvals_status"),
        Index("ix_approvals_task_status", "task_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    task_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False
    )
    step_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("task_steps.id", ondelete="SET NULL")
    )
    plan_version: Mapped[int] = mapped_column(Integer, nullable=False)
    action_type: Mapped[str] = mapped_column(String(64), nullable=False)
    parameters: Mapped[dict[str, Any]] = mapped_column(nullable=False, default=dict)
    # SHA-256 de (ação, parâmetros canônicos, versão do plano).
    scope_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="PENDING")
    decided_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    decided_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime())
    reason: Mapped[Optional[str]] = mapped_column(Text)
    # Consequências/riscos mostrados ao usuário no momento da decisão.
    risk: Mapped[str] = mapped_column(Text, nullable=False, default="")
    expires_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime())


class TaskPlan(TimestampMixin, Base):
    """Uma versão do plano de uma tarefa. Versões antigas nunca são alteradas."""

    __tablename__ = "task_plans"
    __table_args__ = (UniqueConstraint("task_id", "version", name="uq_task_plans_version"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    task_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    created_by: Mapped[str] = mapped_column(String(16), nullable=False)  # user | model
    change_note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    plan_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class Execution(Base):
    __tablename__ = "executions"
    __table_args__ = (Index("ix_executions_task", "task_id", "started_at"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    task_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False
    )
    step_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("task_steps.id", ondelete="SET NULL")
    )
    approval_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("approvals.id", ondelete="SET NULL")
    )
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    command: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    exit_code: Mapped[Optional[int]] = mapped_column(Integer)
    stdout_tail: Mapped[str] = mapped_column(Text, nullable=False, default="")
    stderr_tail: Mapped[str] = mapped_column(Text, nullable=False, default="")
    sandbox_profile: Mapped[dict[str, Any]] = mapped_column(nullable=False, default=dict)
    started_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utcnow, nullable=False
    )
    finished_at: Mapped[Optional[datetime]] = mapped_column(UTCDateTime())


class ExecutionArtifact(TimestampMixin, Base):
    __tablename__ = "execution_artifacts"
    __table_args__ = (UniqueConstraint("execution_id", "path", name="uq_artifact_path"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    execution_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("executions.id", ondelete="CASCADE"), nullable=False
    )
    path: Mapped[str] = mapped_column(String(512), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)


class VerificationResult(TimestampMixin, Base):
    __tablename__ = "verification_results"
    __table_args__ = (Index("ix_verification_task", "task_id"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    task_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False
    )
    execution_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("executions.id", ondelete="SET NULL")
    )
    criterion: Mapped[str] = mapped_column(Text, nullable=False)
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    details: Mapped[str] = mapped_column(Text, nullable=False, default="")


class AuditEvent(TimestampMixin, Base):
    """Evento de auditoria encadeado por hash (detecção de adulteração)."""

    __tablename__ = "audit_events"
    __table_args__ = (
        CheckConstraint(_in("actor_type", ACTOR_TYPES), name="ck_audit_actor_type"),
        Index("ix_audit_task", "task_id", "id"),
        Index("ix_audit_type", "event_type"),
    )

    # Inteiro sequencial: a ordem estrita é necessária para a cadeia de hashes.
    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    actor_type: Mapped[str] = mapped_column(String(16), nullable=False)
    actor_id: Mapped[Optional[uuid.UUID]] = mapped_column(Uuid)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    task_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("tasks.id", ondelete="SET NULL")
    )
    entity_type: Mapped[Optional[str]] = mapped_column(String(32))
    entity_id: Mapped[Optional[str]] = mapped_column(String(64))
    data: Mapped[dict[str, Any]] = mapped_column(nullable=False, default=dict)
    prev_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)


class MemoryItem(TimestampMixin, Base):
    __tablename__ = "memory_items"
    __table_args__ = (Index("ix_memory_user_kind", "user_id", "kind"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[Optional[str]] = mapped_column(String(128))
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utcnow, nullable=False
    )


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict[str, Any]] = mapped_column(nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utcnow, nullable=False
    )
    updated_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )


USAGE_STATES = ("RESERVED", "FINAL", "FAILED")


class ModelUsage(TimestampMixin, Base):
    """Gasto com provedores pagos. A reserva é gravada ANTES da chamada."""

    __tablename__ = "model_usage"
    __table_args__ = (
        CheckConstraint(_in("status", USAGE_STATES), name="ck_model_usage_status"),
        Index("ix_model_usage_day", "day"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    # Data local do servidor (AAAA-MM-DD): o orçamento é diário no fuso do notebook.
    day: Mapped[str] = mapped_column(String(10), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_brl: Mapped[float] = mapped_column(Float, nullable=False)
    request_id: Mapped[Optional[str]] = mapped_column(String(128))
    detail: Mapped[Optional[str]] = mapped_column(Text)
