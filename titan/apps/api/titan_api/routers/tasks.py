"""Rotas da Fase 2: tarefas, planos, aprovações, execuções, auditoria e eventos (SSE)."""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session as DBSession
from starlette.concurrency import run_in_threadpool

from titan.db.models import Approval, AuditEvent, Execution, Task, TaskPlan, TaskStep, VerificationResult
from titan.tasks import states as S
from titan.tasks.actions import ACTIONS, CRITERIA_TYPES
from titan.tasks.runner import submit_reply
from titan.tasks.service import (
    TaskError,
    create_task,
    current_steps,
    decide_approval,
    get_task,
    latest_execution,
    request_cancel,
    resume,
    set_plan,
)
from titan_api.deps import AppContext, CurrentUser, current_user, get_ctx, get_db
from titan_api.schemas import ErrorResponse

router = APIRouter(prefix="/api/v1", tags=["tasks"], responses={401: {"model": ErrorResponse}})

ERR = {404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}, 422: {"model": ErrorResponse}}
_STATUS = {"not_found": 404, "invalid": 422, "conflict": 409, "needs_confirmation": 409}


def _error(exc: TaskError) -> JSONResponse:
    code = {"invalid": "validation_error"}.get(exc.code, exc.code)
    return JSONResponse({"error": {"code": code, "message": str(exc)}},
                        status_code=_STATUS.get(exc.code, 409))


# --- contratos ------------------------------------------------------------------

class StepIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    action_type: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    success_criteria: list[dict[str, Any]] = Field(min_length=1, max_length=10)
    requires_approval: bool = False
    depends_on: list[int] = Field(default_factory=list)


class TaskCreateIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=10_000)
    steps: Optional[list[StepIn]] = Field(default=None, max_length=30)


class PlanIn(BaseModel):
    steps: list[StepIn] = Field(min_length=1, max_length=30)
    change_note: str = Field(default="", max_length=1000)


class DecisionIn(BaseModel):
    decision: str = Field(pattern="^(approve|reject)$")
    scope_hash: str = Field(min_length=64, max_length=64)
    reason: str = Field(default="", max_length=1000)


class CancelIn(BaseModel):
    reason: str = Field(default="", max_length=1000)


class ResumeIn(BaseModel):
    retry_uncertain: bool = False


class ReplyIn(BaseModel):
    text: str = Field(min_length=1, max_length=10_000)


class TaskOut(BaseModel):
    id: uuid.UUID
    title: str
    description: str
    status: str
    status_reason: Optional[str]
    plan_version: int
    created_at: datetime
    updated_at: datetime


class StepOut(BaseModel):
    id: uuid.UUID
    position: int
    title: str
    description: str
    action_type: str
    action_label: str
    parameters: dict[str, Any]
    requires_approval: bool
    depends_on: list[int]
    success_criteria: list[dict[str, Any]]
    status: str
    last_output: Optional[str]
    last_error: Optional[str]


class ApprovalOut(BaseModel):
    id: uuid.UUID
    task_id: uuid.UUID
    task_title: str
    step_position: Optional[int]
    step_title: Optional[str]
    plan_version: int
    action_type: str
    action_label: str
    parameters: dict[str, Any]
    risk: str
    scope_hash: str
    status: str
    expires_at: Optional[datetime]
    decided_at: Optional[datetime]
    reason: Optional[str]
    created_at: datetime


class PlanOut(BaseModel):
    version: int
    created_by: str
    change_note: str
    created_at: datetime


class VerificationOut(BaseModel):
    criterion: str
    passed: bool
    details: str
    created_at: datetime


class TaskDetail(BaseModel):
    task: TaskOut
    steps: list[StepOut]
    approvals: list[ApprovalOut]
    plans: list[PlanOut]
    verification: list[VerificationOut]


class TaskList(BaseModel):
    items: list[TaskOut]


class ExecutionOut(BaseModel):
    id: uuid.UUID
    step_id: Optional[uuid.UUID]
    attempt: int
    command: str
    status: str
    output: str
    error: str
    started_at: datetime
    finished_at: Optional[datetime]


class AuditOut(BaseModel):
    id: int
    created_at: datetime
    actor_type: str
    event_type: str
    data: dict[str, Any]


class ActionInfo(BaseModel):
    name: str
    label: str
    sensitive: bool
    risk: str
    required_params: list[str]
    available: bool
    unavailable_reason: str


class CatalogOut(BaseModel):
    actions: list[ActionInfo]
    criteria_types: list[str]


# --- conversões --------------------------------------------------------------------

def _task_out(t: Task) -> TaskOut:
    return TaskOut(id=t.id, title=t.title, description=t.request, status=t.status,
                   status_reason=t.error, plan_version=t.plan_version, created_at=t.created_at,
                   updated_at=t.updated_at)


def _approval_out(db: DBSession, ap: Approval, task: Optional[Task] = None) -> ApprovalOut:
    task = task or db.get(Task, ap.task_id)
    step = db.get(TaskStep, ap.step_id) if ap.step_id else None
    spec = ACTIONS.get(ap.action_type)
    return ApprovalOut(id=ap.id, task_id=ap.task_id, task_title=task.title if task else "",
                       step_position=step.position if step else None,
                       step_title=step.title if step else None, plan_version=ap.plan_version,
                       action_type=ap.action_type, action_label=spec.label if spec else ap.action_type,
                       parameters=ap.parameters, risk=ap.risk, scope_hash=ap.scope_hash,
                       status=ap.status, expires_at=ap.expires_at, decided_at=ap.decided_at,
                       reason=ap.reason, created_at=ap.created_at)


def _detail(db: DBSession, task: Task) -> TaskDetail:
    steps = []
    for s in current_steps(db, task):
        ex = latest_execution(db, s)
        steps.append(StepOut(
            id=s.id, position=s.position, title=s.title, description=s.description,
            action_type=s.action_type, action_label=ACTIONS[s.action_type].label,
            parameters=s.parameters, requires_approval=s.requires_approval,
            depends_on=s.depends_on, success_criteria=s.success_criteria, status=s.status,
            last_output=(ex.stdout_tail or None) if ex else None,
            last_error=(ex.stderr_tail or None) if ex else None))
    approvals = [_approval_out(db, a, task) for a in db.scalars(
        select(Approval).where(Approval.task_id == task.id).order_by(Approval.created_at))]
    plans = [PlanOut(version=p.version, created_by=p.created_by, change_note=p.change_note,
                     created_at=p.created_at) for p in db.scalars(
        select(TaskPlan).where(TaskPlan.task_id == task.id).order_by(TaskPlan.version))]
    verification = [VerificationOut(criterion=v.criterion, passed=v.passed, details=v.details,
                                    created_at=v.created_at) for v in db.scalars(
        select(VerificationResult).where(VerificationResult.task_id == task.id)
        .order_by(VerificationResult.created_at))]
    return TaskDetail(task=_task_out(task), steps=steps, approvals=approvals, plans=plans,
                      verification=verification)


# --- rotas -------------------------------------------------------------------------

@router.get("/tasks/catalog", response_model=CatalogOut)
def catalog(_: CurrentUser = Depends(current_user)) -> CatalogOut:
    return CatalogOut(
        actions=[ActionInfo(name=a.name, label=a.label, sensitive=a.sensitive, risk=a.risk,
                            required_params=list(a.required_params), available=a.available,
                            unavailable_reason=a.unavailable_reason) for a in ACTIONS.values()],
        criteria_types=sorted(CRITERIA_TYPES))


@router.post("/tasks", response_model=TaskDetail, status_code=201, responses=ERR)
def create(body: TaskCreateIn, idempotency_key: Optional[str] = Header(
               default=None, alias="Idempotency-Key", max_length=64),
           cu: CurrentUser = Depends(current_user), db: DBSession = Depends(get_db),
           ctx: AppContext = Depends(get_ctx)):
    try:
        task, duplicate = create_task(
            db, cu.user.id, body.title, body.description,
            [s.model_dump() for s in body.steps] if body.steps else None,
            idempotency_key, ctx.settings.approval_ttl_hours)
    except TaskError as exc:
        db.rollback()
        return _error(exc)
    detail = _detail(db, task)
    return JSONResponse(detail.model_dump(mode="json"), status_code=200 if duplicate else 201)


@router.get("/tasks", response_model=TaskList)
def list_tasks(limit: int = Query(50, ge=1, le=200), cu: CurrentUser = Depends(current_user),
               db: DBSession = Depends(get_db)) -> TaskList:
    rows = db.scalars(select(Task).where(Task.user_id == cu.user.id)
                      .order_by(Task.updated_at.desc()).limit(limit))
    return TaskList(items=[_task_out(t) for t in rows])


@router.get("/tasks/{task_id}", response_model=TaskDetail, responses=ERR)
def get_one(task_id: uuid.UUID, cu: CurrentUser = Depends(current_user),
            db: DBSession = Depends(get_db)):
    try:
        return _detail(db, get_task(db, cu.user.id, task_id))
    except TaskError as exc:
        return _error(exc)


@router.put("/tasks/{task_id}/plan", response_model=TaskDetail, responses=ERR)
def replace_plan(task_id: uuid.UUID, body: PlanIn, cu: CurrentUser = Depends(current_user),
                 db: DBSession = Depends(get_db), ctx: AppContext = Depends(get_ctx)):
    try:
        task = get_task(db, cu.user.id, task_id)
        set_plan(db, task, [s.model_dump() for s in body.steps], created_by="user",
                 actor_id=cu.user.id, change_note=body.change_note or "plano revisado",
                 approval_ttl_hours=ctx.settings.approval_ttl_hours)
    except TaskError as exc:
        db.rollback()
        return _error(exc)
    return _detail(db, task)


@router.post("/tasks/{task_id}/start", response_model=TaskDetail, responses=ERR)
def start(task_id: uuid.UUID, cu: CurrentUser = Depends(current_user),
          db: DBSession = Depends(get_db), ctx: AppContext = Depends(get_ctx)):
    try:
        task = get_task(db, cu.user.id, task_id)
    except TaskError as exc:
        return _error(exc)
    if task.status != S.READY:
        return _error(TaskError(f"A tarefa precisa estar pronta (READY) para iniciar; "
                                f"estado atual: {task.status}."))
    db.commit()
    ctx.runner.start(task.id)
    db.refresh(task)
    return _detail(db, task)


@router.post("/tasks/{task_id}/cancel", response_model=TaskDetail, responses=ERR)
def cancel(task_id: uuid.UUID, body: CancelIn, cu: CurrentUser = Depends(current_user),
           db: DBSession = Depends(get_db)):
    try:
        task = get_task(db, cu.user.id, task_id)
        request_cancel(db, task, cu.user.id, body.reason)
    except TaskError as exc:
        db.rollback()
        return _error(exc)
    return _detail(db, task)


@router.post("/tasks/{task_id}/resume", response_model=TaskDetail, responses=ERR)
def resume_task(task_id: uuid.UUID, body: ResumeIn, cu: CurrentUser = Depends(current_user),
                db: DBSession = Depends(get_db), ctx: AppContext = Depends(get_ctx)):
    try:
        task = get_task(db, cu.user.id, task_id)
        resume(db, task, cu.user.id, body.retry_uncertain, ctx.settings.approval_ttl_hours)
    except TaskError as exc:
        db.rollback()
        return _error(exc)
    db.commit()
    ctx.runner.start(task.id)
    db.refresh(task)
    return _detail(db, task)


@router.post("/tasks/{task_id}/reply", response_model=TaskDetail, responses=ERR)
def reply(task_id: uuid.UUID, body: ReplyIn, cu: CurrentUser = Depends(current_user),
          db: DBSession = Depends(get_db), ctx: AppContext = Depends(get_ctx)):
    try:
        task = get_task(db, cu.user.id, task_id)
        submit_reply(db, task, cu.user.id, body.text)
    except TaskError as exc:
        db.rollback()
        return _error(exc)
    db.commit()
    ctx.runner.start(task.id)
    db.refresh(task)
    return _detail(db, task)


@router.get("/tasks/{task_id}/executions", response_model=list[ExecutionOut], responses=ERR)
def executions(task_id: uuid.UUID, cu: CurrentUser = Depends(current_user),
               db: DBSession = Depends(get_db)):
    try:
        task = get_task(db, cu.user.id, task_id)
    except TaskError as exc:
        return _error(exc)
    rows = db.scalars(select(Execution).where(Execution.task_id == task.id)
                      .order_by(Execution.started_at))
    return [ExecutionOut(id=e.id, step_id=e.step_id, attempt=e.attempt, command=e.command,
                         status=e.status, output=e.stdout_tail, error=e.stderr_tail,
                         started_at=e.started_at, finished_at=e.finished_at) for e in rows]


@router.get("/tasks/{task_id}/audit", response_model=list[AuditOut], responses=ERR)
def task_audit(task_id: uuid.UUID, cu: CurrentUser = Depends(current_user),
               db: DBSession = Depends(get_db)):
    try:
        task = get_task(db, cu.user.id, task_id)
    except TaskError as exc:
        return _error(exc)
    rows = db.scalars(select(AuditEvent).where(AuditEvent.task_id == task.id)
                      .order_by(AuditEvent.id))
    return [AuditOut(id=e.id, created_at=e.created_at, actor_type=e.actor_type,
                     event_type=e.event_type, data=e.data) for e in rows]


@router.get("/tasks/{task_id}/events", responses=ERR)
async def task_events(
    task_id: uuid.UUID,
    request: Request,
    after: Optional[int] = Query(None, ge=0),
    max_seconds: int = Query(300, ge=1, le=3600),
    last_event_id: Optional[str] = Header(default=None, alias="Last-Event-ID"),
    cu: CurrentUser = Depends(current_user),
    ctx: AppContext = Depends(get_ctx),
):
    """Eventos da tarefa (SSE). Reconexões com Last-Event-ID recebem só o que faltou."""
    def owned() -> bool:
        with ctx.session_factory() as db:
            return db.scalar(select(Task.id).where(Task.id == task_id,
                                                   Task.user_id == cu.user.id)) is not None

    if not await run_in_threadpool(owned):
        return _error(TaskError("Tarefa não encontrada.", "not_found"))
    start_id = after
    if last_event_id and last_event_id.isdigit():
        start_id = int(last_event_id)

    def fetch(last: int) -> tuple[list[AuditEvent], str]:
        with ctx.session_factory() as db:
            rows = list(db.scalars(select(AuditEvent).where(
                AuditEvent.task_id == task_id, AuditEvent.id > last).order_by(AuditEvent.id)
                .limit(200)))
            status = db.scalar(select(Task.status).where(Task.id == task_id))
            for r in rows:
                db.expunge(r)
            return rows, status

    async def stream():
        last = start_id or 0
        loop = asyncio.get_running_loop()
        deadline = loop.time() + max_seconds
        idle = 0
        yield "retry: 3000\n\n"
        while loop.time() < deadline:
            if await request.is_disconnected():
                return
            rows, status = await run_in_threadpool(fetch, last)
            for r in rows:
                payload = {"event_type": r.event_type, "actor_type": r.actor_type,
                           "created_at": r.created_at.isoformat(), "data": r.data,
                           "task_status": status}
                yield f"id: {r.id}\nevent: task\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
                last = r.id
            if not rows:
                if status in S.TERMINAL:
                    yield f"event: end\ndata: {json.dumps({'task_status': status})}\n\n"
                    return
                idle += 1
                if idle % 15 == 0:
                    yield ": keepalive\n\n"
            await asyncio.sleep(1.0)

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


@router.get("/approvals", response_model=list[ApprovalOut])
def list_approvals(status: Optional[str] = Query("PENDING", pattern="^(PENDING|APPROVED|REJECTED|INVALIDATED|EXPIRED|ALL)$"),
                   cu: CurrentUser = Depends(current_user), db: DBSession = Depends(get_db)):
    q = select(Approval).join(Task, Task.id == Approval.task_id).where(Task.user_id == cu.user.id)
    if status != "ALL":
        q = q.where(Approval.status == status)
    return [_approval_out(db, a) for a in db.scalars(q.order_by(Approval.created_at.desc()).limit(200))]


@router.post("/approvals/{approval_id}/decision", response_model=TaskDetail, responses=ERR)
def decision(approval_id: uuid.UUID, body: DecisionIn, cu: CurrentUser = Depends(current_user),
             db: DBSession = Depends(get_db)):
    ap = db.get(Approval, approval_id)
    if ap is None:
        return _error(TaskError("Aprovação não encontrada.", "not_found"))
    try:
        task = decide_approval(db, ap, actor_type="user", user_id=cu.user.id,
                               decision=body.decision, echoed_scope_hash=body.scope_hash,
                               reason=body.reason)
    except TaskError as exc:
        db.commit()  # preserva marcações de EXPIRADA/INVALIDADA e a auditoria
        return _error(exc)
    return _detail(db, task)
