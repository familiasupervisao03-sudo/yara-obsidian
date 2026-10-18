"""Fase 2: tarefas, planos versionados, aprovações, cancelamento, retomada e SSE."""

import json
import uuid

import pytest

from tests.conftest import CSRF, build_client, create_user, login

NOTE = {"title": "Anotar", "action_type": "note", "parameters": {"text": "lembrar do backup"},
        "success_criteria": [{"type": "contains", "value": "backup"}]}
ASK = {"title": "Perguntar", "action_type": "ask_model", "parameters": {"prompt": "diga oi"},
       "success_criteria": [{"type": "output_nonempty"}]}
WAIT = {"title": "Confirmar", "action_type": "wait_for_user",
        "parameters": {"question": "Qual o nome do projeto?"},
        "success_criteria": [{"type": "contains", "value": "titan"}]}
CODE = {"title": "Rodar código", "action_type": "run_code",
        "parameters": {"language": "python", "code": "print(1)"},
        "success_criteria": [{"type": "output_nonempty"}]}


def new_task(c, steps=None, key=None, title="Tarefa"):
    headers = dict(CSRF)
    if key:
        headers["Idempotency-Key"] = key
    body = {"title": title, "description": "teste"}
    if steps is not None:
        body["steps"] = steps
    return c.post("/api/v1/tasks", json=body, headers=headers)


def approve_all(c, detail, decision="approve"):
    for ap in detail["approvals"]:
        if ap["status"] == "PENDING":
            r = c.post(f"/api/v1/approvals/{ap['id']}/decision",
                       json={"decision": decision, "scope_hash": ap["scope_hash"]}, headers=CSRF)
            assert r.status_code == 200, r.text
            detail = r.json()
    return detail


@pytest.fixture
def mock_client(make_settings):
    from titan.db.migrate import upgrade_head

    s = make_settings(model_provider="mock")
    upgrade_head(s.database_url)
    create_user(s)
    with build_client(s) as c:
        login(c)
        yield c, s


def test_task_without_plan_waits_in_planning(auth_client):
    r = new_task(auth_client)
    assert r.status_code == 201
    assert r.json()["task"]["status"] == "PLANNING"


def test_full_run_with_verification(auth_client):
    d = new_task(auth_client, [NOTE]).json()
    assert d["task"]["status"] == "READY"
    assert d["steps"][0]["success_criteria"] == NOTE["success_criteria"]
    d = auth_client.post(f"/api/v1/tasks/{d['task']['id']}/start", headers=CSRF).json()
    assert d["task"]["status"] == "COMPLETED"
    assert d["steps"][0]["status"] == "DONE"
    assert d["verification"][0]["passed"] is True


def test_failed_criterion_fails_task_not_success(auth_client):
    bad = dict(NOTE, success_criteria=[{"type": "contains", "value": "inexistente"}])
    d = new_task(auth_client, [bad]).json()
    d = auth_client.post(f"/api/v1/tasks/{d['task']['id']}/start", headers=CSRF).json()
    assert d["task"]["status"] == "FAILED"
    assert "critério" in d["task"]["status_reason"]


def test_sensitive_action_requires_approval_before_running(mock_client):
    c, _ = mock_client
    d = new_task(c, [ASK]).json()
    assert d["task"]["status"] == "PENDING_APPROVAL"
    assert d["steps"][0]["requires_approval"] is True
    r = c.post(f"/api/v1/tasks/{d['task']['id']}/start", headers=CSRF)
    assert r.status_code == 409  # não começa sem autorização
    ex = c.get(f"/api/v1/tasks/{d['task']['id']}/executions").json()
    assert ex == []
    d = approve_all(c, d)
    assert d["task"]["status"] == "READY"
    d = c.post(f"/api/v1/tasks/{d['task']['id']}/start", headers=CSRF).json()
    assert d["task"]["status"] == "COMPLETED"
    assert d["steps"][0]["last_output"] == "[mock] diga oi"


def test_plan_cannot_disable_approval_for_sensitive_action(mock_client):
    c, _ = mock_client
    d = new_task(c, [dict(ASK, requires_approval=False)]).json()
    assert d["steps"][0]["requires_approval"] is True
    assert d["task"]["status"] == "PENDING_APPROVAL"


def test_rejected_action_is_not_executed(mock_client):
    c, _ = mock_client
    d = new_task(c, [ASK]).json()
    d = approve_all(c, d, "reject")
    assert d["task"]["status"] == "PLANNING"
    r = c.post(f"/api/v1/tasks/{d['task']['id']}/start", headers=CSRF)
    assert r.status_code == 409
    assert c.get(f"/api/v1/tasks/{d['task']['id']}/executions").json() == []


def test_plan_change_invalidates_previous_approvals(mock_client):
    c, _ = mock_client
    d = new_task(c, [ASK]).json()
    old = d["approvals"][0]
    tid = d["task"]["id"]
    changed = dict(ASK, parameters={"prompt": "outra coisa"})
    d = c.put(f"/api/v1/tasks/{tid}/plan", json={"steps": [changed], "change_note": "mudou"},
              headers=CSRF).json()
    assert d["task"]["plan_version"] == 2
    statuses = {a["id"]: a["status"] for a in d["approvals"]}
    assert statuses[old["id"]] == "INVALIDATED"
    # Aprovar o pedido antigo (versão 1) é recusado.
    r = c.post(f"/api/v1/approvals/{old['id']}/decision",
               json={"decision": "approve", "scope_hash": old["scope_hash"]}, headers=CSRF)
    assert r.status_code == 409
    assert [p["version"] for p in d["plans"]] == [1, 2]


def test_approval_must_echo_exact_scope(mock_client):
    c, _ = mock_client
    d = new_task(c, [ASK]).json()
    ap = d["approvals"][0]
    r = c.post(f"/api/v1/approvals/{ap['id']}/decision",
               json={"decision": "approve", "scope_hash": "0" * 64}, headers=CSRF)
    assert r.status_code == 409


def test_expired_approval_is_refused(mock_client):
    from datetime import timedelta

    from titan.db.engine import make_engine, make_session_factory
    from titan.db.models import Approval, utcnow

    c, s = mock_client
    d = new_task(c, [ASK]).json()
    engine = make_engine(s.database_url)
    with make_session_factory(engine).begin() as db:
        for ap in db.query(Approval).all():
            ap.expires_at = utcnow() - timedelta(minutes=1)
    engine.dispose()
    ap = d["approvals"][0]
    r = c.post(f"/api/v1/approvals/{ap['id']}/decision",
               json={"decision": "approve", "scope_hash": ap["scope_hash"]}, headers=CSRF)
    assert r.status_code == 409 and "expirou" in r.json()["error"]["message"]
    status = c.get(f"/api/v1/tasks/{d['task']['id']}").json()["approvals"][0]["status"]
    assert status == "EXPIRED"


def test_model_cannot_decide_approvals():
    from titan.tasks.service import TaskError, decide_approval

    with pytest.raises(TaskError, match="Somente um usuário"):
        decide_approval(None, None, actor_type="model", user_id=None, decision="approve",
                        echoed_scope_hash="x", reason="")


def test_code_execution_blocked_even_if_approved(auth_client):
    d = new_task(auth_client, [CODE]).json()
    d = approve_all(auth_client, d)
    d = auth_client.post(f"/api/v1/tasks/{d['task']['id']}/start", headers=CSRF).json()
    assert d["task"]["status"] == "FAILED"
    assert "sandbox" in d["task"]["status_reason"].lower()


def test_wait_for_user_and_reply(auth_client):
    d = new_task(auth_client, [WAIT, NOTE]).json()
    tid = d["task"]["id"]
    d = auth_client.post(f"/api/v1/tasks/{tid}/start", headers=CSRF).json()
    assert d["task"]["status"] == "WAITING_FOR_USER"
    d = auth_client.post(f"/api/v1/tasks/{tid}/reply", json={"text": "Projeto TITAN"},
                         headers=CSRF).json()
    assert d["task"]["status"] == "COMPLETED"
    assert [s["status"] for s in d["steps"]] == ["DONE", "DONE"]


def test_cancel_and_invalid_transitions(auth_client):
    d = new_task(auth_client, [WAIT]).json()
    tid = d["task"]["id"]
    d = auth_client.post(f"/api/v1/tasks/{tid}/cancel", json={"reason": "desisti"},
                         headers=CSRF).json()
    assert d["task"]["status"] == "CANCELLED"
    assert auth_client.post(f"/api/v1/tasks/{tid}/start", headers=CSRF).status_code == 409
    assert auth_client.post(f"/api/v1/tasks/{tid}/cancel", json={}, headers=CSRF).status_code == 409
    r = auth_client.put(f"/api/v1/tasks/{tid}/plan", json={"steps": [NOTE]}, headers=CSRF)
    assert r.status_code == 409


def test_idempotent_creation(auth_client):
    r1 = new_task(auth_client, [NOTE], key="tarefa-12345678")
    r2 = new_task(auth_client, [NOTE], key="tarefa-12345678")
    assert r1.status_code == 201 and r2.status_code == 200
    assert r1.json()["task"]["id"] == r2.json()["task"]["id"]
    assert len(auth_client.get("/api/v1/tasks").json()["items"]) == 1


def test_invalid_plans_rejected(auth_client):
    for step in [dict(NOTE, action_type="rm_rf"), dict(NOTE, parameters={}),
                 dict(NOTE, success_criteria=[{"type": "magia"}])]:
        r = new_task(auth_client, [step])
        assert r.status_code == 422, r.text
    assert auth_client.get("/api/v1/tasks").json()["items"] == []  # nada meio criado


def test_interrupted_task_resume_without_duplication(settings):
    """Servidor cai no meio de uma etapa: retomada exige confirmação e não duplica."""
    from titan.db.engine import make_engine, make_session_factory
    from titan.db.models import Execution, Task, TaskStep

    create_user(settings)
    with build_client(settings) as c:
        login(c)
        d = new_task(c, [NOTE, dict(NOTE, title="Segunda")]).json()
        tid = uuid.UUID(d["task"]["id"])
    # Simula queda: tarefa RUNNING com a 1ª etapa iniciada e sem resultado.
    engine = make_engine(settings.database_url)
    with make_session_factory(engine).begin() as db:
        task = db.get(Task, tid)
        task.status = "RUNNING"
        step = db.query(TaskStep).filter_by(task_id=tid, position=1).one()
        step.status = "RUNNING"
        db.add(Execution(task_id=tid, step_id=step.id, attempt=1, command="note",
                         status="RUNNING", sandbox_profile={}))
    engine.dispose()

    with build_client(settings) as c:  # reinício: recuperação automática
        login(c)
        d = c.get(f"/api/v1/tasks/{tid}").json()
        assert d["task"]["status"] == "INTERRUPTED"
        r = c.post(f"/api/v1/tasks/{tid}/resume", json={}, headers=CSRF)
        assert r.status_code == 409 and r.json()["error"]["code"] == "needs_confirmation"
        d = c.post(f"/api/v1/tasks/{tid}/resume", json={"retry_uncertain": True},
                   headers=CSRF).json()
        assert d["task"]["status"] == "COMPLETED"
        ex = c.get(f"/api/v1/tasks/{tid}/executions").json()
        assert [e["status"] for e in ex] == ["ABANDONED", "SUCCEEDED", "SUCCEEDED"]


def test_double_start_does_not_run_twice(auth_client):
    d = new_task(auth_client, [NOTE]).json()
    tid = d["task"]["id"]
    auth_client.post(f"/api/v1/tasks/{tid}/start", headers=CSRF)
    assert auth_client.post(f"/api/v1/tasks/{tid}/start", headers=CSRF).status_code == 409
    assert len(auth_client.get(f"/api/v1/tasks/{tid}/executions").json()) == 1


def test_audit_reconstructs_plan_approval_execution_result(mock_client):
    c, _ = mock_client
    d = approve_all(c, new_task(c, [ASK]).json())
    tid = d["task"]["id"]
    c.post(f"/api/v1/tasks/{tid}/start", headers=CSRF)
    types = [e["event_type"] for e in c.get(f"/api/v1/tasks/{tid}/audit").json()]
    for expected in ["task.created", "plan.created", "approval.requested", "approval.approved",
                     "step.started", "step.executed", "verification.result"]:
        assert expected in types, expected
    states = [e["data"]["to"] for e in c.get(f"/api/v1/tasks/{tid}/audit").json()
              if e["event_type"] == "task.state"]
    assert states == ["PENDING_APPROVAL", "READY", "RUNNING", "VERIFYING", "COMPLETED"]


def _sse_events(text):
    events = []
    for block in text.split("\n\n"):
        lines = dict(l.split(": ", 1) for l in block.splitlines() if ": " in l and not l.startswith(":"))
        if "data" in lines:
            events.append((lines.get("id"), lines.get("event"), json.loads(lines["data"])))
    return events


def test_sse_replays_and_resumes_without_duplicates(auth_client):
    d = new_task(auth_client, [NOTE]).json()
    tid = d["task"]["id"]
    auth_client.post(f"/api/v1/tasks/{tid}/start", headers=CSRF)
    r = auth_client.get(f"/api/v1/tasks/{tid}/events?max_seconds=5")
    assert r.headers["content-type"].startswith("text/event-stream")
    events = _sse_events(r.text)
    ids = [int(e[0]) for e in events if e[1] == "task"]
    assert ids == sorted(set(ids)) and len(ids) >= 5
    assert events[-1][1] == "end" and events[-1][2]["task_status"] == "COMPLETED"
    # Reconexão a partir do meio: só os eventos posteriores.
    mid = ids[2]
    r2 = auth_client.get(f"/api/v1/tasks/{tid}/events?max_seconds=5",
                         headers={"Last-Event-ID": str(mid)})
    ids2 = [int(e[0]) for e in _sse_events(r2.text) if e[1] == "task"]
    assert ids2 == [i for i in ids if i > mid]


def test_other_users_cannot_see_tasks_or_approvals(settings):
    create_user(settings, "alice")
    create_user(settings, "bob")
    with build_client(settings) as a, build_client(settings) as b:
        login(a, "alice")
        login(b, "bob")
        d = new_task(a, [CODE]).json()
        tid, ap = d["task"]["id"], d["approvals"][0]
        assert b.get(f"/api/v1/tasks/{tid}").status_code == 404
        assert b.get(f"/api/v1/tasks/{tid}/events?max_seconds=1").status_code == 404
        assert b.get("/api/v1/approvals").json() == []
        r = b.post(f"/api/v1/approvals/{ap['id']}/decision",
                   json={"decision": "approve", "scope_hash": ap["scope_hash"]}, headers=CSRF)
        assert r.status_code == 404


def test_background_thread_runner(make_settings):
    import time

    from titan.db.migrate import upgrade_head

    s = make_settings(task_runner="thread")
    upgrade_head(s.database_url)
    create_user(s)
    with build_client(s) as c:
        login(c)
        tid = new_task(c, [NOTE, dict(NOTE, title="Outra")]).json()["task"]["id"]
        c.post(f"/api/v1/tasks/{tid}/start", headers=CSRF)
        for _ in range(100):
            status = c.get(f"/api/v1/tasks/{tid}").json()["task"]["status"]
            if status in ("COMPLETED", "FAILED"):
                break
            time.sleep(0.05)
        assert status == "COMPLETED"


def test_cancel_requested_during_execution_stops_before_next_step(settings):
    from titan.db.engine import make_engine, make_session_factory
    from titan.db.models import Task
    from titan.tasks.runner import TaskRunner
    from titan.tasks.service import request_cancel

    uid = create_user(settings)
    with build_client(settings) as c:
        login(c)
        tid = uuid.UUID(new_task(c, [NOTE, dict(NOTE, title="Segunda")]).json()["task"]["id"])
    engine = make_engine(settings.database_url)
    factory = make_session_factory(engine)
    runner = TaskRunner(settings, factory, inline=True)
    original = runner._action_note

    def note_then_cancel(params, user_id, task_id):
        out = original(params, user_id, task_id)
        with factory.begin() as db:  # o usuário pede cancelamento durante a 1ª etapa
            request_cancel(db, db.get(Task, task_id), uid, "parar")
        return out

    runner._action_note = note_then_cancel
    runner.start(tid)
    with factory() as db:
        task = db.get(Task, tid)
        assert task.status == "CANCELLED"
    with build_client(settings) as c:
        login(c)
        ex = c.get(f"/api/v1/tasks/{tid}/executions").json()
        assert len(ex) == 1  # a segunda etapa nunca começou
    engine.dispose()
