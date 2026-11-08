"""Lembrete na hora, sem IA: "me lembra de tirar o bolo às 2:30 da tarde" → (título, quando).

Mesma regra de apps/web/src/central/reminder.ts (Central e Casa), para o chat do TITAN também
criar o lembrete com certeza, mesmo com a IA em pausa. Sem hora reconhecida: devolve None e a
frase segue para a IA (que pergunta o horário).
"""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timedelta
from typing import Optional

NUM = {"zero": 0, "um": 1, "uma": 1, "dois": 2, "duas": 2, "tres": 3, "quatro": 4, "cinco": 5, "seis": 6, "sete": 7,
       "oito": 8, "nove": 9, "dez": 10, "onze": 11, "doze": 12, "treze": 13, "catorze": 14, "quatorze": 14,
       "quinze": 15, "dezesseis": 16, "dezessete": 17, "dezoito": 18, "dezenove": 19, "vinte": 20, "trinta": 30,
       "quarenta": 40, "cinquenta": 50, "meia": 30, "meio": 12}
_NW = "|".join(sorted(NUM, key=len, reverse=True))
_N = rf"(?:\d{{1,2}}|(?:{_NW})(?: e (?:{_NW}))?)"
_H = rf"(?:\d{{1,2}}|vinte e (?:um|uma|dois|duas|tres)|{_NW})"
TRIGGER = re.compile(r"\b(lembrete|lembra|lembre|lembrar|avisa|avise|avisar|alarme|alerta)\b")


def plain(t: str) -> str:
    """Sem acento e minúsculo, com o MESMO tamanho (letra por letra)."""
    return "".join(unicodedata.normalize("NFD", c)[0] for c in t).lower()


def _num(s: Optional[str]) -> Optional[int]:
    if not s:
        return None
    s = s.strip()
    if s.isdigit():
        return int(s)
    total = 0
    for w in s.split(" e "):
        if w not in NUM:
            return None
        total += NUM[w]
    return total


def simple_request(text: str) -> bool:
    """Pedido simples (uma frase curta)? Mensagens com vários pedidos ("me lembra X. E anota Y")
    ficam com a IA, que separa tudo (lembrete, tarefa, memória)."""
    t = text.strip()
    parts = [p for p in re.split(r"[.!?;]+\s+", t) if p.strip()]
    return len(t) <= 140 and len(parts) <= 1 and not re.search(r"\b(e anota|anota|e tamb[eé]m|e mais)\b", plain(t))


def parse_reminder(text: str, now: Optional[datetime] = None) -> Optional[tuple[str, datetime]]:
    now = now or datetime.now().astimezone()
    if not simple_request(text):
        return None
    orig = re.sub(r"\s+", " ", re.sub(r"[,.!?]", " ", text)).strip()
    t = plain(orig)
    if not TRIGGER.search(t):
        return None
    rest = f" {t} "
    due: Optional[datetime] = None

    rel = re.search(rf" (?:daqui a|daqui|em|dentro de) ({_N}|meia) (minutos?|min|horas?|h)\b", rest)
    if rel:
        n = 30 if rel.group(1) == "meia" else _num(rel.group(1))
        if n is not None:
            mins = 30 if rel.group(1) == "meia" else (n * 60 if rel.group(2).startswith("h") else n)
            due = now + timedelta(minutes=mins)
            rest = rest.replace(rel.group(0), " ", 1)

    shift: Optional[int] = None
    day = re.search(r" (depois de amanha|amanha|hoje)\b", rest)
    if day:
        shift = {"hoje": 0, "amanha": 1}.get(day.group(1), 2)
        rest = rest.replace(day.group(0), " ", 1)

    if due is None:
        h: Optional[int] = None
        m, period = 0, ""
        sp = re.search(r" (?:as |a )?(meio dia|meio-dia|meia noite|meia-noite)\b", rest)
        if sp:
            h = 12 if sp.group(1).startswith("meio") else 0
            rest = rest.replace(sp.group(0), " ", 1)
        else:
            pat = re.compile(rf" (?:as |a |pras |para as |pra )?({_H})(?:(?: ?[:h] ?| horas? e | e )({_N}))?"
                             rf"(?: ?(?:horas?|h|hrs?))?(?: (da manha|da tarde|da noite|da madrugada))?(?= |$)")
            for mm in pat.finditer(rest):
                hh = _num(mm.group(1))
                if hh is None or hh > 23 or not re.search(
                        r" (as|a|pras|pra|para as) |[:h]|hora|da (manha|tarde|noite|madrugada)", mm.group(0)):
                    continue
                mins = _num(mm.group(2)) or 0
                if mins > 59:
                    continue
                h, m, period = hh, mins, mm.group(3) or ""
                rest = rest.replace(mm.group(0), " ", 1)
                break
        if h is None:
            return None
        if period in ("da tarde", "da noite") and h < 12:
            h += 12
        if period == "da manha" and h == 12:
            h = 0
        due = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if shift is not None:
            due += timedelta(days=shift)
        elif due <= now:
            pm = due + timedelta(hours=12)
            due = pm if (not period and h < 12 and pm > now) else due + timedelta(days=1)
    elif shift:
        due += timedelta(days=shift)

    title = rest
    title = re.sub(r"^\s*(ei |hey |ok )?tita[no]?\b", " ", title)  # só o "Ei, Titã" do começo
    for pat_ in (
                 r"\b(cria|crie|criar|faz|faca|fazer|coloca|coloque|bota|poe|marca|marque|agenda|agende|adiciona|adicione)\b",
                 r"\b(um|uma|o|a)? ?(lembrete|alarme|alerta)\b", r"\b(pra|para|por favor|favor|pfv|que|voce|vc)\b",
                 r"\b(me )?(lembra|lembre|lembrar|avisa|avise|avisar)( me)?\b"):
        title = re.sub(pat_, " ", title)
    title = re.sub(r"\s+", " ", title).strip()
    title = re.sub(r"^(de|do|da|que|sobre|pra|para|e|o|a)\s+", "", title)
    title = re.sub(r"^(de|do|da)\s+", "", title).strip()
    # volta as palavras do original (com acento)
    ow, pw = orig.split(" "), t.split(" ")
    out, start = [], 0
    for w in title.split(" ") if title else []:
        try:
            i = pw.index(w, start)
            out.append(ow[i])
            start = i + 1
        except ValueError:
            out.append(w)
    final = " ".join(out)
    return (final[:1].upper() + final[1:] if final else "Lembrete"), due


def when_text(d: datetime, now: Optional[datetime] = None) -> str:
    now = now or datetime.now().astimezone()
    hm = d.strftime("%H:%M")
    diff = (d.date() - now.date()).days
    return f"hoje às {hm}" if diff == 0 else f"amanhã às {hm}" if diff == 1 else f"{d.strftime('%d/%m')} às {hm}"
