"""Fontes padrão e leitura de feeds RSS/Atom (biblioteca padrão; nada da página é executado)."""

from __future__ import annotations

import html
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Optional
from urllib.parse import urlsplit

CATEGORIES = ("tecnologia", "ia", "negocios", "jogos", "esportes", "brasil", "ceara", "checagem")

# Sites conhecidos e sérios (feeds públicos). O dono liga/desliga cada um e pode acrescentar outros.
DEFAULT_SOURCES: list[dict] = [
    {"name": "Tecnoblog", "url": "https://tecnoblog.net/feed/", "category": "tecnologia", "site": "https://tecnoblog.net"},
    {"name": "Canaltech", "url": "https://canaltech.com.br/rss/", "category": "tecnologia", "site": "https://canaltech.com.br"},
    {"name": "Olhar Digital", "url": "https://olhardigital.com.br/feed/", "category": "tecnologia", "site": "https://olhardigital.com.br"},
    {"name": "G1 Tecnologia", "url": "https://g1.globo.com/rss/g1/tecnologia/", "category": "tecnologia", "site": "https://g1.globo.com/tecnologia/"},
    {"name": "The Verge", "url": "https://www.theverge.com/rss/index.xml", "category": "tecnologia", "site": "https://www.theverge.com"},
    {"name": "G1 Economia", "url": "https://g1.globo.com/rss/g1/economia/", "category": "negocios", "site": "https://g1.globo.com/economia/"},
    {"name": "IGN Brasil", "url": "https://br.ign.com/feed.xml", "category": "jogos", "site": "https://br.ign.com"},
    {"name": "ge", "url": "https://ge.globo.com/rss/ge/", "category": "esportes", "site": "https://ge.globo.com"},
    {"name": "G1", "url": "https://g1.globo.com/rss/g1/", "category": "brasil", "site": "https://g1.globo.com"},
    {"name": "G1 Ceará", "url": "https://g1.globo.com/rss/g1/ce/ceara/", "category": "ceara", "site": "https://g1.globo.com/ce/ceara/"},
    {"name": "Agência Lupa", "url": "https://www.agencialupa.org/feed/", "category": "checagem", "site": "https://www.agencialupa.org"},
    {"name": "Aos Fatos", "url": "https://www.aosfatos.org/noticias/feed/", "category": "checagem", "site": "https://www.aosfatos.org"},
]

XML_TYPES = ("application/rss+xml", "application/atom+xml", "application/xml", "text/xml")
MAX_FEED_BYTES = 3_000_000
_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")


class FeedError(ValueError):
    pass


@dataclass
class FeedEntry:
    title: str
    url: str
    published: datetime
    summary: str
    source: str


def clean_text(raw: str, limit: int = 1200) -> str:
    """HTML do feed → texto simples (sem tags), cortado."""
    text = html.unescape(_TAG.sub(" ", raw or ""))
    text = _WS.sub(" ", text).strip()
    return text[:limit]


def _date(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    value = value.strip()
    try:
        d = parsedate_to_datetime(value)  # RSS: "Mon, 16 Nov 2026 10:00:00 -0300"
    except (TypeError, ValueError, IndexError):
        d = None
    if d is None:
        try:
            d = datetime.fromisoformat(value.replace("Z", "+00:00"))  # Atom: ISO 8601
        except ValueError:
            return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc)


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _child_text(el: ET.Element, *names: str) -> str:
    for name in names:  # na ordem pedida (ex.: description antes de content)
        for child in el:
            if _local(child.tag) == name:
                text = "".join(child.itertext()).strip()  # inclui texto dentro de <b>, <p>…
                if text:
                    return text
    return ""


def _atom_link(el: ET.Element) -> str:
    best = ""
    for child in el:
        if _local(child.tag) == "link":
            href = child.attrib.get("href", "")
            if child.attrib.get("rel", "alternate") == "alternate" and href:
                return href
            best = best or href
    return best


def _safe_url(url: str) -> str:
    url = (url or "").strip()
    p = urlsplit(url)
    return url if p.scheme in ("http", "https") and p.netloc else ""


def parse(xml_text: str, source: str, now: Optional[datetime] = None) -> list[FeedEntry]:
    """Lê RSS 2.0 ou Atom. Recusa DOCTYPE/ENTITY (truque que trava o computador)."""
    if len(xml_text) > MAX_FEED_BYTES:
        raise FeedError("Feed grande demais.")
    head = xml_text[:4000].upper()
    if "<!DOCTYPE" in head or "<!ENTITY" in xml_text.upper():
        raise FeedError("Feed com DOCTYPE/ENTITY recusado por segurança.")
    try:
        root = ET.fromstring(xml_text.lstrip("﻿ \n\r\t"))
    except ET.ParseError as exc:
        raise FeedError(f"Feed inválido: {exc}") from exc
    now = now or datetime.now(timezone.utc)
    out: list[FeedEntry] = []
    items = [e for e in root.iter() if _local(e.tag) in ("item", "entry")]
    for it in items[:80]:
        title = clean_text(_child_text(it, "title"), 400)
        url = _safe_url(_child_text(it, "link") or _atom_link(it))
        if not title or not url:
            continue
        when = _date(_child_text(it, "pubdate", "published", "updated", "date")) or now
        if when > now:  # data no futuro: usa a hora em que foi lida
            when = now
        summary = clean_text(_child_text(it, "description", "summary", "content", "encoded"))
        out.append(FeedEntry(title=title, url=url, published=when, summary=summary, source=source))
    return out


def site_name(url: str) -> str:
    host = (urlsplit(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host
