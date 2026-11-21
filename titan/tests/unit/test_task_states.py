"""Máquina de estados das tarefas: tabela explícita, coerente com o banco."""

import itertools

from titan.db.models import TASK_STATES
from titan.tasks import states as S


def test_table_covers_exactly_the_database_states():
    assert set(S.TRANSITIONS) == set(TASK_STATES)
    for targets in S.TRANSITIONS.values():
        assert targets <= set(TASK_STATES)
    assert S.TERMINAL | S.PLAN_EDITABLE | S.IN_FLIGHT <= set(TASK_STATES)


def test_terminal_states_have_no_exit():
    for state in S.TERMINAL:
        assert S.TRANSITIONS[state] == frozenset()
        assert not any(S.can_transition(state, t) for t in TASK_STATES)


def test_every_pair_follows_the_table():
    for current, new in itertools.product(TASK_STATES, repeat=2):
        assert S.can_transition(current, new) == (new in S.TRANSITIONS[current])


def test_examples_of_forbidden_transitions():
    forbidden = [
        (S.RECEIVED, S.RUNNING),       # não executa sem plano
        (S.RECEIVED, S.COMPLETED),     # não conclui sem verificação
        (S.PENDING_APPROVAL, S.RUNNING),  # não executa sem aprovação
        (S.RUNNING, S.COMPLETED),      # conclusão só passando por VERIFYING
        (S.CANCEL_REQUESTED, S.RUNNING),
        (S.COMPLETED, S.READY),
        (S.FAILED, S.RUNNING),
        (S.CANCELLED, S.READY),
    ]
    for current, new in forbidden:
        assert not S.can_transition(current, new), (current, new)


def test_unknown_states_are_refused():
    assert not S.can_transition("INEXISTENTE", S.READY)
    assert not S.can_transition(S.READY, "INEXISTENTE")


def test_completion_is_only_reachable_through_verification():
    assert [s for s in TASK_STATES if S.can_transition(s, S.COMPLETED)] == [S.VERIFYING]
