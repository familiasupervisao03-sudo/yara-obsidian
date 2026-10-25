"""Fontes de busca gratuitas.

* ``wikipedia``: API pública da Wikipédia em português (sem chave, sem custo).
* ``searxng``: metabuscador SearXNG rodando NO PRÓPRIO notebook (opcional; o
  usuário instala e informa o endereço em TITAN_WEB_SEARXNG_URL).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from urllib.parse import quote, urlencode, urlsplit

from titan.tools.web.extract import clip
from titan.tools.web.net import Fetcher, WebError

WIKI_API = "https://pt.wikipedia.org/w/api.php"


@dataclass
class Hit:
    title: str
    url: str
    snippet: str = ""
    text: str = ""  # texto já obtido pela própria fonte (ex.: Wikipédia)


def _json(fetcher: Fetcher, url: str) -> dict:
    page = fetcher.get(url, accept="application/json")
    try:
        data = json.loads(page.text())
    except ValueError as exc:
        raise WebError("A busca respondeu em formato inesperado.", "bad_response") from exc
    if not isinstance(data, dict):
        raise WebError("A busca respondeu em formato inesperado.", "bad_response")
    return data


def wikipedia(fetcher: Fetcher, query: str, limit: int = 3, max_chars: int = 5000,
              notes: list[str] | None = None) -> list[Hit]:
    found = _json(fetcher, WIKI_API + "?" + urlencode({
        "action": "query", "list": "search", "srsearch": query, "srlimit": limit,
        "srprop": "", "format": "json", "formatversion": 2}))
    titles = [r.get("title", "") for r in found.get("query", {}).get("search", []) if r.get("title")]
    hits = []
    for i, title in enumerate(titles[:limit]):
        # Artigo inteiro só para o primeiro resultado; dos outros, a introdução.
        params = {"action": "query", "prop": "extracts", "explaintext": 1, "titles": title,
                  "format": "json", "formatversion": 2, "redirects": 1}
        if i:
            params["exintro"] = 1
        try:
            pages = _json(fetcher, WIKI_API + "?" + urlencode(params)).get("query", {}).get("pages", [])
        except WebError as exc:
            if notes is not None:
                notes.append(f"Wikipédia ({title}): {exc}")
            continue
        text = (pages[0].get("extract") or "") if pages else ""
        if not text.strip():
            continue
        real = pages[0].get("title") or title
        hits.append(Hit(title=f"{real} — Wikipédia", text=clip(text.strip(), max_chars),
                        url="https://pt.wikipedia.org/wiki/" + quote(real.replace(" ", "_"))))
    return hits


def searxng(fetcher: Fetcher, base_url: str, query: str, limit: int = 5) -> list[Hit]:
    data = _json(fetcher, base_url.rstrip("/") + "/search?" + urlencode({
        "q": query, "format": "json", "language": "pt-BR", "safesearch": 1}))
    hits, seen = [], set()
    for r in data.get("results", []):
        url = str(r.get("url") or "")
        if urlsplit(url).scheme not in ("http", "https") or url in seen:
            continue
        seen.add(url)
        hits.append(Hit(title=str(r.get("title") or url)[:200], url=url,
                        snippet=clip(str(r.get("content") or ""), 500)))
        if len(hits) >= limit:
            break
    return hits
