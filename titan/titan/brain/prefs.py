"""Preferências do sócio: mensagens do TITAN e como a memória é guardada."""

from __future__ import annotations

import json
import re
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session as DBSession

from titan.db.models import MemoryItem, utcnow

KIND = "brain_prefs"
_HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
DEFAULTS: dict[str, Any] = {
    "auto_save": False,       # guardar sozinho as coisas simples (sem pedir aprovação)
    "bom_dia": "07:00",       # "" = desligado
    "boa_noite": "21:30",
    "papo": True,             # papo solto
    "papo_max": 1,            # por dia
    "socio_semana": True,     # conversa de sócio no domingo à tarde
    "acompanhar": True,       # perguntar sobre assuntos em aberto
    "silencio_inicio": "22:00",
    "silencio_fim": "07:00",
    "skipped_questions": [],
}


class PrefsError(ValueError):
    pass


def _row(db: DBSession, user_id: uuid.UUID):
    return db.scalar(select(MemoryItem).where(MemoryItem.user_id == user_id, MemoryItem.kind == KIND))


def get(db: DBSession, user_id: uuid.UUID) -> dict[str, Any]:
    row = _row(db, user_id)
    stored = json.loads(row.content) if row else {}
    return {**DEFAULTS, **{k: v for k, v in stored.items() if k in DEFAULTS}}


def validate(data: dict[str, Any]) -> dict[str, Any]:
    out = dict(DEFAULTS)
    for k in ("auto_save", "papo", "socio_semana", "acompanhar"):
        v = data.get(k, DEFAULTS[k])
        if not isinstance(v, bool):
            raise PrefsError(f"'{k}' deve ser verdadeiro ou falso.")
        out[k] = v
    for k in ("bom_dia", "boa_noite"):
        v = data.get(k, DEFAULTS[k]) or ""
        if v and not _HHMM.match(v):
            raise PrefsError(f"'{k}' deve ser HH:MM ou vazio (desligado).")
        out[k] = v
    for k in ("silencio_inicio", "silencio_fim"):
        v = data.get(k, DEFAULTS[k])
        if not isinstance(v, str) or not _HHMM.match(v):
            raise PrefsError(f"'{k}' deve ser HH:MM.")
        out[k] = v
    n = data.get("papo_max", 1)
    if not isinstance(n, int) or isinstance(n, bool) or not 0 <= n <= 3:
        raise PrefsError("'papo_max' deve ser de 0 a 3 por dia.")
    out["papo_max"] = n
    skipped = data.get("skipped_questions", [])
    if not isinstance(skipped, list) or len(skipped) > 100 or not all(isinstance(s, str) and len(s) <= 32 for s in skipped):
        raise PrefsError("'skipped_questions' inválido.")
    out["skipped_questions"] = list(dict.fromkeys(skipped))
    return out


def save(db: DBSession, user_id: uuid.UUID, data: dict[str, Any]) -> dict[str, Any]:
    prefs = validate({**get(db, user_id), **data})
    row = _row(db, user_id)
    content = json.dumps(prefs, ensure_ascii=False)
    if row is None:
        db.add(MemoryItem(user_id=user_id, kind=KIND, content=content, source="usuário"))
    else:
        row.content, row.updated_at = content, utcnow()
    db.flush()
    return prefs
