"""Geração de resposta em streaming, com cancelamento e persistência consistente.

Roda numa thread própria; a cada pedaço verifica ``cancel``. Ao cancelar
(usuário interrompeu ou a conexão caiu), fecha o fluxo do provedor e salva o
trecho já recebido como mensagem ``interrupted``. Nada é inventado: sem texto,
nada é salvo como resposta.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import Any, Callable

from sqlalchemy.orm import Session as DBSession, sessionmaker

from titan.audit import log as audit
from titan.db.models import Conversation
from titan.memory import conversations as repo
from titan.models.providers import ChatTurn, ModelUnavailable, stream_reply
from titan.policies.model_gate import ProviderBlocked

log = logging.getLogger("titan.chat.stream")

Emit = Callable[[str, dict[str, Any]], None]


def run_reply_stream(session_factory: sessionmaker[DBSession], conversation_id: uuid.UUID,
                     provider: Any, turns: list[ChatTurn], emit: Emit,
                     cancel: threading.Event) -> None:
    parts: list[str] = []
    inner = stream_reply(provider, turns)
    started = time.monotonic()
    first_delta_ms = None
    try:
        for kind, payload in inner:
            if cancel.is_set():
                inner.close()
                saved = _save(session_factory, conversation_id, "".join(parts), provider,
                              status="interrupted")
                emit("interrupted", {"message": saved, "reason": "cancelado pelo usuário"})
                return
            if kind == "delta":
                if first_delta_ms is None:
                    first_delta_ms = int((time.monotonic() - started) * 1000)
                parts.append(payload)
                emit("delta", {"text": payload})
            elif kind == "done":
                saved = _save(session_factory, conversation_id, payload.content, provider,
                              status="complete", model_name=payload.model,
                              provider_name=payload.provider)
                emit("done", {"message": saved, "metrics": {
                    "first_delta_ms": first_delta_ms,
                    "total_ms": int((time.monotonic() - started) * 1000)}})
                return
    except (ModelUnavailable, ProviderBlocked) as exc:
        if parts:
            _save(session_factory, conversation_id, "".join(parts), provider, status="error")
        emit("error", {"detail": str(exc), "partial": bool(parts)})
    except Exception:
        log.exception("Falha inesperada no streaming da resposta")
        emit("error", {"detail": "Erro interno ao gerar a resposta. Consulte os logs.",
                       "partial": bool(parts)})


def _save(session_factory: sessionmaker[DBSession], conversation_id: uuid.UUID, text: str,
          provider: Any, *, status: str, model_name: str | None = None,
          provider_name: str | None = None) -> dict[str, Any] | None:
    text = text.strip()
    if not text:
        return None
    with session_factory.begin() as db:
        conv = db.get(Conversation, conversation_id)
        msg = repo.add_message(db, conv, "assistant", text,
                               model_provider=provider_name or provider.info.name,
                               model_name=model_name or getattr(provider, "model", None))
        msg.status = status
        if status == "interrupted":
            msg.interrupted_at_char = len(text)
        audit.record(db, "model.reply", actor_type="model", entity_type="message",
                     entity_id=str(msg.id),
                     data={"provider": msg.model_provider, "model": msg.model_name,
                           "status": status, "streamed": True})
        db.flush()
        return {"id": str(msg.id), "role": "assistant", "content": msg.content,
                "model_provider": msg.model_provider, "model_name": msg.model_name,
                "status": msg.status, "interrupted_at_char": msg.interrupted_at_char,
                "created_at": msg.created_at.isoformat()}
