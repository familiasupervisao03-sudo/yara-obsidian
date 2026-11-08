"""Sócio: Início, metas, lembretes/tarefas, memória (cérebro), perguntas, resumo 📌 e mensagens."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session as DBSession
from starlette.concurrency import run_in_threadpool

from titan.audit import log as audit
from titan.brain import extract, service, store
from titan.brain import prefs as brain_prefs
from titan.brain.questions import BY_KEY, LABELS, QUESTIONS
from titan.db.models import BrainMemory, Conversation, Goal, Message, TitanNote, Todo, utcnow
from titan.memory import conversations as repo
from titan.models.providers import ModelUnavailable
from titan.policies.model_gate import ProviderBlocked
from titan_api.deps import AppContext, CurrentUser, current_user, get_ctx, get_db
from titan_api.schemas import ErrorResponse

router = APIRouter(prefix="/api/v1/brain", tags=["brain"], responses={401: {"model": ErrorResponse}})
NOT_FOUND = {404: {"model": ErrorResponse}}
Category = Literal["sobre", "gostos", "negocio", "estudos", "resumo", "outros"]


def _err(code: int, kind: str, message: str) -> JSONResponse:
    return JSONResponse({"error": {"code": kind, "message": message}}, status_code=code)


def _404(what: str = "Item") -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, f"{what} não encontrado.")


# --- modelos de saída -----------------------------------------------------------------

class GoalOut(BaseModel):
    id: uuid.UUID
    title: str
    unit: str
    target: float
    current: float
    deadline: Optional[datetime]
    done: bool
    percent: float
    pace: str
    days_left: Optional[int]
    line: str


def goal_out(g: Goal) -> GoalOut:
    return GoalOut(id=g.id, title=g.title, unit=g.unit, target=g.target, current=g.current,
                   deadline=g.deadline, done=g.done, line=store.goal_line(g), **store.goal_progress(g))


class TodoOut(BaseModel):
    id: uuid.UUID
    kind: str
    title: str
    due_at: Optional[datetime]
    done_at: Optional[datetime]
    late: bool
    conversation_id: Optional[uuid.UUID]


def todo_out(t: Todo) -> TodoOut:
    today_start = store.local_now().replace(hour=0, minute=0, second=0, microsecond=0)
    late = t.done_at is None and t.due_at is not None and t.due_at < (utcnow() if t.kind == "lembrete" else today_start)
    return TodoOut(id=t.id, kind=t.kind, title=t.title, due_at=t.due_at, done_at=t.done_at, late=late,
                   conversation_id=t.conversation_id)


class MemoryOut(BaseModel):
    id: uuid.UUID
    category: str
    content: str
    status: str
    origin: str
    topic: Optional[str]
    conversation_id: Optional[uuid.UUID]
    conversation_title: Optional[str]
    replaces: Optional[str]
    created_at: datetime
    updated_at: datetime


def memory_out(db: DBSession, m: BrainMemory) -> MemoryOut:
    title = None
    if m.conversation_id is not None:
        conv = db.get(Conversation, m.conversation_id)
        title = conv.title if conv else None
    replaces = None
    if m.replaces_id is not None:
        old = db.get(BrainMemory, m.replaces_id)
        replaces = old.content if old else None
    return MemoryOut(id=m.id, category=m.category, content=m.content, status=m.status, origin=m.origin,
                     topic=m.topic, conversation_id=m.conversation_id, conversation_title=title,
                     replaces=replaces, created_at=m.created_at, updated_at=m.updated_at)


class ContinueOut(BaseModel):
    conversation_id: uuid.UUID
    title: str
    last_role: str
    last_text: str
    updated_at: datetime
    origin: str


class HomeOut(BaseModel):
    greeting: str
    now: datetime
    continue_conversation: Optional[ContinueOut]
    goals: list[GoalOut]
    today: list[TodoOut]
    open_todos: int
    pending_memories: int
    memory_total: int = 0


# --- Início ---------------------------------------------------------------------------

@router.get("/home", response_model=HomeOut)
def home(cu: CurrentUser = Depends(current_user), db: DBSession = Depends(get_db)) -> HomeOut:
    now = store.local_now()
    counts = store.counts(db, cu.user.id)
    greeting = "Bom dia" if 5 <= now.hour < 12 else "Boa tarde" if now.hour < 18 else "Boa noite"
    cont = None
    conv = db.scalar(select(Conversation).where(Conversation.user_id == cu.user.id,
                                                Conversation.archived.is_(False))
                     .order_by(Conversation.updated_at.desc()).limit(1))
    if conv is not None:
        last = db.scalar(select(Message).where(Message.conversation_id == conv.id)
                         .order_by(Message.created_at.desc()).limit(1))
        if last is not None:
            cont = ContinueOut(conversation_id=conv.id, title=conv.title, last_role=last.role,
                               last_text=" ".join(last.content.split())[:140], updated_at=conv.updated_at,
                               origin=conv.origin)
    return HomeOut(greeting=greeting, now=now, continue_conversation=cont,
                   goals=[goal_out(g) for g in store.active_goals(db, cu.user.id)],
                   today=[todo_out(t) for t in store.today_todos(db, cu.user.id)],
                   open_todos=len(store.list_todos(db, cu.user.id)),
                   pending_memories=counts["pending"], memory_total=counts["total"])


# --- metas ----------------------------------------------------------------------------

class GoalIn(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    unit: str = Field(default="", max_length=24)
    target: float = Field(default=0, ge=0, le=1e9)
    deadline: Optional[datetime] = None


class GoalPatch(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=160)
    unit: Optional[str] = Field(default=None, max_length=24)
    target: Optional[float] = Field(default=None, ge=0, le=1e9)
    current: Optional[float] = Field(default=None, ge=0, le=1e9)
    add: Optional[float] = Field(default=None, ge=-1e9, le=1e9, description="soma ao progresso atual")
    deadline: Optional[datetime] = None
    clear_deadline: bool = False
    done: Optional[bool] = None


@router.get("/goals", response_model=list[GoalOut])
def goals(all: bool = False, cu: CurrentUser = Depends(current_user), db: DBSession = Depends(get_db)):
    stmt = select(Goal).where(Goal.user_id == cu.user.id)
    if not all:
        stmt = stmt.where(Goal.done.is_(False))
    return [goal_out(g) for g in db.scalars(stmt.order_by(Goal.created_at))]


def _aware(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is not None and dt.tzinfo is None:
        dt = dt.replace(tzinfo=store.local_now().tzinfo)
    return dt


@router.post("/goals", response_model=GoalOut, status_code=201, responses={422: {"model": ErrorResponse}})
def create_goal(body: GoalIn, cu: CurrentUser = Depends(current_user), db: DBSession = Depends(get_db)):
    try:
        g = store.add_goal(db, cu.user.id, body.title, body.unit, body.target, _aware(body.deadline))
    except store.MemoryRefused as exc:
        return _err(422, "sensitive", str(exc))
    audit.record(db, "goal.created", actor_type="user", actor_id=cu.user.id, entity_type="goal", entity_id=str(g.id))
    return goal_out(g)


@router.patch("/goals/{goal_id}", response_model=GoalOut, responses=NOT_FOUND)
def update_goal(goal_id: uuid.UUID, body: GoalPatch, cu: CurrentUser = Depends(current_user),
                db: DBSession = Depends(get_db)):
    g = store.get_goal(db, cu.user.id, goal_id)
    if g is None:
        raise _404("Meta")
    if body.title is not None:
        g.title = " ".join(body.title.split())[:160]
    if body.unit is not None:
        g.unit = " ".join(body.unit.split())[:24]
    if body.target is not None:
        g.target = body.target
    if body.current is not None:
        g.current = body.current
    if body.add is not None:
        g.current = max(0.0, g.current + body.add)
    if body.clear_deadline:
        g.deadline = None
    elif body.deadline is not None:
        g.deadline = _aware(body.deadline)
    if body.done is not None:
        g.done = body.done
    g.updated_at = utcnow()
    db.flush()
    return goal_out(g)


@router.delete("/goals/{goal_id}", status_code=204, responses=NOT_FOUND)
def delete_goal(goal_id: uuid.UUID, cu: CurrentUser = Depends(current_user), db: DBSession = Depends(get_db)):
    g = store.get_goal(db, cu.user.id, goal_id)
    if g is None:
        raise _404("Meta")
    db.delete(g)
    return Response(status_code=204)


# --- lembretes e tarefas --------------------------------------------------------------

class TodoIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    kind: Literal["lembrete", "tarefa"] = "tarefa"
    due_at: Optional[datetime] = None


class TodoPatch(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=200)
    due_at: Optional[datetime] = None
    clear_due: bool = False
    done: Optional[bool] = None
    snooze_minutes: Optional[int] = Field(default=None, ge=1, le=7 * 24 * 60)


@router.get("/todos", response_model=list[TodoOut])
def todos(all: bool = False, conversation_id: Optional[uuid.UUID] = None,
          cu: CurrentUser = Depends(current_user), db: DBSession = Depends(get_db)):
    return [todo_out(t) for t in store.list_todos(db, cu.user.id, include_done=all,
                                                  conversation_id=conversation_id)]


@router.post("/todos", response_model=TodoOut, status_code=201)
def create_todo(body: TodoIn, cu: CurrentUser = Depends(current_user), db: DBSession = Depends(get_db)):
    return todo_out(store.add_todo(db, cu.user.id, body.title, body.kind, _aware(body.due_at)))


@router.patch("/todos/{todo_id}", response_model=TodoOut, responses=NOT_FOUND)
def update_todo(todo_id: uuid.UUID, body: TodoPatch, cu: CurrentUser = Depends(current_user),
                db: DBSession = Depends(get_db)):
    t = store.get_todo(db, cu.user.id, todo_id)
    if t is None:
        raise _404("Lembrete ou tarefa")
    if body.title is not None:
        t.title = " ".join(body.title.split())[:200]
    if body.clear_due:
        t.due_at, t.kind = None, "tarefa"
    elif body.due_at is not None:
        t.due_at, t.notified_at = _aware(body.due_at), None
    if body.snooze_minutes is not None:
        t.due_at = max(utcnow(), t.due_at or utcnow()) + timedelta(minutes=body.snooze_minutes)
        t.notified_at = None
    if body.done is not None:
        t.done_at = utcnow() if body.done else None
    t.updated_at = utcnow()
    db.flush()
    return todo_out(t)


@router.delete("/todos/{todo_id}", status_code=204, responses=NOT_FOUND)
def delete_todo(todo_id: uuid.UUID, cu: CurrentUser = Depends(current_user), db: DBSession = Depends(get_db)):
    t = store.get_todo(db, cu.user.id, todo_id)
    if t is None:
        raise _404("Lembrete ou tarefa")
    db.delete(t)
    return Response(status_code=204)


class ReminderOut(BaseModel):
    id: uuid.UUID
    title: str
    due_at: datetime


@router.get("/reminders/upcoming", response_model=list[ReminderOut])
def upcoming(cu: CurrentUser = Depends(current_user), db: DBSession = Depends(get_db)):
    """Lembretes dos próximos 7 dias: o app do celular agenda os avisos no próprio aparelho."""
    limit = utcnow() + timedelta(days=7)
    return [ReminderOut(id=t.id, title=t.title, due_at=t.due_at)
            for t in store.list_todos(db, cu.user.id)
            if t.kind == "lembrete" and t.due_at is not None and utcnow() - timedelta(minutes=1) <= t.due_at <= limit]


# --- memória --------------------------------------------------------------------------

class MemoryList(BaseModel):
    items: list[MemoryOut]
    counts: dict[str, int]


class MemoryIn(BaseModel):
    content: str = Field(min_length=1, max_length=300)
    category: Category = "outros"


class MemoryPatch(BaseModel):
    content: Optional[str] = Field(default=None, min_length=1, max_length=300)
    category: Optional[Category] = None
    status: Optional[Literal["active", "archived"]] = None
    topic: Optional[Literal["open", "resolved", "none"]] = None


@router.get("/memories", response_model=MemoryList)
def memories(q: str = Query("", max_length=100), category: str = Query("", max_length=16),
             status_: str = Query("", alias="status", max_length=16),
             cu: CurrentUser = Depends(current_user), db: DBSession = Depends(get_db)):
    store.archive_stale(db, cu.user.id)
    rows = store.list_memories(db, cu.user.id, q=q, category=category, status=status_)
    return MemoryList(items=[memory_out(db, m) for m in rows[:500]], counts=store.counts(db, cu.user.id))


@router.post("/memories", response_model=MemoryOut, status_code=201, responses={422: {"model": ErrorResponse}})
def add_memory(body: MemoryIn, cu: CurrentUser = Depends(current_user), db: DBSession = Depends(get_db)):
    try:
        m = store.add_memory(db, cu.user.id, body.content, body.category, status="active", origin="voce")
    except store.MemoryRefused as exc:
        return _err(422, "sensitive", str(exc))
    audit.record(db, "memory.added", actor_type="user", actor_id=cu.user.id, entity_type="memory",
                 entity_id=str(m.id), data={"category": m.category})
    return memory_out(db, m)


@router.patch("/memories/{memory_id}", response_model=MemoryOut, responses={**NOT_FOUND, 422: {"model": ErrorResponse}})
def edit_memory(memory_id: uuid.UUID, body: MemoryPatch, cu: CurrentUser = Depends(current_user),
                db: DBSession = Depends(get_db)):
    m = store.get_memory(db, cu.user.id, memory_id)
    if m is None:
        raise _404("Lembrança")
    try:
        topic = "__keep__" if body.topic is None else (None if body.topic == "none" else body.topic)
        store.update_memory(db, m, content=body.content, category=body.category, status=body.status, topic=topic)
    except store.MemoryRefused as exc:
        return _err(422, "sensitive", str(exc))
    return memory_out(db, m)


@router.post("/memories/{memory_id}/approve", response_model=MemoryOut, responses=NOT_FOUND)
def approve_memory(memory_id: uuid.UUID, cu: CurrentUser = Depends(current_user), db: DBSession = Depends(get_db)):
    m = store.get_memory(db, cu.user.id, memory_id)
    if m is None:
        raise _404("Lembrança")
    m.status, m.updated_at = "active", utcnow()
    if m.replaces_id is not None:
        old = store.get_memory(db, cu.user.id, m.replaces_id)
        if old is not None:
            old.status = "archived"
    audit.record(db, "memory.approved", actor_type="user", actor_id=cu.user.id, entity_type="memory",
                 entity_id=str(m.id), data={"category": m.category})
    db.flush()
    return memory_out(db, m)


@router.delete("/memories/{memory_id}", status_code=204, responses=NOT_FOUND)
def delete_memory(memory_id: uuid.UUID, cu: CurrentUser = Depends(current_user), db: DBSession = Depends(get_db)):
    m = store.get_memory(db, cu.user.id, memory_id)
    if m is None:
        raise _404("Lembrança")
    db.delete(m)
    audit.record(db, "memory.deleted", actor_type="user", actor_id=cu.user.id, entity_type="memory",
                 entity_id=str(memory_id))
    return Response(status_code=204)


class EraseIn(BaseModel):
    confirm: Literal["APAGAR"]


@router.post("/memories/erase", status_code=204)
def erase_memories(body: EraseIn, cu: CurrentUser = Depends(current_user), db: DBSession = Depends(get_db)):
    """Apaga TODAS as lembranças (pede a palavra APAGAR)."""
    n = 0
    for m in db.scalars(select(BrainMemory).where(BrainMemory.user_id == cu.user.id)):
        db.delete(m)
        n += 1
    audit.record(db, "memory.erased", actor_type="user", actor_id=cu.user.id, entity_type="memory",
                 data={"count": n})
    return Response(status_code=204)


# --- "Me conta de você" ---------------------------------------------------------------

class QuestionOut(BaseModel):
    key: str
    category: str
    question: str
    options: list[str]
    answered: int
    total: int


class AnswerIn(BaseModel):
    answer: str = Field(min_length=1, max_length=200)


def _answered(db: DBSession, user_id: uuid.UUID) -> set[str]:
    return {k for k in db.scalars(select(BrainMemory.question_key).where(
        BrainMemory.user_id == user_id, BrainMemory.question_key.is_not(None)))}


@router.get("/questions/next", response_model=Optional[QuestionOut])
def next_question(cu: CurrentUser = Depends(current_user), db: DBSession = Depends(get_db)):
    done = _answered(db, cu.user.id)
    skipped = set(brain_prefs.get(db, cu.user.id)["skipped_questions"])
    for key, cat, q, opts in QUESTIONS:
        if key not in done and key not in skipped:
            return QuestionOut(key=key, category=cat, question=q, options=opts, answered=len(done), total=len(QUESTIONS))
    return None


@router.post("/questions/{key}/answer", response_model=MemoryOut, status_code=201, responses={**NOT_FOUND, 422: {"model": ErrorResponse}})
def answer_question(key: str, body: AnswerIn, cu: CurrentUser = Depends(current_user), db: DBSession = Depends(get_db)):
    if key not in BY_KEY:
        raise _404("Pergunta")
    cat, q, _ = BY_KEY[key]
    answer = " ".join(body.answer.split()).rstrip(".")
    label = LABELS.get(key) or q.rstrip("?").split(":")[0]
    try:
        m = store.add_memory(db, cu.user.id, f"{label}: {answer}", cat, status="active", origin="pergunta",
                             question_key=key)
    except store.MemoryRefused as exc:
        return _err(422, "sensitive", str(exc))
    return memory_out(db, m)


@router.post("/questions/{key}/skip", status_code=204, responses=NOT_FOUND)
def skip_question(key: str, cu: CurrentUser = Depends(current_user), db: DBSession = Depends(get_db)):
    if key not in BY_KEY:
        raise _404("Pergunta")
    p = brain_prefs.get(db, cu.user.id)
    brain_prefs.save(db, cu.user.id, {"skipped_questions": p["skipped_questions"] + [key]})
    return Response(status_code=204)


# --- resumo 📌 e ações da conversa ---------------------------------------------------

@router.post("/conversations/{conversation_id}/summary", response_model=MemoryOut,
             responses={**NOT_FOUND, 503: {"model": ErrorResponse}})
async def summarize(conversation_id: uuid.UUID, cu: CurrentUser = Depends(current_user),
                    ctx: AppContext = Depends(get_ctx)):
    try:
        m = await run_in_threadpool(service.summarize_conversation, ctx.settings, ctx.session_factory,
                                    cu.user.id, conversation_id)
    except KeyError:
        return _err(404, "not_found", "Conversa não encontrada.")
    except ValueError as exc:
        return _err(422, "empty", str(exc))
    except (ModelUnavailable, ProviderBlocked) as exc:
        return _err(503, "model_unavailable", f"Sem IA para resumir agora: {exc}")
    with ctx.session_factory.begin() as db:
        audit.record(db, "memory.summary", actor_type="user", actor_id=cu.user.id, entity_type="conversation",
                     entity_id=str(conversation_id))
        return memory_out(db, db.merge(m))


@router.get("/conversations/{conversation_id}/actions", response_model=dict[str, list[dict]], responses=NOT_FOUND)
def conversation_actions(conversation_id: uuid.UUID, cu: CurrentUser = Depends(current_user),
                         db: DBSession = Depends(get_db)):
    conv = repo.get_conversation(db, cu.user.id, conversation_id)
    if conv is None:
        raise _404("Conversa")
    ids = [str(i) for i in db.scalars(select(Message.id).where(Message.conversation_id == conv.id,
                                                               Message.role == "user"))]
    return extract.actions_for(db, cu.user.id, ids)


# --- mensagens do TITAN ---------------------------------------------------------------

class NoteOut(BaseModel):
    id: uuid.UUID
    kind: str
    title: str
    body: str
    conversation_id: Optional[uuid.UUID]
    todo_id: Optional[uuid.UUID]
    created_at: datetime
    delivered: bool


class DeliveredIn(BaseModel):
    ids: list[uuid.UUID] = Field(max_length=100)
    # aparelho que mostrou (cada um tem a sua cópia); everywhere=true também marca a entrega geral
    # (usado pelo app Android, para o aviso em segundo plano não repetir no mesmo celular)
    device: str = Field(default="", max_length=40, pattern=r"^[A-Za-z0-9_\-]*$")
    everywhere: bool = False


@router.get("/notes", response_model=list[NoteOut])
def notes(pending: bool = True, device: str = Query(default="", max_length=40, pattern=r"^[A-Za-z0-9_\-]*$"),
          cu: CurrentUser = Depends(current_user), db: DBSession = Depends(get_db)):
    """Mensagens ainda não mostradas. Com ``device``, cada aparelho tem a sua lista (o notebook
    mostrar não "gasta" a mensagem do celular). Sem ``device`` (app Android antigo, em segundo
    plano), vale a entrega geral."""
    stmt = select(TitanNote).where(TitanNote.user_id == cu.user.id)
    if pending and device:
        stmt = stmt.where(~TitanNote.delivered_to.contains(f",{device},"),
                          TitanNote.created_at >= utcnow() - timedelta(hours=12))
    elif pending:
        stmt = stmt.where(TitanNote.delivered_at.is_(None),
                          TitanNote.created_at >= utcnow() - timedelta(days=2))
    rows = db.scalars(stmt.order_by(TitanNote.created_at.desc()).limit(50))
    return [NoteOut(id=n.id, kind=n.kind, title=n.title, body=n.body, conversation_id=n.conversation_id,
                    todo_id=n.todo_id, created_at=n.created_at, delivered=n.delivered_at is not None) for n in rows]


@router.post("/notes/delivered", status_code=204)
def notes_delivered(body: DeliveredIn, cu: CurrentUser = Depends(current_user), db: DBSession = Depends(get_db)):
    for n in db.scalars(select(TitanNote).where(TitanNote.user_id == cu.user.id, TitanNote.id.in_(body.ids))):
        if body.device:
            seen = [d for d in (n.delivered_to or "").strip(",").split(",") if d]
            if body.device not in seen:
                seen = (seen + [body.device])[-12:]
                n.delivered_to = "," + ",".join(seen) + ","
        if not body.device or body.everywhere:
            n.delivered_at = n.delivered_at or utcnow()
    return Response(status_code=204)


class BrainPrefsIO(BaseModel):
    auto_save: bool = False
    bom_dia: str = Field(default="07:00", pattern=r"^$|^([01]\d|2[0-3]):[0-5]\d$")
    boa_noite: str = Field(default="21:30", pattern=r"^$|^([01]\d|2[0-3]):[0-5]\d$")
    papo: bool = True
    papo_max: int = Field(default=1, ge=0, le=3)
    socio_semana: bool = True
    acompanhar: bool = True
    silencio_inicio: str = Field(default="22:00", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    silencio_fim: str = Field(default="07:00", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")


@router.get("/prefs", response_model=BrainPrefsIO)
def get_prefs(cu: CurrentUser = Depends(current_user), db: DBSession = Depends(get_db)):
    return BrainPrefsIO(**{k: v for k, v in brain_prefs.get(db, cu.user.id).items() if k in BrainPrefsIO.model_fields})


@router.put("/prefs", response_model=BrainPrefsIO, responses={422: {"model": ErrorResponse}})
def put_prefs(body: BrainPrefsIO, cu: CurrentUser = Depends(current_user), db: DBSession = Depends(get_db)):
    try:
        saved = brain_prefs.save(db, cu.user.id, body.model_dump())
    except brain_prefs.PrefsError as exc:
        return _err(422, "validation_error", str(exc))
    audit.record(db, "brain.prefs", actor_type="user", actor_id=cu.user.id, entity_type="preferences",
                 data={k: saved[k] for k in BrainPrefsIO.model_fields})
    return BrainPrefsIO(**{k: v for k, v in saved.items() if k in BrainPrefsIO.model_fields})
