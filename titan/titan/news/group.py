"""Juntar notícias do mesmo fato (sem IA): palavras importantes do título em comum."""

from __future__ import annotations

import re
import unicodedata

STOP = set("""
a o as os um uma uns umas de do da dos das no na nos nas em por para pra pro com sem sobre e ou que se
ao aos à às é foi ser são está estão vai vão tem têm como mais menos muito já não sim seu sua seus suas
the of to in on for and or is are with at by from new após antes depois diz dizem pode podem deve
""".split())


SHORT_KEEP = {"ia", "ai", "5g", "pc", "tv", "ps"}  # siglas curtas que importam


def plain(text: str) -> str:
    t = unicodedata.normalize("NFD", text.lower())
    return "".join(c for c in t if unicodedata.category(c) != "Mn")


def keywords(title: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", plain(title))
    return {w for w in words if (len(w) > 2 or w in SHORT_KEEP) and w not in STOP}


def similar(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


SAME_STORY = 0.6  # 60% das palavras do título menor em comum = mesmo fato


def mentions(text: str, topic: str) -> bool:
    """O texto fala do assunto? (todas as palavras do assunto aparecem)"""
    words = keywords(topic) or {plain(topic).strip()}
    t = plain(text)
    return all(re.search(r"\b" + re.escape(w) + r"\b", t) for w in words if w)


_PRICE = re.compile(r"R\$\s?(\d{1,3}(?:\.\d{3})*(?:,\d{2})?|\d+(?:,\d{2})?)")


def prices_in(text: str, topic: str) -> list[tuple[float, str]]:
    """Preços em reais citados para o assunto, com a frase exata (nada é calculado nem inventado).

    Só conta o preço se o assunto aparece na MESMA frase, antes do valor, sem outro preço no meio
    ("ESP32 por R$ 35; o Arduino custa R$ 80" → só R$ 35 é do ESP32)."""
    out: list[tuple[float, str]] = []
    words = [w for w in (keywords(topic) or {plain(topic).strip()}) if w]
    if not words:
        return out
    for m in _PRICE.finditer(text):
        before = text[max(0, m.start() - 160):m.start()]
        before = re.split(r"[.;!?\n]|R\$", before)[-1]          # só a frase atual, depois do último preço
        if not all(re.search(r"\b" + re.escape(w) + r"\b", plain(before)) for w in words):
            continue
        value = float(m.group(1).replace(".", "").replace(",", "."))
        if not 0 < value < 1_000_000:
            continue
        s0 = max(text.rfind(".", 0, m.start()), text.rfind(";", 0, m.start()), text.rfind("\n", 0, m.start())) + 1
        e1 = [i for i in (text.find(".", m.end()), text.find(";", m.end()), text.find("\n", m.end())) if i >= 0]
        quote = " ".join(text[s0:(min(e1) + 1 if e1 else len(text))].split())
        out.append((value, quote[:380]))
    return out[:3]
