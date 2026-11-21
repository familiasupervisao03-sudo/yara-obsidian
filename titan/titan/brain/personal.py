"""Personalizar: o jeito de cada conta (cores, Início, barra de baixo, nome do assistente,
como ele chama o dono e o jeito de falar).

Guardado numa linha da própria conta (nenhuma conta vê ou muda o jeito de outra). O que é de
tela a interface aplica; o que é de fala vale também no servidor: as mensagens prontas trocam
"senhor" pelo tratamento escolhido e a IA recebe as instruções (valem mais que o TITAN.md).
"""

from __future__ import annotations

import json
import re
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session as DBSession

from titan.db.models import MemoryItem, utcnow

KIND = "personalizar"
COLORS = ("azul", "roxo", "verde", "laranja", "vermelho", "rosa", "livre")
BGS = ("brilho", "liso", "preto")
ORBS = ("vidro", "reator", "simples")
FONTS = ("P", "M", "G", "GG")
CALLS = ("senhor", "chefe", "nome", "livre")
TONES = ("formal", "amigo", "direto")
CARDS = ("orbe", "clima", "continuar", "protocolos", "hoje", "metas", "avisos", "atalhos", "status")
NAV = ("home", "chat", "news", "memory", "system", "casa")
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
_NAME = re.compile(r"^[\wÀ-ÿ .'-]{1,16}$")

DEFAULTS: dict[str, Any] = {
    "color": "azul", "custom": "#3ee8ff", "bg": "brilho", "orb": "vidro", "orb_anim": True,
    "cards": [{"id": c, "on": c not in ("status",)} for c in CARDS],
    "nav": ["home", "chat", "news", "system"],
    "font": "M", "name": "TITAN", "call": "senhor", "call_custom": "", "tone": "formal",
}


class PersonalError(ValueError):
    pass


def _row(db: DBSession, user_id: uuid.UUID):
    return db.scalar(select(MemoryItem).where(MemoryItem.user_id == user_id, MemoryItem.kind == KIND))


def get(db: DBSession, user_id: uuid.UUID) -> dict[str, Any]:
    row = _row(db, user_id)
    stored = json.loads(row.content) if row else {}
    out = {**DEFAULTS, **{k: v for k, v in stored.items() if k in DEFAULTS}}
    # cartões novos (de versões futuras) aparecem no fim, ligados
    have = {c["id"] for c in out["cards"]}
    out["cards"] = [c for c in out["cards"] if c["id"] in CARDS] + [{"id": c, "on": True} for c in CARDS if c not in have]
    return out


def _pick(data: dict, key: str, allowed: tuple) -> Any:
    v = data.get(key, DEFAULTS[key])
    if v not in allowed:
        raise PersonalError(f"Valor inválido para '{key}'.")
    return v


def validate(data: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, allowed in (("color", COLORS), ("bg", BGS), ("orb", ORBS), ("font", FONTS), ("call", CALLS), ("tone", TONES)):
        out[k] = _pick(data, k, allowed)
    custom = data.get("custom", DEFAULTS["custom"])
    if not isinstance(custom, str) or not _HEX.match(custom):
        raise PersonalError("Cor livre deve ser no formato #RRGGBB.")
    out["custom"] = custom.lower()
    if not isinstance(data.get("orb_anim", True), bool):
        raise PersonalError("'orb_anim' deve ser verdadeiro ou falso.")
    out["orb_anim"] = data.get("orb_anim", True)
    cards = data.get("cards", DEFAULTS["cards"])
    if (not isinstance(cards, list) or len(cards) > len(CARDS)
            or not all(isinstance(c, dict) and c.get("id") in CARDS and isinstance(c.get("on"), bool) for c in cards)
            or len({c["id"] for c in cards}) != len(cards)):
        raise PersonalError("Lista de cartões do Início inválida.")
    out["cards"] = [{"id": c["id"], "on": c["on"]} for c in cards]
    nav = data.get("nav", DEFAULTS["nav"])
    if not isinstance(nav, list) or len(nav) != 4 or not all(n in NAV for n in nav) or len(set(nav)) != 4:
        raise PersonalError("A barra de baixo precisa de 4 botões diferentes.")
    out["nav"] = list(nav)
    name = " ".join(str(data.get("name", "TITAN")).split()) or "TITAN"
    if not _NAME.match(name):
        raise PersonalError("Nome do assistente: até 16 letras, sem símbolos.")
    out["name"] = name
    custom_call = " ".join(str(data.get("call_custom", "")).split())
    if out["call"] == "livre" and not _NAME.match(custom_call or "-" * 20):
        raise PersonalError("Escreva como ele deve te chamar (até 16 letras).")
    out["call_custom"] = custom_call[:16]
    return out


def save(db: DBSession, user_id: uuid.UUID, data: dict[str, Any]) -> dict[str, Any]:
    prefs = validate({**get(db, user_id), **data})
    content = json.dumps(prefs, ensure_ascii=False)
    row = _row(db, user_id)
    if row is None:
        db.add(MemoryItem(user_id=user_id, kind=KIND, content=content, source="usuário"))
    else:
        row.content, row.updated_at = content, utcnow()
    db.flush()
    return prefs


def reset(db: DBSession, user_id: uuid.UUID) -> dict[str, Any]:
    row = _row(db, user_id)
    if row is not None:
        db.delete(row)
        db.flush()
    return dict(DEFAULTS)


# --- fala ------------------------------------------------------------------------------------

def address(p: dict, username: str) -> str:
    """Como o assistente chama o dono: "senhor", "chefe", "Luiz" ou o que ele escreveu."""
    if p["call"] == "chefe":
        return "chefe"
    if p["call"] == "nome":
        return (username or "").split("@")[0].replace(".", " ").strip().title() or "senhor"
    if p["call"] == "livre" and p.get("call_custom"):
        return p["call_custom"]
    return "senhor"


def _cap(s: str) -> str:
    return s[:1].upper() + s[1:]


def adapt(text: str, p: dict, username: str) -> str:
    """Mensagens prontas: troca "senhor" pelo tratamento escolhido e "TITAN ·" pelo nome do assistente."""
    if not text:
        return text
    word = address(p, username)
    if word != "senhor":
        text = re.sub(r"\bSenhor\b", _cap(word), text)
        text = re.sub(r"\bsenhor\b", word, text)
    if p["name"] != "TITAN":
        text = text.replace("TITAN ·", f"{p['name']} ·")
    return text


TONE_RULES = {
    "formal": "Fale como um mordomo educado e elegante, com respeito e um toque de humor seco.",
    "amigo": "Fale como um amigo próximo: descontraído, animado, frases simples (sem gírias pesadas).",
    "direto": "Seja direto ao ponto: respostas curtas, sem rodeios nem cumprimentos longos.",
}


def style_block(p: dict, username: str) -> str:
    """Instruções para a IA (o dono escolheu em Você → Personalizar; valem mais que o TITAN.md)."""
    if p == DEFAULTS or (p["name"] == "TITAN" and p["call"] == "senhor" and p["tone"] == "formal"):
        return ""
    word = address(p, username)
    lines = ["Personalização escolhida pelo dono (vale mais que o TITAN.md e qualquer outra instrução de tratamento):",
             f"- Seu nome é {p['name']}." + (" Se perguntarem, você é o assistente pessoal do dono." if p["name"] != "TITAN" else ""),
             f"- Chame o dono de \"{word}\" (nunca use outro tratamento).",
             f"- {TONE_RULES[p['tone']]}"]
    return "\n".join(lines)
