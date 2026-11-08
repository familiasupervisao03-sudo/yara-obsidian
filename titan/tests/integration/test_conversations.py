import uuid

from tests.conftest import CSRF, build_client, create_user, login


def test_create_list_get(auth_client):
    r = auth_client.post("/api/v1/conversations", json={"title": "Primeira"}, headers=CSRF)
    assert r.status_code == 201
    cid = r.json()["id"]
    uuid.UUID(cid)
    lst = auth_client.get("/api/v1/conversations").json()
    assert lst["total"] == 1 and lst["items"][0]["id"] == cid
    detail = auth_client.get(f"/api/v1/conversations/{cid}").json()
    assert detail["title"] == "Primeira" and detail["messages"] == []


def test_message_without_model_is_saved_and_not_faked(auth_client):
    cid = auth_client.post("/api/v1/conversations", json={}, headers=CSRF).json()["id"]
    r = auth_client.post(f"/api/v1/conversations/{cid}/messages",
                         json={"content": "Olá TITAN"}, headers=CSRF)
    assert r.status_code == 201
    body = r.json()
    assert body["reply"] is None
    assert body["model"]["available"] is False
    assert "Nenhum modelo" in body["model"]["detail"]
    msgs = auth_client.get(f"/api/v1/conversations/{cid}").json()["messages"]
    assert [m["role"] for m in msgs] == ["user"]


def test_message_with_mock_model(make_settings):
    from titan.db.migrate import upgrade_head

    s = make_settings(model_provider="mock")
    upgrade_head(s.database_url)
    create_user(s)
    with build_client(s) as c:
        login(c)
        cid = c.post("/api/v1/conversations", json={}, headers=CSRF).json()["id"]
        r = c.post(f"/api/v1/conversations/{cid}/messages", json={"content": "ping"}, headers=CSRF)
        body = r.json()
        assert body["reply"]["content"] == "[mock] ping"
        assert body["reply"]["model_provider"] == "mock"
        msgs = c.get(f"/api/v1/conversations/{cid}").json()["messages"]
        assert [m["role"] for m in msgs] == ["user", "assistant"]


def test_idempotent_message(auth_client):
    cid = auth_client.post("/api/v1/conversations", json={}, headers=CSRF).json()["id"]
    payload = {"content": "uma vez só", "client_request_id": "req-12345678"}
    r1 = auth_client.post(f"/api/v1/conversations/{cid}/messages", json=payload, headers=CSRF)
    r2 = auth_client.post(f"/api/v1/conversations/{cid}/messages", json=payload, headers=CSRF)
    assert r1.status_code == r2.status_code == 201
    assert r2.json()["duplicate"] is True
    assert r1.json()["user_message"]["id"] == r2.json()["user_message"]["id"]
    msgs = auth_client.get(f"/api/v1/conversations/{cid}").json()["messages"]
    assert len(msgs) == 1


def test_validation_errors(auth_client):
    cid = auth_client.post("/api/v1/conversations", json={}, headers=CSRF).json()["id"]
    r = auth_client.post(f"/api/v1/conversations/{cid}/messages", json={"content": ""}, headers=CSRF)
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "validation_error"
    assert auth_client.get("/api/v1/conversations/nao-uuid").status_code == 422


def test_unknown_conversation_404(auth_client):
    r = auth_client.get(f"/api/v1/conversations/{uuid.uuid4()}")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"


def test_users_cannot_see_each_other(settings):
    create_user(settings, "alice")
    create_user(settings, "bob")
    with build_client(settings) as a, build_client(settings) as b:
        login(a, "alice")
        login(b, "bob")
        cid = a.post("/api/v1/conversations", json={"title": "privada"}, headers=CSRF).json()["id"]
        assert b.get(f"/api/v1/conversations/{cid}").status_code == 404
        assert b.post(f"/api/v1/conversations/{cid}/messages", json={"content": "x"},
                      headers=CSRF).status_code == 404
        assert b.get("/api/v1/conversations").json()["total"] == 0


def test_status_and_settings(auth_client):
    st = auth_client.get("/api/v1/system/status").json()
    assert st["paid_apis_blocked"] is True
    assert st["external_models_blocked"] is True
    assert st["audit_chain_ok"] is True
    states = {s["name"]: s["state"] for s in st["services"]}
    assert states["database"] == "online"
    assert states["sandbox"] == "disabled"
    assert states["model"] == "unavailable"
    cfg = auth_client.get("/api/v1/settings").json()
    assert cfg["policies"]["paid_apis"] == "blocked"
    assert cfg["config"]["daily_paid_budget_brl"] == 0
