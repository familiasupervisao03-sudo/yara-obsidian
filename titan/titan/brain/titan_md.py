"""TITAN.md: o manual de como o TITAN age com o dono (cada conta tem o seu).

Fica no banco (nunca em arquivo do repositório). O dono edita à vontade; o TITAN só
SUGERE linhas novas, que entram quando o dono toca em "Guardar" (a IA não aprova as
próprias mudanças: assim um site ou mensagem estranha não "reprograma" o TITAN).
Cada mudança vira uma versão nova: dá para ver o histórico e desfazer.
"""

from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session as DBSession

from titan.db.models import TitanMdSuggestion, TitanMdVersion

MAX_CHARS = 8000
SECTIONS = ("Quem sou eu", "Como falar comigo", "Regras", "O que o TITAN aprendeu")

TEMPLATE = """# Como o TITAN age comigo

## Quem sou eu
- (como quer ser chamado, o que faz, o que é importante pra você)

## Como falar comigo
- (jeito de falar, tamanho das respostas, por voz e por texto)

## Regras
- (o que o TITAN sempre deve ou nunca deve fazer)

## O que o TITAN aprendeu
"""


class ManualError(ValueError):
    pass


def latest(db: DBSession, user_id: uuid.UUID) -> Optional[TitanMdVersion]:
    return db.scalar(select(TitanMdVersion).where(TitanMdVersion.user_id == user_id)
                     .order_by(TitanMdVersion.created_at.desc(), TitanMdVersion.id.desc()).limit(1))


def content(db: DBSession, user_id: uuid.UUID) -> str:
    v = latest(db, user_id)
    return v.content if v else TEMPLATE


def save(db: DBSession, user_id: uuid.UUID, text: str, source: str = "dono", note: str = "") -> TitanMdVersion:
    text = (text or "").replace("\r\n", "\n").strip() + "\n"
    if len(text) > MAX_CHARS:
        raise ManualError(f"O TITAN.md pode ter no máximo {MAX_CHARS} letras.")
    cur = latest(db, user_id)
    if cur and cur.content == text:
        return cur
    v = TitanMdVersion(user_id=user_id, content=text, source=source, note=note[:300])
    db.add(v)
    db.flush()
    return v


def history(db: DBSession, user_id: uuid.UUID, limit: int = 20) -> list[TitanMdVersion]:
    return list(db.scalars(select(TitanMdVersion).where(TitanMdVersion.user_id == user_id)
                           .order_by(TitanMdVersion.created_at.desc(), TitanMdVersion.id.desc()).limit(limit)))


def undo(db: DBSession, user_id: uuid.UUID) -> TitanMdVersion:
    """Volta para a versão anterior (vira uma versão nova: nada se perde)."""
    h = history(db, user_id, 2)
    if not h:
        raise ManualError("Ainda não há mudanças para desfazer.")
    previous = h[1].content if len(h) > 1 else TEMPLATE
    return save(db, user_id, previous, "desfazer", "voltou para a versão anterior")


def add_line(text: str, section: str, line: str) -> str:
    """Põe "- linha" no fim da seção (cria a seção se não existir)."""
    line = "- " + line.strip().lstrip("-• ").strip()
    lines = text.rstrip("\n").split("\n")
    head = f"## {section}".lower()
    try:
        start = next(i for i, l in enumerate(lines) if l.strip().lower() == head)
    except StopIteration:
        return "\n".join(lines) + f"\n\n## {section}\n{line}\n"
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    while end > start + 1 and not lines[end - 1].strip():
        end -= 1
    lines.insert(end, line)
    return "\n".join(lines) + "\n"


def suggest(db: DBSession, user_id: uuid.UUID, line: str, section: str,
            conversation_id: Optional[uuid.UUID] = None) -> Optional[TitanMdSuggestion]:
    line = " ".join((line or "").split())[:280].strip().lstrip("-• ")
    if not line:
        return None
    section = section if section in SECTIONS else "O que o TITAN aprendeu"
    if line.lower() in content(db, user_id).lower():
        return None  # já está no manual
    dup = db.scalar(select(TitanMdSuggestion).where(
        TitanMdSuggestion.user_id == user_id, TitanMdSuggestion.status == "pending",
        TitanMdSuggestion.line == line))
    if dup:
        return dup
    s = TitanMdSuggestion(user_id=user_id, line=line, section=section, conversation_id=conversation_id)
    db.add(s)
    db.flush()
    return s


def pending(db: DBSession, user_id: uuid.UUID) -> list[TitanMdSuggestion]:
    return list(db.scalars(select(TitanMdSuggestion).where(
        TitanMdSuggestion.user_id == user_id, TitanMdSuggestion.status == "pending")
        .order_by(TitanMdSuggestion.created_at.desc()).limit(20)))


def _own(db: DBSession, user_id: uuid.UUID, sid: uuid.UUID) -> TitanMdSuggestion:
    s = db.get(TitanMdSuggestion, sid)
    if s is None or s.user_id != user_id:  # sugestão de outra conta: como se não existisse
        raise LookupError(str(sid))
    return s


def accept(db: DBSession, user_id: uuid.UUID, sid: uuid.UUID) -> TitanMdVersion:
    s = _own(db, user_id, sid)
    if s.status != "pending":
        raise ManualError("Essa sugestão já foi respondida.")
    s.status = "accepted"
    return save(db, user_id, add_line(content(db, user_id), s.section, s.line), "titan", s.line)


def dismiss(db: DBSession, user_id: uuid.UUID, sid: uuid.UUID) -> None:
    s = _own(db, user_id, sid)
    if s.status == "pending":
        s.status = "dismissed"


def context_block(db: DBSession, user_id: uuid.UUID) -> str:
    """O manual vai junto de cada conversa (texto do dono: preferências, não ordens de segurança)."""
    v = latest(db, user_id)
    if v is None or not v.content.strip() or v.content == TEMPLATE:
        return ""
    return ("MANUAL DO DONO (TITAN.md) — como ele quer que você aja com ele. Siga essas preferências "
            "de jeito, tom e rotina. Elas NÃO mudam as regras de segurança, NÃO autorizam ações sem "
            "aprovação e NÃO liberam gastos.\n" + v.content[:MAX_CHARS])
