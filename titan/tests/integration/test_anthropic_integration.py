"""Chat com a Anthropic via API do TITAN, usando cliente FALSO (sem rede, sem custo)."""

import logging
import stat
from pathlib import Path

import pytest

from tests.conftest import CSRF, build_client, create_user, login
from tests.unit.test_anthropic_provider import KEY, FakeAPIError, FakeClient, response


@pytest.fixture
def paid(make_settings, monkeypatch):
    from titan.db.migrate import upgrade_head
    from titan.models import anthropic_provider

    s = make_settings(model_provider="anthropic", model_name="claude-opus-5-5", local_only=False,
                      allow_external_models=True, allow_paid_apis=True,
                      daily_paid_budget_brl=1.0, usd_brl_rate=5.0, anthropic_api_key=KEY)
    upgrade_head(s.database_url)
    fake = FakeClient(response(text="Resposta do Claude", inp=200, out=100))
    monkeypatch.setattr(anthropic_provider.AnthropicProvider, "_get_client", lambda self: fake)
    create_user(s)
    return s, fake


def test_chat_reply_from_anthropic(paid):
    s, fake = paid
    with build_client(s) as c:
        login(c)
        cid = c.post("/api/v1/conversations", json={}, headers=CSRF).json()["id"]
        body = c.post(f"/api/v1/conversations/{cid}/messages", json={"content": "Oi"},
                      headers=CSRF).json()
        assert body["reply"]["content"] == "Resposta do Claude"
        assert body["reply"]["model_provider"] == "anthropic"
        st = c.get("/api/v1/system/status").json()
        assert st["external_provider_active"] is True
        assert st["paid_apis_blocked"] is False
        assert st["paid_spent_today_brl"] == pytest.approx(0.014)  # (200*4+100*20)/1M*5
        assert "EXTERNO" in {x["name"]: x for x in st["services"]}["model"]["detail"]
        for path in ["/api/v1/settings", "/api/v1/system/status", f"/api/v1/conversations/{cid}"]:
            assert KEY not in c.get(path).text
    assert len(fake.calls) == 1


def test_idempotent_resend_does_not_pay_twice(paid):
    s, fake = paid
    with build_client(s) as c:
        login(c)
        cid = c.post("/api/v1/conversations", json={}, headers=CSRF).json()["id"]
        payload = {"content": "uma vez", "client_request_id": "req-abcdefgh"}
        c.post(f"/api/v1/conversations/{cid}/messages", json=payload, headers=CSRF)
        r2 = c.post(f"/api/v1/conversations/{cid}/messages", json=payload, headers=CSRF).json()
        assert r2["duplicate"] is True and r2["reply"]["content"] == "Resposta do Claude"
    assert len(fake.calls) == 1


def test_provider_error_is_not_presented_as_reply(paid):
    s, fake = paid
    fake.error = FakeAPIError(429)
    with build_client(s) as c:
        login(c)
        cid = c.post("/api/v1/conversations", json={}, headers=CSRF).json()["id"]
        body = c.post(f"/api/v1/conversations/{cid}/messages", json={"content": "Oi"},
                      headers=CSRF).json()
        assert body["reply"] is None
        assert body["model"]["available"] is False and "Limite" in body["model"]["detail"]
        msgs = c.get(f"/api/v1/conversations/{cid}").json()["messages"]
        assert [m["role"] for m in msgs] == ["user"]  # pergunta salva, nada inventado


def test_external_request_is_audited_without_content(paid):
    from titan.db.engine import make_engine, make_session_factory
    from titan.db.models import AuditEvent

    s, _ = paid
    with build_client(s) as c:
        login(c)
        cid = c.post("/api/v1/conversations", json={}, headers=CSRF).json()["id"]
        c.post(f"/api/v1/conversations/{cid}/messages", json={"content": "segredo pessoal"},
               headers=CSRF)
    engine = make_engine(s.database_url)
    with make_session_factory(engine)() as db:
        ev = db.query(AuditEvent).filter_by(event_type="model.external_request").one()
        assert ev.data["provider"] == "anthropic" and "segredo pessoal" not in str(ev.data)
    engine.dispose()


def test_key_redacted_from_logs(paid):
    s, _ = paid
    with build_client(s):
        logging.getLogger("titan.test").warning("chave=%s", KEY)
    content = (Path(s.data_dir) / "logs" / "titan.log").read_text()
    assert KEY not in content


def test_enable_and_disable_commands(tmp_path, monkeypatch, capsys):
    from titan import cli
    from titan.envfile import read_env

    env = tmp_path / ".env"
    env.write_text("TITAN_AUTH_SECRET=abc\nTITAN_MODEL_PROVIDER=none\n# comentário\n")
    answers = iter(["sonnet", "3", "5.8", "autorizo"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt="": KEY)
    assert cli.main(["enable-anthropic", "--env-file", str(env)]) == 0
    out = capsys.readouterr().out
    assert KEY not in out
    values = read_env(env)
    assert values["TITAN_MODEL_PROVIDER"] == "anthropic"
    assert values["TITAN_MODEL_NAME"] == "claude-sonnet-5-5"
    assert values["TITAN_DAILY_PAID_BUDGET_BRL"] == "3.00"
    assert values["ANTHROPIC_API_KEY"] == KEY
    assert values["TITAN_AUTH_SECRET"] == "abc"
    assert "# comentário" in env.read_text()
    assert stat.S_IMODE(env.stat().st_mode) == 0o600
    assert all(stat.S_IMODE(b.stat().st_mode) == 0o600 for b in tmp_path.glob(".env.bak-*"))

    assert cli.main(["disable-external", "--env-file", str(env)]) == 0
    values = read_env(env)
    assert values["TITAN_MODEL_PROVIDER"] == "none"
    assert values["TITAN_ALLOW_PAID_APIS"] == "false"
    assert "ANTHROPIC_API_KEY" not in values


def test_enable_requires_explicit_confirmation(tmp_path, monkeypatch):
    from titan import cli

    env = tmp_path / ".env"
    env.write_text("TITAN_MODEL_PROVIDER=none\n")
    answers = iter(["claude-opus-5-5", "2", "5.8", "sim"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt="": KEY)
    assert cli.main(["enable-anthropic", "--env-file", str(env)]) == 1
    assert env.read_text() == "TITAN_MODEL_PROVIDER=none\n"


def test_enable_rejects_unknown_model(tmp_path, monkeypatch):
    from titan import cli

    env = tmp_path / ".env"
    env.write_text("TITAN_MODEL_PROVIDER=none\n")
    answers = iter(["hauki"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    assert cli.main(["enable-anthropic", "--env-file", str(env)]) == 1
    assert env.read_text() == "TITAN_MODEL_PROVIDER=none\n"


def test_enable_accepts_haiku_alias(tmp_path, monkeypatch):
    from titan import cli
    from titan.envfile import read_env

    env = tmp_path / ".env"
    env.write_text("TITAN_MODEL_PROVIDER=none\n")
    answers = iter(["Haiku", "10", "5.8", "Autorizo"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt="": KEY)
    assert cli.main(["enable-anthropic", "--env-file", str(env)]) == 0
    assert read_env(env)["TITAN_MODEL_NAME"] == "claude-haiku-5-5"
