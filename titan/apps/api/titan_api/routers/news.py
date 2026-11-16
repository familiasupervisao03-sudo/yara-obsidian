"""Notícias do TITAN: lista, fontes, assuntos seguidos, dicionário e jornal (cada conta vê só o seu).

As notícias vêm dos sites (feeds públicos) com título, data e link reais. Resumos e análises
do TITAN são feitos só com o texto lido e vêm marcados como "do TITAN".
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta
from typing import Literal, Optional
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session as DBSession
from starlette.concurrency import run_in_threadpool

from titan.audit import log as audit
from titan.db.models import NewsFollow, NewsItem, NewsStory, NewsTerm, NewsUserStory, TitanNote, utcnow
from titan.news import feeds, service
from titan.news.group import keywords, similar
from titan_api.deps import AppContext, CurrentUser, current_user, get_ctx, get_db
from titan_api.schemas import ErrorResponse

router = APIRouter(prefix="/api/v1/news", tags=["news"], responses={401: {"model": ErrorResponse}})
NOT_FOUND = {404: {"model": ErrorResponse}}
AI_WORDS = {"ia", "inteligencia", "artificial", "chatgpt", "gemini", "claude", "openai", "llm", "anthropic", "groq"}


def _err(code: int, kind: str, message: str) -> JSONResponse:
    return JSONResponse({"error": {"code": kind, "message": message}}, status_code=code)


class SourceLink(BaseModel):
    name: str
    url: str
    title: str
    published_at: datetime


class Analysis(BaseModel):
    resumo: str = ""
    por_que_importa: str = ""
    afeta_titan: str = ""
    oportunidade: str = ""
    discordam: bool = False
    discordancia: str = ""


class StoryOut(BaseModel):
    id: uuid.UUID
    title: str
    category: str
    first_at: datetime
    last_at: datetime
    sources: list[SourceLink]          # linha do tempo: cada site com a data real
    n_sources: int
    read: bool
    saved: bool
    vote: int
    important: bool
    affects: bool
    analysis: Optional[Analysis] = None
    checks: list[SourceLink] = []      # agências de checagem que falaram do assunto


class NewsList(BaseModel):
    enabled: bool
    stories: list[StoryOut]
    total_items: int


def _story_out(db: DBSession, st: NewsStory, us: Optional[NewsUserStory], checks: list[NewsStory]) -> StoryOut:
    items = service.story_sources(db, st.id)
    words = set(st.words.split())
    chk = []
    for c in checks:
        if similar(words, set(c.words.split())) >= 0.5:
            for it in service.story_sources(db, c.id)[:1]:
                chk.append(SourceLink(name=it.source, url=it.url, title=it.title, published_at=it.published_at))
    analysis = None
    if us and us.analysis:
        try:
            analysis = Analysis(**{k: v for k, v in json.loads(us.analysis).items() if k in Analysis.model_fields})
        except (ValueError, TypeError):
            analysis = None
    return StoryOut(
        id=st.id, title=st.title, category=st.category, first_at=st.first_at, last_at=st.last_at,
        sources=[SourceLink(name=i.source, url=i.url, title=i.title, published_at=i.published_at) for i in items],
        n_sources=len({i.source for i in items}), read=bool(us and us.read), saved=bool(us and us.saved),
        vote=us.vote if us else 0, important=bool(us and us.score >= service.IMPORTANT_SCORE),
        affects=bool(words & service.PROJECT_WORDS), analysis=analysis, checks=chk[:2])


Category = Literal["tudo", "tecnologia", "ia", "negocios", "jogos", "esportes", "brasil", "ceara", "salvas"]


@router.get("", response_model=NewsList)
def list_news(cat: Category = "tudo", limit: int = Query(default=40, ge=1, le=100),
              cu: CurrentUser = Depends(current_user), ctx: AppContext = Depends(get_ctx),
              db: DBSession = Depends(get_db)):
    """Notícias para esta conta: as mais importantes e recentes primeiro (👎 vai para o fim)."""
    now = utcnow()
    q = (select(NewsStory, NewsUserStory).outerjoin(
        NewsUserStory, (NewsUserStory.story_id == NewsStory.id) & (NewsUserStory.user_id == cu.user.id))
        .where(NewsStory.is_checagem.is_(False)))
    if cat == "salvas":
        q = q.where(NewsUserStory.saved.is_(True))
    else:
        q = q.where(NewsStory.last_at >= now - timedelta(hours=72))
        if cat not in ("tudo", "ia"):
            q = q.where(NewsStory.category == cat)
    rows = db.execute(q.order_by(NewsStory.last_at.desc()).limit(400)).all()
    if cat == "ia":
        rows = [r for r in rows if set(r[0].words.split()) & AI_WORDS]

    def rank(r) -> float:
        st, us = r
        hours = max(0.0, (now - service._aware(st.last_at)).total_seconds() / 3600)
        base = (us.score if us else 0.0) - hours / 6
        return base - (50 if us and us.vote < 0 else 0) - (5 if us and us.read else 0)

    rows.sort(key=rank, reverse=True)
    checks = list(db.scalars(select(NewsStory).where(NewsStory.is_checagem.is_(True),
                                                     NewsStory.last_at >= now - timedelta(days=7))))
    total = db.scalar(select(func.count()).select_from(NewsItem)) or 0
    return NewsList(enabled=ctx.settings.news_enabled, total_items=total,
                    stories=[_story_out(db, st, us, checks) for st, us in rows[:limit]])


class StateIn(BaseModel):
    read: Optional[bool] = None
    saved: Optional[bool] = None
    vote: Optional[int] = Field(default=None, ge=-1, le=1)


def _story(db: DBSession, sid: uuid.UUID) -> NewsStory:
    st = db.get(NewsStory, sid)
    if st is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Notícia não encontrada.")
    return st


@router.post("/stories/{sid}/state", response_model=StoryOut, responses=NOT_FOUND)
def set_state(sid: uuid.UUID, body: StateIn, cu: CurrentUser = Depends(current_user),
              db: DBSession = Depends(get_db)):
    """Lida, salva e 👍/👎 (o TITAN aprende o que a conta gosta; o voto mais recente pesa mais)."""
    st = _story(db, sid)
    us = service._user_story(db, cu.user.id, st.id)
    if body.read is not None:
        us.read = body.read
    if body.saved is not None:
        us.saved = body.saved
    if body.vote is not None:
        us.vote = body.vote
    us.updated_at = utcnow()
    db.flush()
    return _story_out(db, st, us, [])


class ExplainIn(BaseModel):
    mode: Literal["melhor", "facil"] = "melhor"


class ExplainOut(BaseModel):
    text: str
    sources: list[SourceLink]


@router.post("/stories/{sid}/explain", response_model=ExplainOut,
             responses={**NOT_FOUND, 503: {"model": ErrorResponse}})
async def explain(sid: uuid.UUID, body: ExplainIn, cu: CurrentUser = Depends(current_user),
                  ctx: AppContext = Depends(get_ctx)):
    """"Explica melhor" / "Me explica fácil": a IA explica usando SÓ o texto dos sites."""
    from titan.brain.service import brain_provider

    def run():
        with ctx.session_factory() as db:
            st = _story(db, sid)
            items = service.story_sources(db, st.id)
            text = service.explain(brain_provider(ctx.settings, ctx.session_factory), db, st, body.mode)
            return text, [SourceLink(name=i.source, url=i.url, title=i.title, published_at=i.published_at)
                          for i in items]

    try:
        text, srcs = await run_in_threadpool(run)
    except HTTPException:
        raise
    except Exception as exc:
        return _err(503, "model_unavailable", f"A IA não está disponível agora ({str(exc)[:120]}). "
                                              "O link do site continua aí para ler.")
    return ExplainOut(text=text, sources=srcs)


# --- fontes ------------------------------------------------------------------------------------

class SourceOut(BaseModel):
    name: str
    url: str
    site: str
    category: str
    enabled: bool
    custom: bool


class SourceSetIn(BaseModel):
    url: str = Field(min_length=8, max_length=1000)
    enabled: bool = True
    name: str = Field(default="", max_length=80)
    category: Literal["tecnologia", "negocios", "jogos", "esportes", "brasil", "ceara", "checagem"] = "tecnologia"


@router.get("/sources", response_model=list[SourceOut])
def get_sources(cu: CurrentUser = Depends(current_user), db: DBSession = Depends(get_db)):
    return [SourceOut(**{k: s[k] for k in SourceOut.model_fields}) for s in service.sources_for(db, cu.user.id)]


@router.put("/sources", response_model=list[SourceOut], responses={422: {"model": ErrorResponse}})
def put_source(body: SourceSetIn, cu: CurrentUser = Depends(current_user), db: DBSession = Depends(get_db)):
    """Liga/desliga uma fonte ou acrescenta um site novo (endereço do feed RSS, em https)."""
    p = urlsplit(body.url.strip())
    if p.scheme != "https" or not p.hostname:
        return _err(422, "validation_error", "Use o endereço do feed começando com https://")
    service.set_source(db, cu.user.id, body.url.strip(), body.enabled, body.name.strip(), body.category)
    audit.record(db, "news.source", actor_type="user", actor_id=cu.user.id, entity_type="news_source",
                 data={"url": body.url[:200], "enabled": body.enabled})
    return get_sources(cu, db)


@router.delete("/sources", response_model=list[SourceOut])
def delete_source(url: str = Query(max_length=1000), cu: CurrentUser = Depends(current_user),
                  db: DBSession = Depends(get_db)):
    service.remove_source(db, cu.user.id, url)
    return get_sources(cu, db)


# --- assuntos seguidos ---------------------------------------------------------------------------

class HitOut(BaseModel):
    title: str
    url: str
    source: str
    published_at: datetime
    price: Optional[float] = None
    quote: str = ""


class FollowOut(BaseModel):
    id: uuid.UUID
    topic: str
    prices: bool
    since: datetime
    until: datetime
    store_url: str
    last_checked_at: Optional[datetime]
    trend: str
    hits: list[HitOut]


class FollowIn(BaseModel):
    topic: str = Field(min_length=2, max_length=120)
    prices: bool = False
    past_weeks: int = Field(default=2, ge=0, le=52)
    future_weeks: int = Field(default=2, ge=0, le=52)
    store_url: str = Field(default="", max_length=1000)


class FollowTextIn(BaseModel):
    text: str = Field(min_length=3, max_length=300)


def _follow_out(db: DBSession, f: NewsFollow) -> FollowOut:
    s = service.follow_summary(db, f)
    return FollowOut(id=f.id, topic=f.topic, prices=f.prices, since=f.since, until=f.until, store_url=f.store_url,
                     last_checked_at=f.last_checked_at, trend=s["trend"],
                     hits=[HitOut(title=h.title, url=h.url.split("#")[0], source=h.source,
                                  published_at=h.published_at, price=h.price, quote=h.quote) for h in s["hits"]])


@router.get("/follows", response_model=list[FollowOut])
def get_follows(cu: CurrentUser = Depends(current_user), db: DBSession = Depends(get_db)):
    rows = db.scalars(select(NewsFollow).where(NewsFollow.user_id == cu.user.id).order_by(NewsFollow.created_at.desc()))
    return [_follow_out(db, f) for f in rows]


@router.post("/follows", response_model=FollowOut, status_code=201, responses={422: {"model": ErrorResponse}})
def add_follow(body: FollowIn, cu: CurrentUser = Depends(current_user), db: DBSession = Depends(get_db)):
    if body.store_url and urlsplit(body.store_url).scheme != "https":
        return _err(422, "validation_error", "O link da loja precisa começar com https://")
    f = service.create_follow(db, cu.user.id, body.topic, body.prices, body.past_weeks, body.future_weeks,
                              body.store_url.strip())
    audit.record(db, "news.follow", actor_type="user", actor_id=cu.user.id, entity_type="news_follow",
                 entity_id=str(f.id), data={"topic": f.topic, "prices": f.prices})
    return _follow_out(db, f)


@router.post("/follows/from-text", response_model=FollowOut, status_code=201, responses={422: {"model": ErrorResponse}})
def add_follow_text(body: FollowTextIn, cu: CurrentUser = Depends(current_user), db: DBSession = Depends(get_db)):
    """"Analisa os preços da ESP32 nas próximas 3 semanas e nas semanas passadas" → assunto seguido."""
    p = service.parse_follow(body.text, utcnow())
    if p is None:
        return _err(422, "validation_error", "Não entendi o assunto. Ex.: \"segue o preço da ESP32 nas próximas 3 semanas\".")
    return add_follow(FollowIn(topic=p["topic"], prices=p["prices"], past_weeks=p["past_weeks"],
                               future_weeks=p["future_weeks"]), cu, db)


@router.delete("/follows/{fid}", status_code=204, responses=NOT_FOUND)
def delete_follow(fid: uuid.UUID, cu: CurrentUser = Depends(current_user), db: DBSession = Depends(get_db)):
    f = db.get(NewsFollow, fid)
    if f is None or f.user_id != cu.user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Assunto não encontrado.")
    db.delete(f)
    return Response(status_code=204)


# --- dicionário, jornal e manchetes ----------------------------------------------------------------

class TermOut(BaseModel):
    term: str
    explanation: str
    created_at: datetime


@router.get("/terms", response_model=list[TermOut])
def get_terms(cu: CurrentUser = Depends(current_user), db: DBSession = Depends(get_db)):
    rows = db.scalars(select(NewsTerm).where(NewsTerm.user_id == cu.user.id).order_by(NewsTerm.term))
    return [TermOut(term=t.term, explanation=t.explanation, created_at=t.created_at) for t in rows]


class JornalOut(BaseModel):
    title: str
    body: str
    created_at: Optional[datetime] = None


@router.get("/jornal", response_model=JornalOut)
def get_jornal(cu: CurrentUser = Depends(current_user), db: DBSession = Depends(get_db)):
    """O último Jornal do TITAN; se ainda não saiu hoje, os destaques de agora."""
    n = db.scalar(select(TitanNote).where(TitanNote.user_id == cu.user.id, TitanNote.kind == "jornal")
                  .order_by(TitanNote.created_at.desc()).limit(1))
    if n is not None and n.created_at >= utcnow() - timedelta(hours=20):
        return JornalOut(title=n.title, body=n.body, created_at=n.created_at)
    body = service.jornal(db, cu.user.id, utcnow()) or "Ainda não há notícias guardadas hoje."
    return JornalOut(title="Destaques de agora", body=body)


class HeadlineOut(BaseModel):
    title: str
    source: str


@router.get("/headlines", response_model=list[HeadlineOut])
def headlines(cu: CurrentUser = Depends(current_user), db: DBSession = Depends(get_db)):
    """Manchetes para a TV (Central): as de maior nota das últimas 24 h."""
    rows = db.execute(select(NewsStory).join(NewsUserStory, NewsUserStory.story_id == NewsStory.id)
                      .where(NewsUserStory.user_id == cu.user.id, NewsStory.is_checagem.is_(False),
                             NewsStory.last_at >= utcnow() - timedelta(hours=24), NewsUserStory.vote >= 0)
                      .order_by(NewsUserStory.score.desc()).limit(6)).scalars().all()
    out = []
    for st in rows:
        items = service.story_sources(db, st.id)
        out.append(HeadlineOut(title=st.title, source=items[-1].source if items else ""))
    return out
