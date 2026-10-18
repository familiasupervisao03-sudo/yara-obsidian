from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DBSession

from titan.audit import log as audit
from titan.memory import conversations as repo
from titan.models.providers import ChatTurn, ModelUnavailable, get_provider
from titan.policies.model_gate import ProviderBlocked
from titan_api.deps import AppContext, CurrentUser, current_user, get_ctx, get_db
from titan_api.schemas import (
    ConversationCreate,
    ConversationDetail,
    ConversationList,
    ConversationOut,
    ErrorResponse,
    MessageCreate,
    MessageOut,
    MessagePostOut,
    ModelStatus,
)

log = logging.getLogger("titan.chat")

router = APIRouter(
    prefix="/api/v1/conversations",
    tags=["conversations"],
    responses={401: {"model": ErrorResponse}},
)

NOT_FOUND = {404: {"model": ErrorResponse}}


def _get_owned(db: DBSession, cu: CurrentUser, conversation_id: uuid.UUID):
    conv = repo.get_conversation(db, cu.user.id, conversation_id)
    if conv is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversa não encontrada.")
    return conv


@router.post("", response_model=ConversationOut, status_code=201)
def create_conversation(
    body: ConversationCreate,
    cu: CurrentUser = Depends(current_user),
    db: DBSession = Depends(get_db),
) -> ConversationOut:
    conv = repo.create_conversation(db, cu.user.id, body.title)
    audit.record(db, "conversation.created", actor_type="user", actor_id=cu.user.id,
                 entity_type="conversation", entity_id=str(conv.id))
    return ConversationOut.model_validate(conv)


@router.get("", response_model=ConversationList)
def list_conversations(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    cu: CurrentUser = Depends(current_user),
    db: DBSession = Depends(get_db),
) -> ConversationList:
    items, total = repo.list_conversations(db, cu.user.id, limit, offset)
    return ConversationList(items=[ConversationOut.model_validate(c) for c in items], total=total)


@router.get("/{conversation_id}", response_model=ConversationDetail, responses=NOT_FOUND)
def get_conversation(
    conversation_id: uuid.UUID,
    cu: CurrentUser = Depends(current_user),
    db: DBSession = Depends(get_db),
) -> ConversationDetail:
    conv = _get_owned(db, cu, conversation_id)
    return ConversationDetail(
        **ConversationOut.model_validate(conv).model_dump(),
        messages=[MessageOut.model_validate(m) for m in repo.history(db, conv.id, limit=500)],
    )


@router.post(
    "/{conversation_id}/messages",
    response_model=MessagePostOut,
    status_code=201,
    responses=NOT_FOUND,
)
def post_message(
    conversation_id: uuid.UUID,
    body: MessageCreate,
    cu: CurrentUser = Depends(current_user),
    db: DBSession = Depends(get_db),
    ctx: AppContext = Depends(get_ctx),
) -> MessagePostOut:
    conv = _get_owned(db, cu, conversation_id)

    if body.client_request_id:
        existing = repo.find_message_by_request_id(db, conv.id, body.client_request_id)
        if existing is not None:
            return _duplicate_response(db, conv.id, existing, ctx)

    try:
        user_msg = repo.add_message(
            db, conv, "user", body.content, client_request_id=body.client_request_id
        )
    except IntegrityError:
        # Corrida entre dois envios com a mesma chave: devolve o já gravado.
        db.rollback()
        existing = repo.find_message_by_request_id(db, conv.id, body.client_request_id or "")
        if existing is None:
            raise
        return _duplicate_response(db, conv.id, existing, ctx)

    audit.record(db, "message.created", actor_type="user", actor_id=cu.user.id,
                 entity_type="message", entity_id=str(user_msg.id),
                 data={"conversation_id": str(conv.id), "length": len(body.content)})

    # Grava a mensagem do usuário ANTES de chamar o modelo: ela persiste mesmo se a
    # chamada falhar, e o banco não fica bloqueado durante uma chamada externa lenta.
    db.commit()

    reply_out = None
    try:
        provider = get_provider(ctx.settings, ctx.session_factory)
        turns = [ChatTurn(m.role, m.content) for m in repo.history(db, conv.id)]
        if not provider.info.local:
            audit.record(db, "model.external_request", actor_type="system",
                         entity_type="conversation", entity_id=str(conv.id),
                         data={"provider": provider.info.name, "paid": provider.info.paid,
                               "messages_sent": len(turns)})
            db.commit()
        reply = provider.chat(turns)
        reply_msg = repo.add_message(
            db, conv, "assistant", reply.content,
            model_provider=reply.provider, model_name=reply.model,
        )
        audit.record(db, "model.reply", actor_type="model", entity_type="message",
                     entity_id=str(reply_msg.id),
                     data={"provider": reply.provider, "model": reply.model})
        reply_out = MessageOut.model_validate(reply_msg)
        model = ModelStatus(available=True, provider=reply.provider, detail=reply.model)
    except (ModelUnavailable, ProviderBlocked) as exc:
        # Sem modelo: a mensagem fica salva e o usuário é informado. Nada é inventado.
        model = ModelStatus(available=False, provider=ctx.settings.model_provider, detail=str(exc))

    return MessagePostOut(
        user_message=MessageOut.model_validate(user_msg), reply=reply_out, model=model
    )


def _duplicate_response(db, conversation_id, existing, ctx: AppContext) -> MessagePostOut:
    msgs = repo.history(db, conversation_id, limit=500)
    idx = next((i for i, m in enumerate(msgs) if m.id == existing.id), None)
    nxt = msgs[idx + 1] if idx is not None and idx + 1 < len(msgs) else None
    reply = nxt if nxt is not None and nxt.role == "assistant" else None
    return MessagePostOut(
        user_message=MessageOut.model_validate(existing),
        reply=MessageOut.model_validate(reply) if reply else None,
        model=ModelStatus(available=reply is not None, provider=ctx.settings.model_provider,
                          detail="reenvio idempotente; nenhuma nova mensagem criada"),
        duplicate=True,
    )
