from __future__ import annotations

import asyncio
import json
import logging
import threading
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DBSession

from titan.audit import log as audit
from titan.brain import service as brain
from titan.casa import chat as casa_chat
from titan.db.models import Message
from titan.memory import conversations as repo
from titan.memory import preferences as user_prefs
from titan.memory.reply_stream import run_reply_stream
from titan.memory.style import build_style
from titan.models.providers import ChatTurn, ModelUnavailable, error_reason, get_provider
from titan.policies.model_gate import ProviderBlocked
from titan.tools.web import research as web
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
    rem = _reminder_answer(ctx, cu, conv.id, body.content)
    if rem is not None:  # lembrete na hora, sem IA
        rem.pop("_action", None)
        db.expire_all()
        return MessagePostOut(user_message=MessageOut.model_validate(user_msg), reply=MessageOut(**rem),
                              model=ModelStatus(available=True, provider="titan", detail="lembrete"))
    try:
        provider = get_provider(ctx.settings, ctx.session_factory)
        turns = turns_for_model(repo.history(db, conv.id))
        if not provider.info.local:
            audit.record(db, "model.external_request", actor_type="system",
                         entity_type="conversation", entity_id=str(conv.id),
                         data={"provider": provider.info.name, "paid": provider.info.paid,
                               "messages_sent": len(turns)})
            db.commit()
        style = build_style(body.mode, user_prefs.get(db, cu.user.id))
        turns, style, footer = with_research(ctx, cu, body, turns, style, lambda *_: None)
        style = brain.with_memory(style, brain.context_for(ctx.session_factory, cu.user.id, body.content))
        style = brain.with_memory(style, casa_chat.context_block(ctx.settings, ctx.session_factory, cu.user.id))
        reply = provider.chat(turns, style=style)
        reply_msg = repo.add_message(
            db, conv, "assistant", reply.content.strip() + footer,
            model_provider=reply.provider, model_name=reply.model,
        )
        audit.record(db, "model.reply", actor_type="model", entity_type="message",
                     entity_id=str(reply_msg.id),
                     data={"provider": reply.provider, "model": reply.model})
        reply_out = MessageOut.model_validate(reply_msg)
        model = ModelStatus(available=True, provider=reply.provider, detail=reply.model)
        db.commit()
        brain.after_turn(ctx.settings, ctx.session_factory, cu.user.id, conv.id, user_msg.id,
                         body.content, reply.content)
    except (ModelUnavailable, ProviderBlocked) as exc:
        # Sem modelo: a mensagem fica salva e o usuário é informado. Nada é inventado.
        model = ModelStatus(available=False, provider=ctx.settings.model_provider, detail=str(exc),
                            reason=error_reason(exc))

    return MessagePostOut(
        user_message=MessageOut.model_validate(user_msg), reply=reply_out, model=model
    )


def turns_for_model(messages) -> list[ChatTurn]:
    """Histórico para o modelo. Respostas interrompidas aparecem só até onde foram
    mostradas/faladas, com a marca de interrupção, para a IA saber onde parou."""
    turns = []
    for m in messages:
        content = m.content
        if m.role == "assistant" and m.status == "interrupted":
            cut = m.interrupted_at_char if m.interrupted_at_char is not None else len(content)
            content = content[:cut].rstrip() + " [resposta interrompida pelo usuário aqui]"
        elif m.role == "assistant" and m.status == "error":
            continue
        turns.append(ChatTurn(m.role, content))
    if turns and turns[0].role == "assistant":
        # Conversa que o TITAN começou (bom dia, papo…): a API exige começar pelo usuário, e
        # sem isto a mensagem do TITAN seria descartada e a resposta ficaria sem contexto.
        turns.insert(0, ChatTurn("user", "[O TITAN puxou este assunto por conta própria; a mensagem dele vem a seguir.]"))
    return turns


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


@router.post("/{conversation_id}/messages/stream", responses=NOT_FOUND,
             response_class=StreamingResponse)
async def post_message_stream(
    conversation_id: uuid.UUID,
    body: MessageCreate,
    cu: CurrentUser = Depends(current_user),
    ctx: AppContext = Depends(get_ctx),
):
    """Envia a mensagem e recebe a resposta em pedaços (SSE).

    Eventos: user_message, delta, done | interrupted | error. Fechar a conexão
    cancela a geração; o trecho já gerado é salvo como 'interrupted'.
    """
    prep = await run_in_threadpool(_prepare_stream, ctx, cu, conversation_id, body)
    if isinstance(prep, JSONResponse):
        return prep
    user_out, provider, turns, duplicate_reply, model_error, is_duplicate = prep
    style = await run_in_threadpool(_style_for, ctx, cu, body.mode)

    async def stream():
        yield _sse("user_message", {"message": user_out, "duplicate": is_duplicate})
        if duplicate_reply is not None:
            yield _sse("done", {"message": duplicate_reply, "duplicate": True})
            return
        # "liga o ventilador": o TITAN Casa resolve na hora, sem IA (funciona até sem modelo).
        casa_out = await run_in_threadpool(_casa_answer, ctx, cu, conversation_id, body.content)
        if casa_out is not None:
            yield _sse("delta", {"text": casa_out["content"]})
            yield _sse("done", {"message": casa_out, "footer_chars": 0, "metrics": {"casa": True}})
            return
        # "me lembra às 14h de ...": lembrete na hora, sem IA
        rem_out = await run_in_threadpool(_reminder_answer, ctx, cu, conversation_id, body.content)
        if rem_out is not None:
            action = rem_out.pop("_action")
            yield _sse("delta", {"text": rem_out["content"]})
            yield _sse("done", {"message": rem_out, "footer_chars": 0, "metrics": {"lembrete": True}})
            # avisa o app: no celular, o lembrete é agendado no próprio aparelho na mesma hora
            yield _sse("actions", {"message_id": user_out["id"], "actions": [action]})
            return
        if provider is None:
            detail, reason = model_error or ("reenvio sem resposta registrada", "unavailable")
            yield _sse("error", {"detail": detail, "model_available": False, "reason": reason})
            return
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue()
        cancel = threading.Event()
        finished = False

        def emit(kind: str, data: dict) -> None:
            try:
                loop.call_soon_threadsafe(queue.put_nowait, (kind, data))
            except RuntimeError:  # loop encerrado (cliente desconectou)
                cancel.set()

        def worker() -> None:
            try:
                t, st, footer = with_research(ctx, cu, body, turns, style, emit)
                if cancel.is_set():
                    return
                st = brain.with_memory(st, brain.context_for(ctx.session_factory, cu.user.id, body.content))
                st = brain.with_memory(st, casa_chat.context_block(ctx.settings, ctx.session_factory, cu.user.id))
                replied: dict = {}

                def emit_and_keep(kind: str, data: dict) -> None:
                    if kind == "done" and data.get("message"):
                        replied["text"] = data["message"]["content"]
                    emit(kind, data)

                run_reply_stream(ctx.session_factory, conversation_id, provider, t, emit_and_keep,
                                 cancel, st, footer)
                if replied and not cancel.is_set() and not is_duplicate:
                    # Depois da resposta (o usuário já está lendo): lembretes, tarefas, lembranças.
                    actions = brain.after_turn(ctx.settings, ctx.session_factory, cu.user.id,
                                               conversation_id, uuid.UUID(user_out["id"]),
                                               body.content, replied["text"])
                    if actions:
                        emit("actions", {"message_id": user_out["id"], "actions": actions})
            finally:
                emit("_end", {})

        threading.Thread(target=worker, daemon=True, name="titan-reply-stream").start()
        try:
            while True:
                kind, data = await queue.get()
                if kind == "_end":
                    finished = True
                    return
                yield _sse(kind, data)
        finally:
            if not finished:
                cancel.set()  # cliente fechou a conexão: interrompe a geração

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


def _casa_answer(ctx: AppContext, cu: CurrentUser, conversation_id: uuid.UUID, text: str):
    reply = casa_chat.try_handle(ctx.settings, ctx.session_factory, cu.user.id, text)
    if not reply:
        return None
    with ctx.session_factory.begin() as db:
        conv = repo.get_conversation(db, cu.user.id, conversation_id)
        msg = repo.add_message(db, conv, "assistant", reply, model_provider="titan", model_name="casa")
        db.flush()
        return MessageOut.model_validate(msg).model_dump(mode="json")


def _reminder_answer(ctx: AppContext, cu: CurrentUser, conversation_id: uuid.UUID, text: str):
    """"Me lembra às 14h30 de..." vira lembrete NA HORA (sem IA, funciona com a IA em pausa)."""
    from titan.brain import quick
    from titan.brain import store as brain_store

    parsed = quick.parse_reminder(text, brain_store.local_now())
    if parsed is None:
        return None
    title, due = parsed
    with ctx.session_factory.begin() as db:
        conv = repo.get_conversation(db, cu.user.id, conversation_id)
        reply = f"Lembrete criado: {title}, {quick.when_text(due, brain_store.local_now())}. Te aviso na hora."
        msg = repo.add_message(db, conv, "assistant", reply, model_provider="titan", model_name="lembrete")
        db.flush()
        todo = brain_store.add_todo(db, cu.user.id, title, "lembrete", due_at=due, conversation_id=conv.id,
                                    message_id=msg.id)
        audit.record(db, "brain.todo.created", actor_type="user", actor_id=cu.user.id, entity_type="message",
                     entity_id=str(msg.id), data={"kind": "lembrete", "quick": True})
        out = MessageOut.model_validate(msg).model_dump(mode="json")
        out["_action"] = {"type": "lembrete", "id": str(todo.id), "title": todo.title,
                          "due_at": todo.due_at.isoformat()}
        return out


def with_research(ctx: AppContext, cu: CurrentUser, body: MessageCreate, turns: list[ChatTurn],
                  style: str, emit) -> tuple[list[ChatTurn], str, str]:
    """Pesquisa na internet, se pedida: devolve (turnos, estilo, rodapé com as fontes).

    As fontes entram na ÚLTIMA mensagem do usuário (dados não confiáveis), nunca no
    prompt do sistema; o estilo recebe só instruções fixas do TITAN.
    """
    wanted = body.web is True or (body.web is None and web.wants_web(body.content))
    if not wanted or not turns or turns[-1].role != "user":
        return turns, style, ""
    sep = "\n\n" if style else ""
    if not ctx.settings.web_enabled or ctx.web is None:
        emit("research", {"status": "disabled"})
        return turns, style + sep + (
            "O usuário pediu uma pesquisa na internet, mas ela está desligada nas configurações "
            "do TITAN (ligar com: titan enable-web). Diga isso e não finja ter pesquisado."), ""
    emit("research", {"status": "searching", "query": web.make_query(body.content)})
    try:
        res = ctx.web.research(body.content, str(cu.user.id))
    except web.RateLimited as exc:
        emit("research", {"status": "limited", "detail": str(exc)})
        return turns, style + sep + (
            f"O usuário pediu uma pesquisa na internet, mas ela foi recusada: {exc} "
            "Diga isso e não finja ter pesquisado."), ""
    except Exception:
        log.exception("Falha inesperada na pesquisa na internet")
        emit("research", {"status": "failed"})
        return turns, style + sep + (
            "O usuário pediu uma pesquisa na internet, mas ela falhou por um erro interno. "
            "Diga isso e não finja ter pesquisado."), ""
    emit("research", {"status": "done", **res.public()})
    with ctx.session_factory.begin() as db:
        # Sem a pergunta nem o conteúdo das páginas: só o necessário para auditoria.
        audit.record(db, "web.search", actor_type="user", actor_id=cu.user.id,
                     entity_type="conversation", data={
                         "provider": res.provider, "query_chars": len(res.query),
                         "sources": len(res.sources), "sites": sorted({s.site for s in res.sources}),
                         "cached": res.cached, "elapsed_ms": res.elapsed_ms})
    last = turns[-1]
    turns = turns[:-1] + [ChatTurn("user", last.content + web.sources_block(res))]
    return turns, style + sep + web.style_for(res, body.mode == "voice"), web.sources_footer(res)


def _style_for(ctx: AppContext, cu: CurrentUser, mode: str) -> str:
    with ctx.session_factory() as db:
        return build_style(mode, user_prefs.get(db, cu.user.id))


def _prepare_stream(ctx: AppContext, cu: CurrentUser, conversation_id: uuid.UUID,
                    body: MessageCreate):
    with ctx.session_factory() as db:
        conv = repo.get_conversation(db, cu.user.id, conversation_id)
        if conv is None:
            return JSONResponse({"error": {"code": "not_found",
                                           "message": "Conversa não encontrada."}},
                                status_code=404)
        if body.client_request_id:
            existing = repo.find_message_by_request_id(db, conv.id, body.client_request_id)
            if existing is not None:
                dup = _duplicate_response(db, conv.id, existing, ctx)
                return (dup.user_message.model_dump(mode="json"), None, [],
                        dup.reply.model_dump(mode="json") if dup.reply else None, None, True)
        try:
            user_msg = repo.add_message(db, conv, "user", body.content,
                                        client_request_id=body.client_request_id)
            audit.record(db, "message.created", actor_type="user", actor_id=cu.user.id,
                         entity_type="message", entity_id=str(user_msg.id),
                         data={"conversation_id": str(conv.id), "length": len(body.content),
                               "streamed": True})
            db.commit()
        except IntegrityError:
            db.rollback()
            existing = repo.find_message_by_request_id(db, conv.id, body.client_request_id or "")
            if existing is None:
                raise
            dup = _duplicate_response(db, conv.id, existing, ctx)
            return (dup.user_message.model_dump(mode="json"), None, [],
                    dup.reply.model_dump(mode="json") if dup.reply else None, None, True)
        user_out = MessageOut.model_validate(user_msg).model_dump(mode="json")
        try:
            provider = get_provider(ctx.settings, ctx.session_factory)
        except (ModelUnavailable, ProviderBlocked) as exc:
            return user_out, None, [], None, (str(exc), error_reason(exc)), False
        turns = turns_for_model(repo.history(db, conv.id))
        if not provider.info.local:
            audit.record(db, "model.external_request", actor_type="system",
                         entity_type="conversation", entity_id=str(conv.id),
                         data={"provider": provider.info.name, "paid": provider.info.paid,
                               "messages_sent": len(turns), "streamed": True})
            db.commit()
        return user_out, provider, turns, None, None, False


class InterruptionIn(BaseModel):
    spoken_chars: int = Field(ge=0, le=1_000_000)


@router.post("/{conversation_id}/messages/{message_id}/interruption",
             response_model=MessageOut, responses=NOT_FOUND)
def record_interruption(conversation_id: uuid.UUID, message_id: uuid.UUID,
                        body: InterruptionIn, cu: CurrentUser = Depends(current_user),
                        db: DBSession = Depends(get_db)) -> MessageOut:
    """Registra até onde a resposta foi falada/mostrada quando o usuário interrompeu."""
    conv = _get_owned(db, cu, conversation_id)
    msg = db.get(Message, message_id)
    if msg is None or msg.conversation_id != conv.id or msg.role != "assistant":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Mensagem não encontrada.")
    msg.status = "interrupted"
    msg.interrupted_at_char = min(body.spoken_chars, len(msg.content))
    audit.record(db, "message.interrupted", actor_type="user", actor_id=cu.user.id,
                 entity_type="message", entity_id=str(msg.id),
                 data={"spoken_chars": msg.interrupted_at_char, "total_chars": len(msg.content)})
    return MessageOut.model_validate(msg)


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
