from tests.conftest import build_client


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_ready_when_migrated(client):
    r = client.get("/ready")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "ready"


def test_not_ready_without_migrations(make_settings):
    s = make_settings()  # banco sem migrações
    with build_client(s) as c:
        r = c.get("/ready")
    assert r.status_code == 503
    body = r.json()
    assert body["status"] == "not_ready"
    assert any(ch["name"] == "migrations" and not ch["ok"] for ch in body["checks"])


def test_ui_not_built_is_reported_not_faked(client):
    r = client.get("/")
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "ui_not_built"
