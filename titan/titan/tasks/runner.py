"""Executor de tarefas: roda as etapas em ordem, verifica critérios e registra tudo.

Garantias:
* Uma tarefa só começa a partir de READY, por transição otimista (sem execução dupla).
* Ação sensível só roda com aprovação válida para a ação, os parâmetros e a versão.
* O início de cada execução é gravado ANTES do efeito; se o servidor cair no meio, a
  etapa fica "incerta" e a retomada exige confirmação humana.
* A tarefa só é COMPLETED se todas as etapas passarem na verificação.
"""

from __future__ import annotations

import logging
import threading
import uuid
from typing import Callable, Optional

from sqlalchemy.orm import Session as DBSession, sessionmaker

from titan.audit import log as audit
from titan.config.settings import Settings
from titan.db.models import Execution, MemoryItem, Task, TaskStep, VerificationResult, utcnow
from titan.models.providers import ChatTurn, ModelUnavailable, get_provider
from titan.policies.model_gate import ProviderBlocked
from titan.tasks import states as S
from titan.tasks.actions import ACTIONS, check_criterion, describe_criterion
from titan.tasks.service import (
    TaskError,
    current_steps,
    ensure_fresh_approval,
    latest_execution,
    transition,
    valid_approval_for_step,
)

log = logging.getLogger("titan.tasks")

WAIT = object()  # sentinela: a etapa aguarda resposta do usuário
OUTPUT_LIMIT = 20_000


class ActionFailed(Exception):
    pass


class TaskRunner:
    def __init__(self, settings: Settings, session_factory: sessionmaker[DBSession],
                 inline: bool = False) -> None:
        self.settings = settings
        self.session_factory = session_factory
        self.inline = inline
        self._active: set[uuid.UUID] = set()
        self._lock = threading.Lock()

    # --- disparo ---------------------------------------------------------------

    def start(self, task_id: uuid.UUID) -> None:
        with self._lock:
            if task_id in self._active:
                return
            self._active.add(task_id)
        if self.inline:
            self._run_guarded(task_id)
        else:
            threading.Thread(target=self._run_guarded, args=(task_id,), daemon=True,
                             name=f"titan-task-{task_id}").start()

    def _run_guarded(self, task_id: uuid.UUID) -> None:
        try:
            self.run(task_id)
        except Exception:  # nunca deixa a tarefa "presa" em RUNNING silenciosamente
            log.exception("Falha inesperada no executor da tarefa %s", task_id)
            try:
                with self.session_factory.begin() as db:
                    task = db.get(Task, task_id)
                    if task and task.status in S.IN_FLIGHT | {S.CANCEL_REQUESTED}:
                        transition(db, task, S.INTERRUPTED,
                                   reason="erro interno do executor; verifique os logs")
            except Exception:
                log.exception("Não foi possível marcar a tarefa %s como interrompida", task_id)
        finally:
            with self._lock:
                self._active.discard(task_id)

    # --- execução ----------------------------------------------------------------

    def run(self, task_id: uuid.UUID) -> None:
        with self.session_factory.begin() as db:
            task = db.get(Task, task_id)
            if task is None or task.status != S.READY:
                return
            transition(db, task, S.RUNNING, reason="execução iniciada")
            step_ids = [s.id for s in current_steps(db, task)]

        for step_id in step_ids:
            if not self._run_step(task_id, step_id):
                return

        with self.session_factory.begin() as db:
            task = db.get(Task, task_id)
            steps = current_steps(db, task)
            if all(s.status == "DONE" for s in steps) and task.status in S.IN_FLIGHT:
                if task.status == S.RUNNING:  # ex.: retomada com todas as etapas já feitas
                    transition(db, task, S.VERIFYING, reason="todas as etapas já verificadas")
                transition(db, task, S.COMPLETED,
                           reason=f"{len(steps)} etapa(s) concluída(s) e verificada(s)")

    def _cancel_if_requested(self, db: DBSession, task: Task) -> bool:
        db.refresh(task)
        if task.status == S.CANCEL_REQUESTED:
            transition(db, task, S.CANCELLED, reason=task.error or "cancelada pelo usuário")
            return True
        return False

    def _run_step(self, task_id: uuid.UUID, step_id: uuid.UUID) -> bool:
        """Executa uma etapa. Retorna False quando a tarefa deve parar."""
        with self.session_factory.begin() as db:
            task = db.get(Task, task_id)
            step = db.get(TaskStep, step_id)
            if self._cancel_if_requested(db, task):
                return False
            if step.status == "DONE":
                return True
            if task.status == S.VERIFYING:
                transition(db, task, S.RUNNING, reason=f"etapa {step.position}")
            spec = ACTIONS[step.action_type]
            if not spec.available:
                return self._fail(db, task, step, spec.unavailable_reason)
            if step.requires_approval and valid_approval_for_step(db, task, step) is None:
                ensure_fresh_approval(db, task, step, self.settings.approval_ttl_hours)
                transition(db, task, S.PENDING_APPROVAL,
                           reason=f"etapa {step.position} precisa de aprovação válida")
                return False
            last = latest_execution(db, step)
            if last is not None and last.status == "RUNNING":
                step.status = "UNCERTAIN"
                transition(db, task, S.WAITING_FOR_USER,
                           reason=f"etapa {step.position}: execução anterior sem resultado "
                                  "conhecido; confirme antes de repetir")
                return False
            if last is not None and last.status == "WAITING":
                transition(db, task, S.WAITING_FOR_USER,
                           reason=f"etapa {step.position} aguarda sua resposta")
                return False
            need_run = not (last is not None and last.status == "SUCCEEDED")
            execution_id = None
            if need_run:
                approval = (valid_approval_for_step(db, task, step)
                            if step.requires_approval else None)
                ex = Execution(task_id=task.id, step_id=step.id,
                               approval_id=approval.id if approval else None,
                               attempt=(last.attempt + 1) if last else 1,
                               command=f"{step.action_type} {step.title}"[:500],
                               status="RUNNING", sandbox_profile={})
                db.add(ex)
                step.status = "RUNNING"
                db.flush()
                execution_id = ex.id
                audit.record(db, "step.started", task_id=task.id, entity_type="step",
                             entity_id=str(step.id),
                             data={"position": step.position, "action": step.action_type,
                                   "attempt": ex.attempt})
            action, params, user_id = step.action_type, dict(step.parameters), task.user_id

        # Efeito da ação FORA da transação (pode ser lento, ex.: chamada ao modelo).
        if need_run:
            try:
                output = self._execute(action, params, user_id, task_id)
            except ActionFailed as exc:
                with self.session_factory.begin() as db:
                    ex = db.get(Execution, execution_id)
                    ex.status, ex.finished_at, ex.stderr_tail = "FAILED", utcnow(), str(exc)[:4000]
                    task, step = db.get(Task, task_id), db.get(TaskStep, step_id)
                    if self._cancel_if_requested(db, task):
                        return False
                    return self._fail(db, task, step, str(exc))
            with self.session_factory.begin() as db:
                ex = db.get(Execution, execution_id)
                task, step = db.get(Task, task_id), db.get(TaskStep, step_id)
                if output is WAIT:
                    ex.status = "WAITING"
                    step.status = "WAITING"
                    if self._cancel_if_requested(db, task):
                        return False
                    transition(db, task, S.WAITING_FOR_USER,
                               reason=f"etapa {step.position}: {params.get('question')}")
                    return False
                ex.status, ex.finished_at = "SUCCEEDED", utcnow()
                ex.exit_code = 0
                ex.stdout_tail = str(output)[:OUTPUT_LIMIT]
                audit.record(db, "step.executed", task_id=task.id, entity_type="step",
                             entity_id=str(step.id),
                             data={"position": step.position, "output_chars": len(str(output))})

        return self._verify(task_id, step_id)

    def _verify(self, task_id: uuid.UUID, step_id: uuid.UUID) -> bool:
        with self.session_factory.begin() as db:
            task, step = db.get(Task, task_id), db.get(TaskStep, step_id)
            if self._cancel_if_requested(db, task):
                return False
            transition(db, task, S.VERIFYING, reason=f"verificando etapa {step.position}")
            ex = latest_execution(db, step)
            output = ex.stdout_tail or ""
            failures = []
            for criterion in step.success_criteria:
                ok, detail = check_criterion(criterion, output)
                db.add(VerificationResult(task_id=task.id, execution_id=ex.id,
                                          criterion=describe_criterion(criterion), passed=ok,
                                          details=detail))
                if not ok:
                    failures.append(f"{describe_criterion(criterion)} ({detail})")
            audit.record(db, "verification.result", task_id=task.id, entity_type="step",
                         entity_id=str(step.id),
                         data={"position": step.position, "passed": not failures,
                               "failures": failures})
            if failures:
                return self._fail(db, task, step, "critério de sucesso não atendido: "
                                  + "; ".join(failures))
            step.status = "DONE"
            return True

    def _fail(self, db: DBSession, task: Task, step: TaskStep, reason: str) -> bool:
        step.status = "FAILED"
        audit.record(db, "step.failed", task_id=task.id, entity_type="step",
                     entity_id=str(step.id), data={"position": step.position, "reason": reason})
        if task.status == S.READY:
            transition(db, task, S.RUNNING, reason=f"etapa {step.position}")
        transition(db, task, S.FAILED, reason=f"etapa {step.position}: {reason}")
        return False

    # --- ações -------------------------------------------------------------------

    def _execute(self, action: str, params: dict, user_id: uuid.UUID, task_id: uuid.UUID):
        handler: Optional[Callable] = getattr(self, f"_action_{action}", None)
        if handler is None:
            raise ActionFailed(f"Ação '{action}' não implementada.")
        return handler(params, user_id, task_id)

    def _action_note(self, params: dict, user_id: uuid.UUID, task_id: uuid.UUID) -> str:
        text = str(params["text"])[:OUTPUT_LIMIT]
        with self.session_factory.begin() as db:
            db.add(MemoryItem(user_id=user_id, kind="note", content=text, source=f"task:{task_id}"))
        return text

    def _action_ask_model(self, params: dict, user_id: uuid.UUID, task_id: uuid.UUID) -> str:
        try:
            provider = get_provider(self.settings, self.session_factory)
            reply = provider.chat([ChatTurn("user", str(params["prompt"]))])
        except (ModelUnavailable, ProviderBlocked) as exc:
            raise ActionFailed(f"Modelo indisponível: {exc}") from exc
        return reply.content

    def _action_wait_for_user(self, params: dict, user_id: uuid.UUID, task_id: uuid.UUID):
        return WAIT

    def _action_run_code(self, params: dict, user_id: uuid.UUID, task_id: uuid.UUID):
        from titan.sandbox.contract import SandboxRequest, SandboxUnavailable, get_sandbox

        sandbox = get_sandbox(self.settings)
        try:
            result = sandbox.run(SandboxRequest(language=str(params["language"]),
                                                files={"main": str(params["code"])},
                                                command=[]))
        except SandboxUnavailable as exc:
            raise ActionFailed(str(exc)) from exc
        return result.stdout


def submit_reply(db: DBSession, task: Task, user_id: uuid.UUID, text: str) -> None:
    """Resposta do usuário a uma etapa wait_for_user; a tarefa volta a READY."""
    if task.status != S.WAITING_FOR_USER:
        raise TaskError("A tarefa não está aguardando resposta.")
    waiting = [s for s in current_steps(db, task) if s.status == "WAITING"]
    if not waiting:
        raise TaskError("Nenhuma etapa aguarda resposta (talvez precise de 'retomar').")
    step = waiting[0]
    ex = latest_execution(db, step)
    ex.status, ex.finished_at, ex.exit_code = "SUCCEEDED", utcnow(), 0
    ex.stdout_tail = text[:OUTPUT_LIMIT]
    step.status = "PENDING"
    audit.record(db, "step.user_reply", actor_type="user", actor_id=user_id, task_id=task.id,
                 entity_type="step", entity_id=str(step.id),
                 data={"position": step.position, "length": len(text)})
    transition(db, task, S.READY, reason="resposta do usuário recebida", actor_type="user",
               actor_id=user_id)
