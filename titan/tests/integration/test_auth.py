from tests.conftest import CSRF, build_client, create_user, login


def test_login_me_logout(settings):
    create_user(settings)
    with build_client(settings) as c:
        r = login(c)
        assert r.status_code == 200
        assert r.json()["user"]["username"] == "operador"
        assert c.get("/api/v1/auth/me").status_code == 200
        assert c.post("/api/v1/auth/logout", headers=CSRF).status_code == 204
        assert c.get("/api/v1/auth/me").status_code == 401


def test_logout_revokes_token_server_side(settings):
    create_user(settings)
    with build_client(settings) as c:
        login(c)
        token = c.cookies.get("titan_session")
        c.post("/api/v1/auth/logout", headers=CSRF)
        c.cookies.set("titan_session", token)  # reutiliza o token antigo
        assert c.get("/api/v1/auth/me").status_code == 401


def test_wrong_password(settings):
    create_user(settings)
    with build_client(settings) as c:
        r = login(c, password="errada-errada")
        assert r.status_code == 401
        assert r.json()["error"]["code"] == "unauthorized"


def test_unknown_user_same_error(settings):
    with build_client(settings) as c:
        r = login(c, username="ninguem", password="qualquer-coisa")
        assert r.status_code == 401
        assert r.json()["error"]["message"] == "Credenciais inválidas."


def test_lockout_after_repeated_failures(make_settings):
    from titan.db.migrate import upgrade_head

    s = make_settings(login_max_attempts=3)
    upgrade_head(s.database_url)
    create_user(s)
    with build_client(s) as c:
        for _ in range(3):
            assert login(c, password="errada-errada").status_code == 401
        r = login(c)  # mesmo a senha correta é recusada durante o bloqueio
        assert r.status_code == 429
        assert "Retry-After" in r.headers


def test_cookie_flags(settings):
    create_user(settings)
    with build_client(settings) as c:
        r = login(c)
        cookie = r.headers["set-cookie"].lower()
        assert "httponly" in cookie
        assert "samesite=strict" in cookie
        assert "path=/" in cookie
        # O token não aparece no corpo da resposta.
        assert c.cookies.get("titan_session") not in r.text


def test_expired_session_rejected(settings):
    from datetime import timedelta

    from titan.db.engine import make_engine, make_session_factory
    from titan.db.models import Session, utcnow

    create_user(settings)
    with build_client(settings) as c:
        login(c)
        engine = make_engine(settings.database_url)
        with make_session_factory(engine).begin() as db:
            for sess in db.query(Session).all():
                sess.expires_at = utcnow() - timedelta(seconds=1)
        engine.dispose()
        assert c.get("/api/v1/auth/me").status_code == 401


def test_failed_login_is_audited_without_password(settings):
    from titan.db.engine import make_engine, make_session_factory
    from titan.db.models import AuditEvent

    with build_client(settings) as c:
        login(c, username="intruso", password="senha-tentada-123")
    engine = make_engine(settings.database_url)
    with make_session_factory(engine)() as db:
        evs = db.query(AuditEvent).filter_by(event_type="auth.login_failed").all()
        assert len(evs) == 1
        assert "senha-tentada-123" not in str(evs[0].data)
    engine.dispose()
