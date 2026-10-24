"""Contratos de entrada e saída da API (Pydantic)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class ErrorBody(BaseModel):
    code: str
    message: str
    details: Optional[Any] = None


class ErrorResponse(BaseModel):
    error: ErrorBody


class HealthOut(BaseModel):
    status: Literal["ok"]
    service: str
    version: str


class CheckOut(BaseModel):
    name: str
    ok: bool
    detail: str


class ReadyOut(BaseModel):
    status: Literal["ready", "not_ready"]
    checks: list[CheckOut]


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    username: str
    role: str


class SessionOut(BaseModel):
    user: UserOut
    expires_at: datetime


class ConversationCreate(BaseModel):
    title: str = Field(default="Nova conversa", min_length=1, max_length=200)


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    role: str
    content: str
    model_provider: Optional[str]
    model_name: Optional[str]
    status: str = "complete"
    interrupted_at_char: Optional[int] = None
    created_at: datetime


class ConversationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    title: str
    created_at: datetime
    updated_at: datetime


class ConversationDetail(ConversationOut):
    messages: list[MessageOut]


class ConversationList(BaseModel):
    items: list[ConversationOut]
    total: int


class MessageCreate(BaseModel):
    content: str = Field(min_length=1, max_length=20_000)
    # Chave de idempotência opcional: reenvios com a mesma chave não duplicam.
    client_request_id: Optional[str] = Field(
        default=None, min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_\-]+$"
    )
    # "voice": a resposta será falada (curta, sem markdown, números por extenso).
    mode: Literal["text", "voice"] = "text"


class ModelStatus(BaseModel):
    available: bool
    provider: str
    detail: str


class MessagePostOut(BaseModel):
    user_message: MessageOut
    reply: Optional[MessageOut]
    model: ModelStatus
    duplicate: bool = False


class SettingsOut(BaseModel):
    config: dict[str, Any]
    policies: dict[str, Any]


class ServiceStatus(BaseModel):
    name: str
    state: Literal["online", "offline", "disabled", "unavailable", "planned"]
    detail: str


class SystemStatusOut(BaseModel):
    version: str
    phase: str
    services: list[ServiceStatus]
    paid_apis_blocked: bool
    external_models_blocked: bool
    external_provider_active: bool
    paid_budget_brl: float
    paid_spent_today_brl: float
    audit_chain_ok: bool
