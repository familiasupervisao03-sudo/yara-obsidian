"""Máquina de estados das tarefas (validada no backend)."""

from __future__ import annotations

RECEIVED = "RECEIVED"
PLANNING = "PLANNING"
PENDING_APPROVAL = "PENDING_APPROVAL"
READY = "READY"
RUNNING = "RUNNING"
VERIFYING = "VERIFYING"
WAITING_FOR_USER = "WAITING_FOR_USER"
CANCEL_REQUESTED = "CANCEL_REQUESTED"
CANCELLED = "CANCELLED"
INTERRUPTED = "INTERRUPTED"
COMPLETED = "COMPLETED"
FAILED = "FAILED"

TERMINAL = frozenset({CANCELLED, COMPLETED, FAILED})
# Estados em que o plano pode ser (re)definido pelo usuário.
PLAN_EDITABLE = frozenset({RECEIVED, PLANNING, PENDING_APPROVAL, READY, WAITING_FOR_USER,
                           INTERRUPTED})
# Estados "em andamento" que, após reinício do servidor, viram INTERRUPTED.
IN_FLIGHT = frozenset({RUNNING, VERIFYING})

TRANSITIONS: dict[str, frozenset[str]] = {
    RECEIVED: frozenset({PLANNING, PENDING_APPROVAL, READY, CANCELLED, FAILED}),
    PLANNING: frozenset({PENDING_APPROVAL, READY, WAITING_FOR_USER, CANCELLED, FAILED}),
    PENDING_APPROVAL: frozenset({READY, PLANNING, PENDING_APPROVAL, CANCELLED, FAILED}),
    READY: frozenset({RUNNING, PLANNING, PENDING_APPROVAL, READY, CANCELLED}),
    RUNNING: frozenset({VERIFYING, WAITING_FOR_USER, PENDING_APPROVAL, CANCEL_REQUESTED,
                        CANCELLED, INTERRUPTED, FAILED}),
    VERIFYING: frozenset({RUNNING, COMPLETED, FAILED, CANCEL_REQUESTED, CANCELLED,
                          INTERRUPTED}),
    WAITING_FOR_USER: frozenset({RUNNING, READY, PLANNING, PENDING_APPROVAL, CANCELLED,
                                 FAILED}),
    CANCEL_REQUESTED: frozenset({CANCELLED, INTERRUPTED}),
    INTERRUPTED: frozenset({READY, PLANNING, PENDING_APPROVAL, WAITING_FOR_USER, CANCELLED}),
    CANCELLED: frozenset(),
    COMPLETED: frozenset(),
    FAILED: frozenset(),
}


def can_transition(current: str, new: str) -> bool:
    return new in TRANSITIONS.get(current, frozenset())
