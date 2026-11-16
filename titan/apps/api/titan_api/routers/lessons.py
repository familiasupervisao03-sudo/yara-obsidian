"""Vídeo-aulas animadas: a IA escreve o roteiro e a interface mostra e narra (ver titan/lessons)."""

from __future__ import annotations

import uuid
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DBSession

from titan.audit import log as audit
from titan.db.models import Message
from titan.lessons import script
from titan.memory import conversations as repo
from titan.memory import preferences as user_prefs
from titan.memory.style import build_style
from titan.models.providers import ModelUnavailable, generate_json, get_provider
from titan.policies.model_gate import ProviderBlocked
from titan_api.deps import AppContext, CurrentUser, current_user, get_ctx, get_db
from titan_api.routers.conversations import turns_for_model, with_research
from titan_api.schemas import ErrorResponse, MessageCreate, MessageOut, ModelStatus

router = APIRouter(prefix="/api/v1", tags=["lessons"], responses={401: {"model": ErrorResponse}})
NOT_FOUND = {404: {"model": ErrorResponse}}


class LessonCreate(BaseModel):
    content: str = Field(min_length=1, max_length=2000, description="o pedido, ex.: 'explica em vídeo a fotossíntese'")
    client_request_id: Optional[str] = Field(default=None, min_length=8, max_length=64,
                                             pattern=r"^[A-Za-z0-9_\-]+$")
    # Pesquisa na internet antes de montar a aula (só com TITAN_WEB_ENABLED=true).
    web: Optional[bool] = None
    level: Literal["crianca", "basico", "avancado"] = "basico"
    length: Literal["rapida", "normal", "completa"] = "normal"
    # Continuação de uma aula: pergunta/teoria sobre ela, ou "explicar mais simples" uma cena.
    continues: Optional[uuid.UUID] = None
    focus_scene: Optional[int] = Field(default=None, ge=0, le=100)
    simpler: bool = False


class LessonOut(BaseModel):
    message_id: uuid.UUID
    lesson: dict[str, Any]


class LessonPostOut(BaseModel):
    user_message: MessageOut
    reply: Optional[MessageOut]
    lesson: Optional[dict[str, Any]]
    model: ModelStatus
    duplicate: bool = False


def _reply_after(db: DBSession, conversation_id: uuid.UUID, user_msg: Message) -> Optional[Message]:
    msgs = repo.history(db, conversation_id, limit=500)
    idx = next((i for i, m in enumerate(msgs) if m.id == user_msg.id), None)
    nxt = msgs[idx + 1] if idx is not None and idx + 1 < len(msgs) else None
    return nxt if nxt is not None and nxt.role == "assistant" else None


@router.post("/conversations/{conversation_id}/lessons", response_model=LessonPostOut, status_code=201,
             responses=NOT_FOUND)
def create_lesson(conversation_id: uuid.UUID, body: LessonCreate, cu: CurrentUser = Depends(current_user),
                  db: DBSession = Depends(get_db), ctx: AppContext = Depends(get_ctx)) -> LessonPostOut:
    conv = repo.get_conversation(db, cu.user.id, conversation_id)
    if conv is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversa não encontrada.")

    def duplicate(existing: Message) -> LessonPostOut:
        reply = _reply_after(db, conv.id, existing)
        lesson = script.load(db, cu.user.id, reply.id) if reply else None
        return LessonPostOut(user_message=MessageOut.model_validate(existing),
                             reply=MessageOut.model_validate(reply) if reply else None, lesson=lesson,
                             model=ModelStatus(available=reply is not None, provider=ctx.settings.model_provider,
                                               detail="reenvio idempotente; nenhuma nova aula criada"),
                             duplicate=True)

    parent = None
    if body.continues is not None:
        parent = script.load(db, cu.user.id, body.continues)  # só aulas do próprio usuário
        if parent is None or db.get(Message, body.continues) is None \
                or db.get(Message, body.continues).conversation_id != conv.id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Aula a continuar não encontrada.")
    if body.client_request_id:
        existing = repo.find_message_by_request_id(db, conv.id, body.client_request_id)
        if existing is not None:
            return duplicate(existing)
    try:
        user_msg = repo.add_message(db, conv, "user", body.content, client_request_id=body.client_request_id)
    except IntegrityError:
        db.rollback()
        existing = repo.find_message_by_request_id(db, conv.id, body.client_request_id or "")
        if existing is None:
            raise
        return duplicate(existing)
    audit.record(db, "message.created", actor_type="user", actor_id=cu.user.id, entity_type="message",
                 entity_id=str(user_msg.id),
                 data={"conversation_id": str(conv.id), "length": len(body.content), "lesson": True})
    db.commit()  # o pedido fica salvo mesmo se a geração falhar

    try:
        provider = get_provider(ctx.settings, ctx.session_factory)
        turns = turns_for_model(repo.history(db, conv.id))
        style = build_style("text", user_prefs.get(db, cu.user.id))
        found: list[dict] = []
        turns, style, _footer = with_research(
            ctx, cu, MessageCreate(content=body.content[:2000], web=body.web), turns, style,
            lambda kind, data: found.extend(data.get("sources") or []) if data.get("status") == "done" else None)
        style = (style + "\n\n" if style else "") + script.build_style(
            body.level, body.length, parent, body.focus_scene, body.simpler)
        if not provider.info.local:
            audit.record(db, "model.external_request", actor_type="system", entity_type="conversation",
                         entity_id=str(conv.id), data={"provider": provider.info.name, "paid": provider.info.paid,
                                                       "messages_sent": len(turns), "lesson": True})
            db.commit()
        data, reply = generate_json(provider, turns, style, script.SCHEMA,
                                    script.max_tokens(body.length, parent is not None))
    except (ModelUnavailable, ProviderBlocked) as exc:
        return LessonPostOut(user_message=MessageOut.model_validate(user_msg), reply=None, lesson=None,
                             model=ModelStatus(available=False, provider=ctx.settings.model_provider, detail=str(exc)))

    lesson = script.sanitize(data, continuation=parent is not None)
    if not lesson["cenas"]:
        return LessonPostOut(user_message=MessageOut.model_validate(user_msg), reply=None, lesson=None,
                             model=ModelStatus(available=False, provider=reply.provider,
                                               detail="A IA não montou nenhuma cena válida. Tente pedir de outro jeito."))
    lesson["fontes"] = [{"n": f["n"], "title": f["title"], "url": f["url"], "site": f["site"]} for f in found]
    lesson.update(nivel=body.level, duracao=body.length, continua=str(body.continues) if parent else None,
                  pedido=body.content[:300])
    msg = repo.add_message(db, conv, "assistant", script.transcript(lesson),
                           model_provider=reply.provider, model_name=reply.model)
    db.flush()
    script.save(db, cu.user.id, msg.id, lesson)
    audit.record(db, "lesson.created", actor_type="model", entity_type="message", entity_id=str(msg.id),
                 data={"provider": reply.provider, "model": reply.model, "scenes": len(lesson["cenas"]),
                       "sources": len(lesson["fontes"]), "continuation": parent is not None,
                       "level": body.level, "length": body.length})
    return LessonPostOut(user_message=MessageOut.model_validate(user_msg), reply=MessageOut.model_validate(msg),
                         lesson=lesson, model=ModelStatus(available=True, provider=reply.provider, detail=reply.model))


@router.get("/lessons/{message_id}", response_model=LessonOut, responses=NOT_FOUND)
def get_lesson(message_id: uuid.UUID, cu: CurrentUser = Depends(current_user),
               db: DBSession = Depends(get_db)) -> LessonOut:
    lesson = script.load(db, cu.user.id, message_id)  # só as aulas do próprio usuário
    if lesson is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Aula não encontrada.")
    return LessonOut(message_id=message_id, lesson=lesson)
