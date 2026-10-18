"""Critérios de aceitação da Fase 1."""

from pathlib import Path

from tests.conftest import CSRF, build_client, create_user, login

ROOT = Path(__file__).resolve().parents[2]


def _parse_env(path: Path) -> dict:
    values = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            values[k.strip()] = v.strip()
    return values


def test_env_example_is_safe_and_documented():
    env = _parse_env(ROOT / ".env.example")
    required = [
        "TITAN_ENV", "TITAN_HOST", "TITAN_PORT", "DATABASE_URL", "TITAN_AUTH_SECRET",
        "TITAN_WORKSPACE_ROOT", "TITAN_SANDBOX_ENABLED", "TITAN_SANDBOX_NETWORK",
        "TITAN_MAX_RUNTIME_SECONDS", "TITAN_MAX_REPAIR_ATTEMPTS", "TITAN_MODEL_PROVIDER",
        "TITAN_MODEL_NAME", "TITAN_ALLOW_PAID_APIS", "TITAN_DAILY_PAID_BUDGET_BRL",
        "TITAN_LOG_LEVEL", "TITAN_DEPLOYMENT_MODE", "TITAN_LOCAL_ONLY",
        "TITAN_ALLOW_EXTERNAL_MODELS",
    ]
    for key in required:
        assert key in env, key
    assert env["TITAN_ALLOW_PAID_APIS"] == "false"
    assert env["TITAN_DAILY_PAID_BUDGET_BRL"] == "0"
    assert env["TITAN_ALLOW_EXTERNAL_MODELS"] == "false"
    assert env["TITAN_LOCAL_ONLY"] == "true"
    assert env["TITAN_SANDBOX_NETWORK"] == "false"
    assert env["TITAN_HOST"] == "127.0.0.1"


def test_env_files_are_gitignored():
    ignore = (ROOT / ".gitignore").read_text().splitlines()
    assert ".env" in ignore
    assert "var/" in ignore


def test_documented_config_starts_api(tmp_path, monkeypatch):
    """A API inicia com o .env.example (trocando só o segredo e os caminhos)."""
    from titan.config.settings import Settings
    from titan.db.migrate import upgrade_head

    env = _parse_env(ROOT / ".env.example")
    env["TITAN_AUTH_SECRET"] = "s" * 48
    env["DATABASE_URL"] = f"sqlite:///{tmp_path / 'titan.db'}"
    env["TITAN_DATA_DIR"] = str(tmp_path / "data")
    env["TITAN_WORKSPACE_ROOT"] = str(tmp_path / "data" / "ws")
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    s = Settings(_env_file=None)
    upgrade_head(s.database_url)
    with build_client(s) as c:
        assert c.get("/health").status_code == 200
        assert c.get("/ready").status_code == 200


def test_conversations_persist_after_restart(settings):
    create_user(settings)
    with build_client(settings) as c:
        login(c)
        cid = c.post("/api/v1/conversations", json={"title": "persistente"}, headers=CSRF).json()["id"]
        c.post(f"/api/v1/conversations/{cid}/messages", json={"content": "lembre-se"}, headers=CSRF)
    # Nova instância da aplicação (simula reinicialização do servidor).
    with build_client(settings) as c2:
        login(c2)
        detail = c2.get(f"/api/v1/conversations/{cid}").json()
        assert detail["title"] == "persistente"
        assert [m["content"] for m in detail["messages"]] == ["lembre-se"]


def test_audit_reconstructs_actions(settings):
    from titan.audit.log import verify_chain
    from titan.db.engine import make_engine, make_session_factory
    from titan.db.models import AuditEvent

    create_user(settings)
    with build_client(settings) as c:
        login(c)
        cid = c.post("/api/v1/conversations", json={}, headers=CSRF).json()["id"]
        c.post(f"/api/v1/conversations/{cid}/messages", json={"content": "x"}, headers=CSRF)
        c.post("/api/v1/auth/logout", headers=CSRF)
    engine = make_engine(settings.database_url)
    with make_session_factory(engine)() as db:
        types = [e.event_type for e in db.query(AuditEvent).order_by(AuditEvent.id)]
        assert types == ["auth.login", "conversation.created", "message.created", "auth.logout"]
        assert verify_chain(db) == (True, None)
    engine.dispose()
