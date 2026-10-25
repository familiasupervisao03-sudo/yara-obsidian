"""Texto legível de uma página HTML (biblioteca padrão; sem executar nada da página)."""

from __future__ import annotations

import re
from html.parser import HTMLParser

SKIP = {"script", "style", "noscript", "template", "svg", "canvas", "iframe", "object",
        "nav", "footer", "header", "aside", "form", "button", "select", "dialog"}
BLOCK = {"p", "div", "section", "article", "main", "li", "tr", "br", "h1", "h2", "h3", "h4",
         "h5", "h6", "pre", "blockquote", "dd", "dt", "figcaption", "table", "ul", "ol"}
VOID = {"br", "img", "hr", "meta", "link", "input", "source", "wbr", "area", "base", "col",
        "embed", "param", "track"}
HIDDEN = re.compile(r"display\s*:\s*none|visibility\s*:\s*hidden", re.I)


class _Extractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.description = ""
        self._in_title = False
        self._skip_stack: list[str] = []
        self._chunks: list[str] = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "meta":
            name = (a.get("name") or a.get("property") or "").lower()
            if name in ("description", "og:description") and not self.description:
                self.description = (a.get("content") or "").strip()
            return
        if tag in VOID:
            if tag == "br":
                self._chunks.append("\n")
            return
        hidden = "hidden" in a or a.get("aria-hidden") == "true" or HIDDEN.search(a.get("style") or "")
        if self._skip_stack or tag in SKIP or hidden:
            self._skip_stack.append(tag)
            return
        if tag == "title":
            self._in_title = True
        if tag in BLOCK:
            self._chunks.append("\n")

    def handle_endtag(self, tag):
        if self._skip_stack:
            # Fecha até a tag correspondente (HTML real nem sempre fecha tudo).
            if tag in self._skip_stack:
                while self._skip_stack and self._skip_stack.pop() != tag:
                    pass
            return
        if tag == "title":
            self._in_title = False
        if tag in BLOCK:
            self._chunks.append("\n")

    def handle_data(self, data):
        if self._in_title and not self._skip_stack:
            self.title += data
            return
        if not self._skip_stack:
            self._chunks.append(data)

    def text(self) -> str:
        raw = "".join(self._chunks)
        lines = [re.sub(r"[ \t\r\f\v ]+", " ", ln).strip() for ln in raw.split("\n")]
        # Linhas muito curtas costumam ser menus e botões soltos.
        kept = [ln for ln in lines if len(ln) >= 25 or (ln and ln[-1:] in ".:!?")]
        return "\n".join(kept)


def extract(html: str, max_chars: int = 6000) -> tuple[str, str]:
    """Devolve (título, texto) limitado a ``max_chars``."""
    p = _Extractor()
    try:
        p.feed(html)
        p.close()
    except Exception:  # HTML muito quebrado: usa o que já foi lido
        pass
    title = re.sub(r"\s+", " ", p.title).strip()[:200]
    body = p.text()
    if not body and p.description:
        body = p.description
    return title, clip(body, max_chars)


def clip(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars]
    end = max(cut.rfind(". "), cut.rfind("\n"))
    return (cut[: end + 1] if end > max_chars * 0.6 else cut).rstrip() + " […]"
