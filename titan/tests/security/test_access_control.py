"""Rotas sensíveis exigem autenticação, CSRF e rede autorizada."""

import re
import uuid

import pytest

from tests.conftest import CSRF, TEST_SECRET, build_client, create_user, login

PUBLIC = {("POST", "/api/v1/auth/login")}


def _api_routes(app):
    # Usa o esquema OpenAPI: é o contrato público de todas as rotas registradas.
    for path, ops in app.openapi()["paths"].items():
        if path.startswith("/api/"):
            for method in ops:
                yield method.upper(), path


def _fill(path):
    return re.sub(r"\{[^}]+\}", str(uuid.uuid4()), path)


def test_every_api_route_requires_auth(client):
    routes = list(_api_routes(client.app))
    assert len(routes) >= 7
    for method, path in routes:
        if (method, path) in PUBLIC:
            continue
        r = client.request(method, _fill(path), headers=CSRF, json={})
        assert r.status_code == 401, f"{method} {path} respondeu {r.status_code}"


def test_state_changing_requests_require_csrf_header(auth_client):
    r = auth_client.post("/api/v1/conversations", json={"title": "x"})
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "csrf_header_missing"


def test_login_requires_csrf_header(settings):
    with build_client(settings) as c:
        r = c.post("/api/v1/auth/login", json={"username": "a", "password": "b"})
        assert r.status_code == 403


@pytest.mark.parametrize("ip", ["192.168.0.50", "8.8.8.8", "10.0.0.2"])
def test_clients_outside_allowed_networks_are_refused(settings, ip):
    with build_client(settings, client=(ip, 1234)) as c:
        assert c.get("/health").status_code == 403
        assert c.post("/api/v1/auth/login", json={}, headers=CSRF).status_code == 403


def test_lan_client_allowed_when_network_configured(make_settings):
    from titan.db.migrate import upgrade_head

    s = make_settings(host="0.0.0.0", allowed_networks="127.0.0.1/32,192.168.0.0/24")
    upgrade_head(s.database_url)
    create_user(s)
    with build_client(s, client=("192.168.0.50", 1234)) as phone:
        assert phone.get("/api/v1/auth/me").status_code == 401  # rede ok, mas exige login
        assert login(phone).status_code == 200
        assert phone.get("/api/v1/auth/me").status_code == 200
    with build_client(s, client=("192.168.1.50", 1234)) as other:
        assert other.get("/health").status_code == 403


def test_forwarded_header_does_not_bypass_allowlist(settings):
    with build_client(settings, client=("8.8.8.8", 1)) as c:
        r = c.get("/health", headers={"X-Forwarded-For": "127.0.0.1"})
        assert r.status_code == 403


def test_security_headers(client):
    r = client.get("/health")
    assert "default-src 'self'" in r.headers["content-security-policy"]
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["x-content-type-options"] == "nosniff"


def test_no_cors_headers(client):
    r = client.get("/health", headers={"Origin": "http://evil.example"})
    assert "access-control-allow-origin" not in r.headers


def test_forged_session_cookie_rejected(settings):
    with build_client(settings) as c:
        c.cookies.set("titan_session", "token-inventado-pelo-atacante")
        assert c.get("/api/v1/auth/me").status_code == 401


def test_session_token_not_stored_in_plaintext(settings):
    from titan.db.engine import make_engine, make_session_factory
    from titan.db.models import Session

    create_user(settings)
    with build_client(settings) as c:
        login(c)
        token = c.cookies.get("titan_session")
    engine = make_engine(settings.database_url)
    with make_session_factory(engine)() as db:
        hashes = [s.token_hash for s in db.query(Session).all()]
    engine.dispose()
    assert token not in hashes and len(hashes) == 1
