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

from sqlalchemy import event, select, text
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


def _hold_sqlite_write_lock(db: DBSession) -> None:
    """No SQLite, pega a trava de escrita do banco ANTES da trava da cadeia.

    Sempre na mesma ordem (banco → cadeia): sem isso, uma transação que já tinha a
    trava do banco esperava a da cadeia, enquanto outra tinha a da cadeia e esperava
    a do banco — as duas ficavam paradas até o limite de 15 s ('database is locked').
    Achado pela simulação contínua (docs/simulacao.md). O UPDATE não altera nenhuma
    linha; só abre a transação de escrita (o PostgreSQL não precisa disso).
    """
    if db.info.get(_LOCK_FLAG) or db.get_bind().dialect.name != "sqlite":
        return
    db.flush()
    db.execute(text("UPDATE audit_events SET id = id WHERE 1 = 0"))


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
    _hold_sqlite_write_lock(db)
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


_COLUMNS = (AuditEvent.id, AuditEvent.created_at, AuditEvent.actor_type, AuditEvent.actor_id,
            AuditEvent.event_type, AuditEvent.task_id, AuditEvent.entity_type, AuditEvent.entity_id,
            AuditEvent.data, AuditEvent.prev_hash, AuditEvent.hash)


def _walk(db: DBSession, after_id: int, prev: str) -> tuple[bool, Optional[int], int, str]:
    """Confere a cadeia a partir de ``after_id`` (cujo hash é ``prev``).

    Lê só as colunas necessárias, em blocos — não carrega todos os eventos na memória.
    Retorna (íntegra?, id do primeiro inválido, último id, último hash).
    """
    q = (select(*_COLUMNS).where(AuditEvent.id > after_id).order_by(AuditEvent.id)
         .execution_options(yield_per=500))
    last_id = after_id
    for row in db.execute(q):
        if row.prev_hash != prev or row.hash != _digest(prev, _payload(row)):
            return False, row.id, last_id, prev
        prev, last_id = row.hash, row.id
    return True, None, last_id, prev


def verify_chain(db: DBSession) -> tuple[bool, Optional[int]]:
    """Retorna (íntegra?, id do primeiro evento inválido)."""
    ok, bad, _, _ = _walk(db, 0, GENESIS_HASH)
    return ok, bad


class ChainMonitor:
    """Verificação da cadeia para a tela de estado (consultada a cada 30 s).

    Confere só os eventos novos desde a última vez (mais o último já conferido, para
    perceber se foi alterado) e a cadeia inteira a cada ``full_every`` segundos — antes,
    cada consulta relia o histórico inteiro, e o custo crescia sem parar com o uso
    (achado pela simulação contínua). Uma falha fica marcada até reiniciar o servidor.
    ``titan audit-verify`` sempre confere tudo.
    """

    def __init__(self, full_every: float = 600.0) -> None:
        self.full_every = full_every
        self._lock = threading.Lock()
        self._last: Optional[tuple[int, str]] = None
        self._full_at = 0.0
        self._bad: Optional[int] = None

    def check(self, db: DBSession) -> tuple[bool, Optional[int]]:
        import time

        with self._lock:
            if self._bad is not None:
                return False, self._bad
            now = time.monotonic()
            if self._last is None or now - self._full_at >= self.full_every:
                ok, bad, last_id, last_hash = _walk(db, 0, GENESIS_HASH)
                self._full_at = now
            else:
                last_id, last_hash = self._last
                # O último evento já conferido: ainda existe, com o mesmo hash e conteúdo?
                anchor = db.execute(select(*_COLUMNS).where(AuditEvent.id == last_id)).first() if last_id else None
                if last_id and (anchor is None or anchor.hash != last_hash
                                or _digest(anchor.prev_hash, _payload(anchor)) != last_hash):
                    ok, bad = False, last_id
                else:
                    ok, bad, last_id, last_hash = _walk(db, last_id, last_hash)
            if not ok:
                self._bad = bad
                return False, bad
            self._last = (last_id, last_hash)
            return True, None
