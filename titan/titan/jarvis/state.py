"""Ajustes e estado de cada conta (cidade, chegada/saída, silêncio, último clima).

Guardado como uma linha JSON da própria conta (mesmo jeito das preferências do sócio):
nenhuma conta enxerga o estado de outra.
"""

from __future__ import annotations

import json
import re
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session as DBSession

from titan.db.models import MemoryItem, utcnow

KIND = "jarvis"
PREF_KEYS = ("rain_alert", "welcome", "ask_leave")
DEFAULTS: dict[str, Any] = {
    "place": None,            # {"name", "admin1", "lat", "lon"} escolhida pelo dono
    "rain_alert": True,       # avisar antes da chuva
    "welcome": True,          # boas-vindas ao chegar
    "ask_leave": True,        # perguntar se desliga o que ficou ligado ao sair
    "arrive_steps": [],       # o que ligar ao chegar (o dono cadastra): [{"device_id", "do"}]
    "presence": "",           # "home" | "away" | "" (ainda não sabe)
    "presence_at": None,
    "left_at": None,
    "quiet_until": None,      # avisos de notícias calados até (ISO, UTC)
    "weather": None,          # resposta do Open-Meteo guardada
    "weather_at": None,
    "weather_error": "",
    "rain_alerted": "",       # hora da chuva já avisada (não repete)
    "pending_protocol": None,  # {"id", "at"}: perguntou "posso executar?" e espera o "sim"
}
_UUID = re.compile(r"^[0-9a-f-]{36}$")


class StateError(ValueError):
    pass


def _row(db: DBSession, user_id: uuid.UUID):
    return db.scalar(select(MemoryItem).where(MemoryItem.user_id == user_id, MemoryItem.kind == KIND))


def get(db: DBSession, user_id: uuid.UUID) -> dict[str, Any]:
    row = _row(db, user_id)
    stored = json.loads(row.content) if row else {}
    return {**DEFAULTS, **{k: v for k, v in stored.items() if k in DEFAULTS}}


def save(db: DBSession, user_id: uuid.UUID, patch: dict[str, Any]) -> dict[str, Any]:
    data = {**get(db, user_id), **{k: v for k, v in patch.items() if k in DEFAULTS}}
    content = json.dumps(data, ensure_ascii=False, default=str)
    row = _row(db, user_id)
    if row is None:
        db.add(MemoryItem(user_id=user_id, kind=KIND, content=content, source="titan"))
    else:
        row.content, row.updated_at = content, utcnow()
    db.flush()
    return data


def clean_steps(steps: Any) -> list[dict]:
    """Passos de aparelho vindos da tela: só id + ação conhecida (o aparelho é conferido ao executar)."""
    if not isinstance(steps, list) or len(steps) > 30:
        raise StateError("Lista de aparelhos inválida.")
    out = []
    for s in steps:
        if not isinstance(s, dict) or not _UUID.match(str(s.get("device_id", ""))) or s.get("do") not in ("on", "off", "dim"):
            raise StateError("Aparelho ou ação inválida.")
        out.append({"device_id": str(s["device_id"]), "do": s["do"]})
    return out
