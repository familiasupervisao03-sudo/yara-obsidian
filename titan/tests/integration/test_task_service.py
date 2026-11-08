"""Serviço de tarefas chamado diretamente (sem HTTP), com banco migrado."""

import pytest
from sqlalchemy import func, select

from tests.conftest import create_user
from titan.audit import log as audit
from titan.db.engine import make_engine, make_session_factory
from titan.db.models import AuditEvent, Task
from titan.tasks import states as S
from titan.tasks.service import (
    TaskError,
    create_task,
    find_by_idempotency_key,
    get_task,
    list_tasks,
    transition,
)

NOTE = {"title": "Anotar", "action_type": "note", "parameters": {"text": "backup"},
        "success_criteria": [{"type": "contains", "value": "backup"}]}


@pytest.fixture
def factory(settings):
    engine = make_engine(settings.database_url)
    yield make_session_factory(engine)
    engine.dispose()


@pytest.fixture
def users(settings):
    return create_user(settings, "alice"), create_user(settings, "bob")


def _new(db, user_id, key=None, steps=None, title="Tarefa"):
    return create_task(db, user_id, title, "descrição", steps, key, approval_ttl_hours=24)


def _count(db, model):
    return db.scalar(select(func.count()).select_from(model))


def test_create_task_without_plan_is_audited(factory, users):
    alice, _ = users
    with factory.begin() as db:
        task, dup = _new(db, alice)
        tid = task.id
    assert dup is False
    with factory() as db:
        task = db.get(Task, tid)
        assert (task.user_id, task.status, task.plan_version) == (alice, S.PLANNING, 0)
        types = list(db.scalars(select(AuditEvent.event_type)
                                .where(AuditEvent.task_id == tid).order_by(AuditEvent.id)))
        assert types == ["task.created", "task.state"]
        assert audit.verify_chain(db) == (True, None)


def test_create_task_with_plan_becomes_ready(factory, users):
    alice, _ = users
    with factory.begin() as db:
        task, _ = _new(db, alice, steps=[NOTE])
        assert task.status == S.READY and task.plan_version == 1


def test_allowed_transition_is_applied_and_audited(factory, users):
    alice, _ = users
    with factory.begin() as db:
        task, _ = _new(db, alice)
        transition(db, task, S.CANCELLED, reason="teste", actor_type="user", actor_id=alice)
        tid = task.id
    with factory() as db:
        assert db.get(Task, tid).status == S.CANCELLED
        last = db.scalar(select(AuditEvent).where(AuditEvent.task_id == tid)
                         .order_by(AuditEvent.id.desc()).limit(1))
        assert last.event_type == "task.state"
        assert last.data["from"] == S.PLANNING and last.data["to"] == S.CANCELLED


def test_forbidden_transition_changes_nothing(factory, users):
    alice, _ = users
    with factory.begin() as db:
        task, _ = _new(db, alice)
        tid = task.id
    with factory() as db:
        before = _count(db, AuditEvent)
    with factory.begin() as db:
        task = db.get(Task, tid)
        with pytest.raises(TaskError) as err:
            transition(db, task, S.COMPLETED)
        assert err.value.code == "conflict"
    with factory() as db:
        assert db.get(Task, tid).status == S.PLANNING
        assert _count(db, AuditEvent) == before


def test_stale_state_is_detected(factory, users):
    """Concorrência otimista: se o estado mudou no banco, a transição é recusada."""
    alice, _ = users
    with factory.begin() as db:
        task, _ = _new(db, alice, steps=[NOTE])
        tid = task.id
    with factory() as db1:
        stale = db1.get(Task, tid)  # lido como READY
        with factory.begin() as db2:
            transition(db2, db2.get(Task, tid), S.CANCELLED, reason="outra requisição")
        with pytest.raises(TaskError):
            transition(db1, stale, S.RUNNING)
        db1.rollback()
    with factory() as db:
        assert db.get(Task, tid).status == S.CANCELLED


def test_other_users_tasks_are_invisible(factory, users):
    alice, bob = users
    with factory.begin() as db:
        task, _ = _new(db, alice, title="da alice")
        tid = task.id
    with factory() as db:
        with pytest.raises(TaskError) as err:
            get_task(db, bob, tid)
        assert err.value.code == "not_found"
        assert get_task(db, alice, tid).id == tid
        assert list_tasks(db, bob) == []
        assert [t.id for t in list_tasks(db, alice)] == [tid]


def test_list_tasks_orders_and_limits(factory, users):
    alice, _ = users
    ids = []
    for i in range(3):
        with factory.begin() as db:
            ids.append(_new(db, alice, title=f"t{i}")[0].id)
    with factory() as db:
        assert len(list_tasks(db, alice, limit=2)) == 2
        assert {t.id for t in list_tasks(db, alice)} == set(ids)


def test_idempotency_key_returns_original(factory, users):
    alice, bob = users
    with factory.begin() as db:
        first, dup1 = _new(db, alice, key="chave-123456")
    with factory.begin() as db:
        again, dup2 = _new(db, alice, key="chave-123456", title="outro título")
    assert (dup1, dup2) == (False, True) and again.id == first.id
    with factory.begin() as db:  # a chave é por usuário
        other, dup3 = _new(db, bob, key="chave-123456")
    assert dup3 is False and other.id != first.id
    with factory() as db:
        assert _count(db, Task) == 2


def _miss_first_lookup(monkeypatch):
    """Simula a corrida: a consulta prévia não vê a tarefa gravada por outro pedido."""
    from titan.tasks import service

    calls = []
    real = service.find_by_idempotency_key

    def miss_first(db, user_id, key):
        calls.append(key)
        return None if len(calls) == 1 else real(db, user_id, key)

    monkeypatch.setattr(service, "find_by_idempotency_key", miss_first)


def test_idempotency_race_signals_duplicate_without_partial_writes(factory, users, monkeypatch):
    alice, _ = users
    with factory.begin() as db:
        first, _ = _new(db, alice, key="corrida-123456")
    with factory() as db:
        events_before = _count(db, AuditEvent)
    _miss_first_lookup(monkeypatch)
    with pytest.raises(TaskError) as err:
        with factory.begin() as db:
            _new(db, alice, key="corrida-123456")
    assert err.value.code == "duplicate"
    with factory() as db:
        assert _count(db, Task) == 1
        assert _count(db, AuditEvent) == events_before
        assert find_by_idempotency_key(db, alice, "corrida-123456").id == first.id
        assert audit.verify_chain(db) == (True, None)


def test_idempotency_race_over_http_returns_original(settings, monkeypatch):
    from tests.conftest import CSRF, build_client, login

    create_user(settings)
    with build_client(settings) as c:
        login(c)
        h = dict(CSRF, **{"Idempotency-Key": "corrida-http-1234"})
        body = {"title": "Tarefa", "description": "x"}
        r1 = c.post("/api/v1/tasks", json=body, headers=h)
        assert r1.status_code == 201
        _miss_first_lookup(monkeypatch)
        r2 = c.post("/api/v1/tasks", json=body, headers=h)
        assert r2.status_code == 200, r2.text
        assert r2.json()["task"]["id"] == r1.json()["task"]["id"]
        assert len(c.get("/api/v1/tasks").json()["items"]) == 1


def test_audit_failure_rolls_back_everything(factory, users, monkeypatch):
    alice, _ = users
    with factory() as db:
        tasks_before, events_before = _count(db, Task), _count(db, AuditEvent)

    real = audit.record

    def fail_on_state(db, event_type, **kw):
        if event_type == "task.state":
            raise RuntimeError("falha simulada na auditoria")
        return real(db, event_type, **kw)

    monkeypatch.setattr(audit, "record", fail_on_state)
    with pytest.raises(RuntimeError):
        with factory.begin() as db:
            _new(db, alice, key="rollback-123456")
    monkeypatch.undo()

    with factory() as db:
        assert _count(db, Task) == tasks_before
        assert _count(db, AuditEvent) == events_before
        assert audit.verify_chain(db) == (True, None)
    # O lock da cadeia foi liberado: novas operações seguem normalmente.
    with factory.begin() as db:
        task, dup = _new(db, alice, key="rollback-123456")
        assert dup is False


def test_error_inside_transaction_leaves_no_partial_task(factory, users):
    alice, _ = users
    with pytest.raises(ZeroDivisionError):
        with factory.begin() as db:
            _new(db, alice, steps=[NOTE])
            1 / 0
    with factory() as db:
        assert _count(db, Task) == 0
        assert audit.verify_chain(db) == (True, None)
