"""Regras de negócio das tarefas: criação, planos, aprovações, cancelamento e retomada.

Todas as funções recebem uma sessão do banco; quem chama encerra a transação.
Toda mudança de estado é gravada em ``audit_events`` (com ``task_id``), o que
também alimenta o fluxo de eventos em tempo real (SSE).
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timedelta
from typing import Any, Optional

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DBSession

from titan.audit import log as audit
from titan.db.models import Approval, Execution, Task, TaskPlan, TaskStep, utcnow
from titan.tasks import states as S
from titan.tasks.actions import ACTIONS, PlanValidationError, validate_step


class TaskError(Exception):
    def __init__(self, message: str, code: str = "conflict") -> None:
        super().__init__(message)
        self.code = code  # conflict | invalid | not_found | needs_confirmation | duplicate


def _canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def scope_hash(task_id: uuid.UUID, version: int, position: int, action_type: str,
               parameters: dict[str, Any]) -> str:
    """Vincula a aprovação à tarefa, à versão do plano, à etapa, à ação e aos parâmetros."""
    payload = {"task": str(task_id), "version": version, "position": position,
               "action": action_type, "parameters": parameters}
    return hashlib.sha256(_canonical(payload).encode()).hexdigest()


def plan_hash(steps: list[dict[str, Any]]) -> str:
    material = [{k: s.get(k) for k in ("title", "action_type", "parameters", "success_criteria",
                                       "requires_approval", "depends_on")} for s in steps]
    return hashlib.sha256(_canonical(material).encode()).hexdigest()


# --- estados ------------------------------------------------------------------

def transition(db: DBSession, task: Task, new: str, *, reason: str = "",
               actor_type: str = "system", actor_id: Optional[uuid.UUID] = None) -> None:
    """Troca o estado com verificação da máquina de estados e concorrência otimista."""
    current = task.status
    if not S.can_transition(current, new):
        raise TaskError(f"Transição inválida: {current} → {new}.")
    result = db.execute(
        update(Task)
        .where(Task.id == task.id, Task.status == current)
        .values(status=new, error=reason or None, updated_at=utcnow())
    )
    if result.rowcount != 1:
        db.refresh(task)
        raise TaskError(f"A tarefa mudou de estado durante a operação (agora {task.status}).")
    db.refresh(task)
    audit.record(db, "task.state", actor_type=actor_type, actor_id=actor_id, task_id=task.id,
                 entity_type="task", entity_id=str(task.id),
                 data={"from": current, "to": new, "reason": reason})


def get_task(db: DBSession, user_id: uuid.UUID, task_id: uuid.UUID) -> Task:
    task = db.scalar(select(Task).where(Task.id == task_id, Task.user_id == user_id))
    if task is None:
        raise TaskError("Tarefa não encontrada.", "not_found")
    return task


def list_tasks(db: DBSession, user_id: uuid.UUID, limit: int = 50) -> list[Task]:
    """Tarefas do usuário, mais recentes primeiro. Nunca inclui tarefas de outros."""
    return list(db.scalars(select(Task).where(Task.user_id == user_id)
                           .order_by(Task.updated_at.desc()).limit(limit)))


def find_by_idempotency_key(db: DBSession, user_id: uuid.UUID, key: str) -> Optional[Task]:
    return db.scalar(select(Task).where(Task.user_id == user_id, Task.idempotency_key == key))


def current_steps(db: DBSession, task: Task) -> list[TaskStep]:
    return list(db.scalars(
        select(TaskStep)
        .where(TaskStep.task_id == task.id, TaskStep.plan_version == task.plan_version)
        .order_by(TaskStep.position)
    ))


def latest_execution(db: DBSession, step: TaskStep) -> Optional[Execution]:
    return db.scalar(
        select(Execution).where(Execution.step_id == step.id)
        .order_by(Execution.attempt.desc()).limit(1)
    )


# --- criação e planos -----------------------------------------------------------

def create_task(db: DBSession, user_id: uuid.UUID, title: str, description: str,
                steps: Optional[list[dict[str, Any]]], idempotency_key: Optional[str],
                approval_ttl_hours: int) -> tuple[Task, bool]:
    """Cria a tarefa do usuário. Com ``idempotency_key``, um reenvio devolve a original.

    Se outro pedido com a mesma chave gravar entre a consulta e a inserção
    (corrida), a restrição ``uq_tasks_idempotency`` dispara e é levantado
    ``TaskError(code="duplicate")``. Nada desta chamada fica gravado; quem chama
    desfaz a transação e busca a original com ``find_by_idempotency_key``.
    (Não se usa savepoint: com o driver SQLite atual, liberar um savepoint
    efetiva a escrita e quebraria a atomicidade da transação externa.)
    """
    if idempotency_key:
        existing = find_by_idempotency_key(db, user_id, idempotency_key)
        if existing is not None:
            return existing, True
    task = Task(user_id=user_id, title=title, request=description, status=S.RECEIVED,
                plan_version=0, idempotency_key=idempotency_key)
    db.add(task)
    try:
        db.flush()
    except IntegrityError as exc:
        if not idempotency_key:
            raise
        raise TaskError("Já existe uma tarefa com esta chave de idempotência.",
                        "duplicate") from exc
    audit.record(db, "task.created", actor_type="user", actor_id=user_id, task_id=task.id,
                 entity_type="task", entity_id=str(task.id),
                 data={"title": title, "description_length": len(description)})
    if steps:
        set_plan(db, task, steps, created_by="user", actor_id=user_id,
                 change_note="plano inicial", approval_ttl_hours=approval_ttl_hours)
    else:
        transition(db, task, S.PLANNING, reason="aguardando plano", actor_type="user",
                   actor_id=user_id)
    return task, False


def set_plan(db: DBSession, task: Task, steps: list[dict[str, Any]], *, created_by: str,
             actor_id: Optional[uuid.UUID], change_note: str, approval_ttl_hours: int) -> TaskPlan:
    """Cria uma NOVA versão do plano. Versões anteriores e suas etapas não são alteradas."""
    if task.status not in S.PLAN_EDITABLE:
        raise TaskError(f"O plano não pode ser alterado no estado {task.status}. "
                        "Cancele a execução primeiro.")
    if not steps:
        raise TaskError("O plano precisa de ao menos uma etapa.", "invalid")
    if len(steps) > 30:
        raise TaskError("Plano muito longo (máximo 30 etapas).", "invalid")
    normalized: list[dict[str, Any]] = []
    for i, raw in enumerate(steps, start=1):
        step = {
            "title": str(raw.get("title") or "").strip()[:200],
            "description": str(raw.get("description") or "")[:2000],
            "action_type": raw.get("action_type"),
            "parameters": raw.get("parameters") or {},
            "success_criteria": raw.get("success_criteria") or [],
            "requires_approval": bool(raw.get("requires_approval", False)),
            "depends_on": [int(d) for d in (raw.get("depends_on") or [])],
        }
        if not step["title"]:
            raise TaskError(f"Etapa {i} sem título.", "invalid")
        try:
            validate_step(step)
        except PlanValidationError as exc:
            raise TaskError(str(exc), "invalid") from exc
        for d in step["depends_on"]:
            if not 1 <= d < i:
                raise TaskError(f"Etapa {i}: dependência {d} inválida (só etapas anteriores).",
                                "invalid")
        # Ação sensível exige aprovação sempre, mesmo que o plano diga o contrário.
        if ACTIONS[step["action_type"]].sensitive:
            step["requires_approval"] = True
        normalized.append(step)

    new_hash = plan_hash(normalized)
    if task.plan_version:
        prev = db.scalar(select(TaskPlan).where(TaskPlan.task_id == task.id,
                                                TaskPlan.version == task.plan_version))
        if prev is not None and prev.plan_hash == new_hash:
            raise TaskError("O novo plano é idêntico à versão atual.", "invalid")

    version = task.plan_version + 1
    plan = TaskPlan(task_id=task.id, version=version, created_by=created_by,
                    change_note=change_note[:1000], plan_hash=new_hash)
    db.add(plan)
    db.execute(update(Task).where(Task.id == task.id).values(plan_version=version,
                                                            updated_at=utcnow()))
    db.refresh(task)

    # Aprovações de versões anteriores deixam de valer (estão vinculadas à versão).
    old = db.scalars(select(Approval).where(Approval.task_id == task.id,
                                            Approval.plan_version < version,
                                            Approval.status.in_(("PENDING", "APPROVED"))))
    for ap in old:
        ap.status = "INVALIDATED"
        ap.reason = f"Plano alterado para a versão {version}."
        audit.record(db, "approval.invalidated", task_id=task.id, entity_type="approval",
                     entity_id=str(ap.id), data={"plan_version": ap.plan_version,
                                                 "new_version": version})

    pending = 0
    now = utcnow()
    for pos, step in enumerate(normalized, start=1):
        row = TaskStep(task_id=task.id, plan_version=version, position=pos, title=step["title"],
                       description=step["description"], action_type=step["action_type"],
                       parameters=step["parameters"], requires_approval=step["requires_approval"],
                       depends_on=step["depends_on"], success_criteria=step["success_criteria"],
                       status="PENDING")
        db.add(row)
        db.flush()
        if step["requires_approval"]:
            _request_approval(db, task, row, now, approval_ttl_hours)
            pending += 1

    audit.record(db, "plan.created", actor_type="user" if created_by == "user" else "model",
                 actor_id=actor_id if created_by == "user" else None, task_id=task.id,
                 entity_type="plan", entity_id=str(plan.id),
                 data={"version": version, "change_note": change_note, "plan_hash": new_hash,
                       "steps": [{"position": i + 1, "title": s["title"],
                                  "action": s["action_type"], "parameters": s["parameters"],
                                  "criteria": s["success_criteria"],
                                  "requires_approval": s["requires_approval"]}
                                 for i, s in enumerate(normalized)]})
    target = S.PENDING_APPROVAL if pending else S.READY
    transition(db, task, target, reason=f"plano v{version} definido",
               actor_type="user" if created_by == "user" else "model",
               actor_id=actor_id if created_by == "user" else None)
    return plan


def _request_approval(db: DBSession, task: Task, step: TaskStep, now: datetime,
                      ttl_hours: int) -> Approval:
    spec = ACTIONS[step.action_type]
    ap = Approval(task_id=task.id, step_id=step.id, plan_version=step.plan_version,
                  action_type=step.action_type, parameters=step.parameters,
                  scope_hash=scope_hash(task.id, step.plan_version, step.position,
                                        step.action_type, step.parameters),
                  status="PENDING", risk=spec.risk,
                  expires_at=now + timedelta(hours=ttl_hours))
    db.add(ap)
    db.flush()
    audit.record(db, "approval.requested", task_id=task.id, entity_type="approval",
                 entity_id=str(ap.id), data={"step": step.position, "action": step.action_type,
                                             "plan_version": step.plan_version})
    return ap


# --- aprovações -------------------------------------------------------------------

def decide_approval(db: DBSession, approval: Approval, *, actor_type: str,
                    user_id: Optional[uuid.UUID], decision: str, echoed_scope_hash: str,
                    reason: str) -> Task:
    """Decisão humana. O modelo (ou qualquer ator não humano) nunca pode decidir."""
    if actor_type != "user" or user_id is None:
        raise TaskError("Somente um usuário autenticado pode decidir aprovações.", "invalid")
    if decision not in ("approve", "reject"):
        raise TaskError("Decisão deve ser 'approve' ou 'reject'.", "invalid")
    task = db.get(Task, approval.task_id)
    if task is None or task.user_id != user_id:
        raise TaskError("Aprovação não encontrada.", "not_found")
    if approval.status != "PENDING":
        raise TaskError(f"Esta aprovação não está pendente (estado {approval.status}).")
    now = utcnow()
    if approval.plan_version != task.plan_version:
        approval.status = "INVALIDATED"
        raise TaskError("O plano mudou depois deste pedido; a aprovação foi invalidada.")
    if approval.expires_at is not None and approval.expires_at <= now:
        approval.status = "EXPIRED"
        audit.record(db, "approval.expired", task_id=task.id, entity_type="approval",
                     entity_id=str(approval.id))
        raise TaskError("Esta aprovação expirou. Peça uma nova revisão do plano.")
    if echoed_scope_hash != approval.scope_hash:
        raise TaskError("A tela mostrava uma versão diferente desta ação. Recarregue e "
                        "revise antes de decidir.")
    step = db.get(TaskStep, approval.step_id) if approval.step_id else None
    expected = scope_hash(task.id, step.plan_version, step.position, step.action_type,
                          step.parameters) if step else None
    if expected != approval.scope_hash:
        approval.status = "INVALIDATED"
        raise TaskError("A etapa não corresponde mais ao que foi pedido; aprovação invalidada.")

    approval.status = "APPROVED" if decision == "approve" else "REJECTED"
    approval.decided_by = user_id
    approval.decided_at = now
    approval.reason = reason[:1000] or None
    audit.record(db, f"approval.{'approved' if decision == 'approve' else 'rejected'}",
                 actor_type="user", actor_id=user_id, task_id=task.id, entity_type="approval",
                 entity_id=str(approval.id),
                 data={"step": step.position if step else None, "action": approval.action_type,
                       "plan_version": approval.plan_version, "scope_hash": approval.scope_hash,
                       "reason": reason})

    if decision == "reject":
        if task.status not in S.TERMINAL and S.can_transition(task.status, S.PLANNING):
            transition(db, task, S.PLANNING, actor_type="user", actor_id=user_id,
                       reason=f"Etapa {step.position if step else '?'} rejeitada; "
                              "revise o plano.")
        return task
    if task.status == S.PENDING_APPROVAL and not pending_approvals(db, task):
        transition(db, task, S.READY, actor_type="user", actor_id=user_id,
                   reason="todas as aprovações concedidas")
    return task


def pending_approvals(db: DBSession, task: Task) -> list[Approval]:
    return list(db.scalars(select(Approval).where(Approval.task_id == task.id,
                                                  Approval.plan_version == task.plan_version,
                                                  Approval.status == "PENDING")))


def valid_approval_for_step(db: DBSession, task: Task, step: TaskStep) -> Optional[Approval]:
    expected = scope_hash(task.id, step.plan_version, step.position, step.action_type,
                          step.parameters)
    now = utcnow()
    for ap in db.scalars(select(Approval).where(Approval.step_id == step.id,
                                                Approval.status == "APPROVED")):
        if (ap.plan_version == task.plan_version and ap.scope_hash == expected
                and (ap.expires_at is None or ap.expires_at > now) and ap.decided_by):
            return ap
    return None


def ensure_fresh_approval(db: DBSession, task: Task, step: TaskStep, ttl_hours: int) -> None:
    """Se a aprovação expirou antes da execução, marca como EXPIRED e pede outra."""
    now = utcnow()
    for ap in db.scalars(select(Approval).where(Approval.step_id == step.id,
                                                Approval.status.in_(("APPROVED", "PENDING")))):
        if ap.expires_at is not None and ap.expires_at <= now:
            ap.status = "EXPIRED"
            audit.record(db, "approval.expired", task_id=task.id, entity_type="approval",
                         entity_id=str(ap.id))
    if not db.scalar(select(Approval).where(Approval.step_id == step.id,
                                            Approval.status == "PENDING")):
        _request_approval(db, task, step, now, ttl_hours)


# --- cancelamento, retomada e recuperação ------------------------------------------

def request_cancel(db: DBSession, task: Task, user_id: uuid.UUID, reason: str) -> Task:
    if task.status in S.TERMINAL:
        raise TaskError(f"A tarefa já terminou ({task.status}).")
    if task.status == S.CANCEL_REQUESTED:
        return task  # idempotente
    why = reason or "cancelada pelo usuário"
    if task.status in S.IN_FLIGHT:
        # A etapa em andamento termina (ou é marcada incerta) e o executor encerra.
        transition(db, task, S.CANCEL_REQUESTED, reason=why, actor_type="user", actor_id=user_id)
    else:
        transition(db, task, S.CANCELLED, reason=why, actor_type="user", actor_id=user_id)
    for ap in pending_approvals(db, task):
        ap.status = "INVALIDATED"
        ap.reason = "tarefa cancelada"
    return task


def uncertain_steps(db: DBSession, task: Task) -> list[TaskStep]:
    """Etapas com execução iniciada e nunca concluída: não se sabe se o efeito ocorreu."""
    out = []
    for step in current_steps(db, task):
        ex = latest_execution(db, step)
        if ex is not None and ex.status == "RUNNING":
            out.append(step)
    return out


def resume(db: DBSession, task: Task, user_id: uuid.UUID, retry_uncertain: bool,
           approval_ttl_hours: int) -> Task:
    if task.status not in (S.INTERRUPTED, S.WAITING_FOR_USER):
        raise TaskError(f"Só é possível retomar tarefas interrompidas (estado atual {task.status}).")
    uncertain = uncertain_steps(db, task)
    if uncertain and not retry_uncertain:
        titles = ", ".join(f"{s.position}. {s.title}" for s in uncertain)
        raise TaskError(
            f"Não é possível saber se estas etapas foram concluídas antes da interrupção: "
            f"{titles}. Confirme que deseja executá-las novamente (pode repetir o efeito).",
            "needs_confirmation")
    for step in uncertain:
        ex = latest_execution(db, step)
        ex.status = "ABANDONED"
        ex.finished_at = utcnow()
        ex.stderr_tail = "Execução interrompida; reexecução confirmada pelo usuário."
        step.status = "PENDING"
        audit.record(db, "step.abandoned", actor_type="user", actor_id=user_id, task_id=task.id,
                     entity_type="step", entity_id=str(step.id), data={"position": step.position})
    waiting = [s for s in current_steps(db, task) if s.status == "WAITING"]
    if waiting and task.status == S.WAITING_FOR_USER and not uncertain:
        raise TaskError("A tarefa aguarda sua resposta à pergunta da etapa "
                        f"{waiting[0].position}.", "invalid")
    if task.status != S.READY:
        transition(db, task, S.READY, reason="retomada pelo usuário", actor_type="user",
                   actor_id=user_id)
    return task


def recover_on_startup(db: DBSession) -> int:
    """Tarefas que estavam em andamento quando o servidor parou viram INTERRUPTED."""
    count = 0
    for task in db.scalars(select(Task).where(Task.status.in_(
            tuple(S.IN_FLIGHT) + (S.CANCEL_REQUESTED,)))):
        target = S.CANCELLED if task.status == S.CANCEL_REQUESTED else S.INTERRUPTED
        reason = ("cancelamento concluído após reinício do servidor" if target == S.CANCELLED
                  else "servidor reiniciado durante a execução")
        transition(db, task, target, reason=reason)
        count += 1
    return count
