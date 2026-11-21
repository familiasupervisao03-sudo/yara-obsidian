"""Preferências explícitas do usuário (adaptação do TITAN ao jeito do dono).

Guardadas no banco local, por usuário, em ``memory_items`` (kind="preferences"),
como JSON validado. Nada é inferido em silêncio: só entra o que o usuário escolhe
(ou confirma, no caso de uma correção sugerida pela tela de voz). O usuário pode
consultar, alterar e apagar tudo pela API.

Limites de segurança:
* tamanho, formalidade e exemplos são opções fechadas que viram frases fixas
  (titan/memory/style.py) — nenhum texto livre daqui chega ao prompt do sistema;
* correções só trocam palavras na transcrição da fala do próprio usuário, com
  aviso na tela; não mudam permissões, aprovações nem regras.
"""

from __future__ import annotations

import json
import re
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session as DBSession

from titan.db.models import MemoryItem, utcnow

KIND = "preferences"
CHOICES = {
    "response_length": ("curta", "normal", "detalhada"),
    "formality": ("informal", "neutra", "formal"),
    "examples": ("auto", "sim", "nao"),
}
DEFAULTS: dict[str, Any] = {"response_length": "normal", "formality": "neutra", "examples": "auto",
                            "voice_rate": 0, "corrections": []}
MAX_CORRECTIONS = 50
_WORDS = re.compile(r"^[\w\s'-]{1,60}$")


class PreferenceError(ValueError):
    pass


def _row(db: DBSession, user_id: uuid.UUID) -> MemoryItem | None:
    return db.scalar(select(MemoryItem).where(MemoryItem.user_id == user_id, MemoryItem.kind == KIND))


def get(db: DBSession, user_id: uuid.UUID) -> dict[str, Any]:
    row = _row(db, user_id)
    stored = json.loads(row.content) if row else {}
    return {**DEFAULTS, **{k: v for k, v in stored.items() if k in DEFAULTS}}


def validate(data: dict[str, Any]) -> dict[str, Any]:
    out = dict(DEFAULTS)
    for key, allowed in CHOICES.items():
        value = data.get(key, DEFAULTS[key])
        if value not in allowed:
            raise PreferenceError(f"'{key}' deve ser um de: {', '.join(allowed)}.")
        out[key] = value
    rate = data.get("voice_rate", 0)
    if not isinstance(rate, int) or isinstance(rate, bool) or not -30 <= rate <= 30:
        raise PreferenceError("'voice_rate' deve ser um inteiro de -30 a 30 (% da velocidade normal).")
    out["voice_rate"] = rate
    corrections = data.get("corrections", [])
    if not isinstance(corrections, list) or len(corrections) > MAX_CORRECTIONS:
        raise PreferenceError(f"'corrections' deve ser uma lista de até {MAX_CORRECTIONS} itens.")
    clean, seen = [], set()
    for c in corrections:
        heard = str((c or {}).get("heard", "")).strip().lower()
        meant = str((c or {}).get("meant", "")).strip()
        if not (_WORDS.match(heard) and _WORDS.match(meant)) or heard == meant.lower():
            raise PreferenceError("Cada correção precisa de 'heard' e 'meant' diferentes, só com "
                                  "letras, números, espaços, hífen ou apóstrofo (até 60 caracteres).")
        if heard not in seen:
            seen.add(heard)
            clean.append({"heard": heard, "meant": meant})
    out["corrections"] = clean
    return out


def save(db: DBSession, user_id: uuid.UUID, data: dict[str, Any]) -> dict[str, Any]:
    prefs = validate(data)
    row = _row(db, user_id)
    content = json.dumps(prefs, ensure_ascii=False)
    if row is None:
        db.add(MemoryItem(user_id=user_id, kind=KIND, content=content, source="usuário"))
    else:
        row.content, row.updated_at = content, utcnow()
    db.flush()
    return prefs


def delete(db: DBSession, user_id: uuid.UUID) -> bool:
    row = _row(db, user_id)
    if row is None:
        return False
    db.delete(row)
    db.flush()
    return True


def apply_corrections(text: str, corrections: list[dict[str, str]]) -> tuple[str, list[str]]:
    """Troca palavras inteiras conforme as correções do usuário (maior expressão primeiro).

    Devolve o texto e a lista do que foi trocado, para a tela mostrar — nada é
    reescrito sem aviso.
    """
    applied = []
    for c in sorted(corrections, key=lambda c: -len(c["heard"])):
        pattern = re.compile(rf"(?<!\w){re.escape(c['heard'])}(?!\w)", re.IGNORECASE)
        if pattern.search(text):
            text = pattern.sub(c["meant"], text)
            applied.append(f"{c['heard']} → {c['meant']}")
    return text, applied
