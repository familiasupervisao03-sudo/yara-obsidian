"""Registro de auditoria encadeado por hash.

Cada evento guarda o hash do anterior; ``verify_chain`` detecta remoções ou
alterações. Os dados são redigidos antes de serem gravados.
"""

from __future__ import annotations

import hashlib
import json
import threading
import uuid
from typing import Any, Optional

from sqlalchemy import event, select
from sqlalchemy.orm import Session as DBSession

from titan.core.redaction import redact
from titan.db.models import AuditEvent, utcnow

GENESIS_HASH = "0" * 64

# O TITAN roda em processo único. O lock é mantido do primeiro evento até o
# commit/rollback da transação, para que duas transações nunca encadeiem a
# partir do mesmo evento anterior. (Lock simples: pode ser liberado por outra
# thread, como acontece no teardown de dependências do FastAPI.)
_chain_lock = threading.Lock()
_LOCK_FLAG = "titan_audit_lock"


def _acquire(db: DBSession) -> None:
    if not db.info.get(_LOCK_FLAG):
        _chain_lock.acquire()
        db.info[_LOCK_FLAG] = True


@event.listens_for(DBSession, "after_commit")
@event.listens_for(DBSession, "after_rollback")
def _release(db: DBSession) -> None:
    if db.info.pop(_LOCK_FLAG, False):
        _chain_lock.release()


def _digest(prev_hash: str, payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256((prev_hash + canonical).encode()).hexdigest()


def _payload(ev: AuditEvent) -> dict[str, Any]:
    return {
        "created_at": ev.created_at.isoformat(),
        "actor_type": ev.actor_type,
        "actor_id": str(ev.actor_id) if ev.actor_id else None,
        "event_type": ev.event_type,
        "task_id": str(ev.task_id) if ev.task_id else None,
        "entity_type": ev.entity_type,
        "entity_id": ev.entity_id,
        "data": ev.data,
    }


def record(
    db: DBSession,
    event_type: str,
    *,
    actor_type: str = "system",
    actor_id: Optional[uuid.UUID] = None,
    task_id: Optional[uuid.UUID] = None,
    entity_type: Optional[str] = None,
    entity_id: Optional[str] = None,
    data: Optional[dict[str, Any]] = None,
) -> AuditEvent:
    """Adiciona um evento na transação corrente (gravado no commit do chamador).

    O chamador DEVE encerrar a transação (commit ou rollback) para liberar a cadeia.
    """
    _acquire(db)
    try:
        last = db.scalar(select(AuditEvent).order_by(AuditEvent.id.desc()).limit(1))
        prev_hash = last.hash if last else GENESIS_HASH
        ev = AuditEvent(
            created_at=utcnow().replace(microsecond=0),
            actor_type=actor_type,
            actor_id=actor_id,
            event_type=event_type,
            task_id=task_id,
            entity_type=entity_type,
            entity_id=entity_id,
            data=redact(data or {}),
            prev_hash=prev_hash,
        )
        ev.hash = _digest(prev_hash, _payload(ev))
        db.add(ev)
        db.flush()
        return ev
    except Exception:
        db.rollback()  # libera o lock e desfaz a transação parcial
        raise


def verify_chain(db: DBSession) -> tuple[bool, Optional[int]]:
    """Retorna (íntegra?, id do primeiro evento inválido)."""
    prev = GENESIS_HASH
    for ev in db.scalars(select(AuditEvent).order_by(AuditEvent.id)):
        if ev.prev_hash != prev or ev.hash != _digest(prev, _payload(ev)):
            return False, ev.id
        prev = ev.hash
    return True, None
