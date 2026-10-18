"""Chat em streaming: pedaços, persistência, idempotência, cancelamento e interrupção."""

import json
import threading
import time
import uuid

import pytest

from tests.conftest import CSRF, build_client, create_user, login


def parse(text):
    out = []
    for block in text.strip().split("\n\n"):
        ev = dict(l.split(": ", 1) for l in block.splitlines() if ": " in l)
        if "event" in ev:
            out.append((ev["event"], json.loads(ev["data"])))
    return out


@pytest.fixture
def mock_chat(make_settings):
    from titan.db.migrate import upgrade_head

    s = make_settings(model_provider="mock")
    upgrade_head(s.database_url)
    create_user(s)
    with build_client(s) as c:
        login(c)
        cid = c.post("/api/v1/conversations", json={}, headers=CSRF).json()["id"]
        yield c, cid, s


def test_stream_deltas_and_persistence(mock_chat):
    c, cid, _ = mock_chat
    r = c.post(f"/api/v1/conversations/{cid}/messages/stream",
               json={"content": "olá tudo bem"}, headers=CSRF)
    assert r.headers["content-type"].startswith("text/event-stream")
    events = parse(r.text)
    kinds = [k for k, _ in events]
    assert kinds[0] == "user_message" and kinds[-1] == "done"
    deltas = "".join(d["text"] for k, d in events if k == "delta")
    assert deltas.strip() == "[mock] olá tudo bem"
    done = events[-1][1]
    assert done["message"]["content"] == "[mock] olá tudo bem"
    assert done["metrics"]["first_delta_ms"] is not None
    msgs = c.get(f"/api/v1/conversations/{cid}").json()["messages"]
    assert [(m["role"], m["status"]) for m in msgs] == [("user", "complete"), ("assistant", "complete")]


def test_stream_without_model_reports_error_not_reply(auth_client):
    cid = auth_client.post("/api/v1/conversations", json={}, headers=CSRF).json()["id"]
    events = parse(auth_client.post(f"/api/v1/conversations/{cid}/messages/stream",
                                    json={"content": "oi"}, headers=CSRF).text)
    assert [k for k, _ in events] == ["user_message", "error"]
    assert "Nenhum modelo" in events[1][1]["detail"]
    msgs = auth_client.get(f"/api/v1/conversations/{cid}").json()["messages"]
    assert [m["role"] for m in msgs] == ["user"]


def test_stream_idempotent_resend(mock_chat):
    c, cid, _ = mock_chat
    body = {"content": "uma vez", "client_request_id": "voz-abcdefgh"}
    parse(c.post(f"/api/v1/conversations/{cid}/messages/stream", json=body, headers=CSRF).text)
    again = parse(c.post(f"/api/v1/conversations/{cid}/messages/stream", json=body,
                         headers=CSRF).text)
    assert again[0][1]["duplicate"] is True
    assert again[-1][0] == "done" and again[-1][1]["duplicate"] is True
    assert len(c.get(f"/api/v1/conversations/{cid}").json()["messages"]) == 2


def test_cancel_mid_stream_saves_partial_as_interrupted(mock_chat):
    from titan.db.engine import make_engine, make_session_factory
    from titan.memory.reply_stream import run_reply_stream
    from titan.models.providers import ChatTurn, MockProvider

    _, cid, s = mock_chat
    engine = make_engine(s.database_url)
    factory = make_session_factory(engine)
    provider = MockProvider()
    provider.delay = 0.02
    cancel = threading.Event()
    events = []

    def emit(kind, data):
        events.append((kind, data))
        if kind == "delta" and len([e for e in events if e[0] == "delta"]) == 2:
            cancel.set()  # usuário começou a falar (barge-in)

    run_reply_stream(factory, uuid.UUID(cid), provider,
                     [ChatTurn("user", "um dois tres quatro cinco seis sete")], emit, cancel)
    kinds = [k for k, _ in events]
    assert kinds.count("delta") == 2 and kinds[-1] == "interrupted"
    saved = events[-1][1]["message"]
    assert saved["status"] == "interrupted"
    assert saved["content"] == "[mock] um"  # só o que realmente chegou
    engine.dispose()


def test_interruption_point_shapes_next_turn(mock_chat):
    from titan.db.engine import make_engine, make_session_factory
    from titan.memory import conversations as repo
    from titan_api.routers.conversations import turns_for_model

    c, cid, s = mock_chat
    done = parse(c.post(f"/api/v1/conversations/{cid}/messages/stream",
                        json={"content": "explique algo longo"}, headers=CSRF).text)[-1][1]
    mid = done["message"]["id"]
    r = c.post(f"/api/v1/conversations/{cid}/messages/{mid}/interruption",
               json={"spoken_chars": 6}, headers=CSRF)
    assert r.status_code == 200 and r.json()["status"] == "interrupted"
    engine = make_engine(s.database_url)
    with make_session_factory(engine)() as db:
        turns = turns_for_model(repo.history(db, uuid.UUID(cid)))
    engine.dispose()
    assert turns[-1].content == "[mock] [resposta interrompida pelo usuário aqui]"


def test_interruption_requires_owner_and_assistant_message(mock_chat, settings):
    c, cid, _ = mock_chat
    events = parse(c.post(f"/api/v1/conversations/{cid}/messages/stream",
                          json={"content": "x"}, headers=CSRF).text)
    user_mid = events[0][1]["message"]["id"]
    r = c.post(f"/api/v1/conversations/{cid}/messages/{user_mid}/interruption",
               json={"spoken_chars": 1}, headers=CSRF)
    assert r.status_code == 404


def test_stream_requires_auth_and_csrf(client):
    cid = str(uuid.uuid4())
    assert client.post(f"/api/v1/conversations/{cid}/messages/stream", json={"content": "x"},
                       headers=CSRF).status_code == 401
    assert client.post(f"/api/v1/conversations/{cid}/messages/stream",
                       json={"content": "x"}).status_code == 403
