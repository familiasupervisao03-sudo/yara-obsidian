"""Repositório de conversas e mensagens (sempre filtrado pelo dono)."""

from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session as DBSession

from titan.db.models import Conversation, Message, utcnow


def create_conversation(db: DBSession, user_id: uuid.UUID, title: str) -> Conversation:
    conv = Conversation(user_id=user_id, title=title)
    db.add(conv)
    db.flush()
    return conv


def list_conversations(
    db: DBSession, user_id: uuid.UUID, limit: int = 50, offset: int = 0
) -> tuple[list[Conversation], int]:
    base = select(Conversation).where(
        Conversation.user_id == user_id, Conversation.archived.is_(False)
    )
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = db.scalars(
        base.order_by(Conversation.updated_at.desc()).limit(limit).offset(offset)
    ).all()
    return list(rows), total


def get_conversation(
    db: DBSession, user_id: uuid.UUID, conversation_id: uuid.UUID
) -> Optional[Conversation]:
    # Conversas de outros usuários são tratadas como inexistentes.
    return db.scalar(
        select(Conversation).where(
            Conversation.id == conversation_id, Conversation.user_id == user_id
        )
    )


def find_message_by_request_id(
    db: DBSession, conversation_id: uuid.UUID, client_request_id: str
) -> Optional[Message]:
    return db.scalar(
        select(Message).where(
            Message.conversation_id == conversation_id,
            Message.client_request_id == client_request_id,
        )
    )


def add_message(
    db: DBSession,
    conv: Conversation,
    role: str,
    content: str,
    *,
    client_request_id: Optional[str] = None,
    model_provider: Optional[str] = None,
    model_name: Optional[str] = None,
) -> Message:
    msg = Message(
        conversation_id=conv.id,
        role=role,
        content=content,
        client_request_id=client_request_id,
        model_provider=model_provider,
        model_name=model_name,
    )
    conv.updated_at = utcnow()
    db.add(msg)
    db.flush()
    return msg


def history(db: DBSession, conversation_id: uuid.UUID, limit: int = 40) -> list[Message]:
    rows = db.scalars(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.desc())
        .limit(limit)
    ).all()
    return list(reversed(rows))
