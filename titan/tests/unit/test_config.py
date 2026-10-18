import pytest
from pydantic import ValidationError

from titan.config.settings import EXAMPLE_AUTH_SECRET, Settings

SECRET = "x" * 40


def make(**kw):
    base = dict(env="development", auth_secret=SECRET)
    base.update(kw)
    return Settings(_env_file=None, **base)


def test_defaults_are_local_and_block_paid():
    s = make()
    assert s.local_only is True
    assert s.allow_paid_apis is False
    assert s.daily_paid_budget_brl == 0
    assert s.allow_external_models is False
    assert s.sandbox_enabled is False
    assert s.sandbox_network is False
    assert s.host == "127.0.0.1"
    assert s.model_provider == "none"


@pytest.mark.parametrize(
    "kw,msg",
    [
        ({"allow_paid_apis": True}, "exige TITAN_DAILY_PAID_BUDGET_BRL maior que 0"),
        ({"daily_paid_budget_brl": 5}, "deve ser 0 enquanto TITAN_ALLOW_PAID_APIS=false"),
        ({"allow_paid_apis": True, "daily_paid_budget_brl": 5000}, "entre 0 e 1000"),
        ({"allow_external_models": True}, "LOCAL_ONLY"),
        ({"model_provider": "openai"}, "desconhecido"),
        ({"model_provider": "anthropic"}, "faltam autorizações"),
        ({"model_effort": "turbo"}, "TITAN_MODEL_EFFORT"),
        ({"model_provider": "mock"}, "mock"),
        ({"sandbox_network": True}, "SANDBOX_NETWORK"),
        ({"auth_secret": ""}, "TITAN_AUTH_SECRET"),
        ({"auth_secret": "curto"}, "TITAN_AUTH_SECRET"),
        ({"auth_secret": EXAMPLE_AUTH_SECRET}, "valor de exemplo"),
        ({"host": "0.0.0.0", "allowed_networks": "0.0.0.0/0"}, "qualquer endereço"),
        ({"host": "0.0.0.0", "allowed_networks": "8.8.8.0/24"}, "pública"),
    ],
)
def test_unsafe_config_is_refused(kw, msg):
    with pytest.raises(ValidationError) as exc:
        make(**kw)
    assert msg in str(exc.value)


def test_lan_with_private_network_is_accepted():
    s = make(host="0.0.0.0", allowed_networks="127.0.0.1/32,192.168.0.0/24",
             lan_acknowledge_http_risk=True)
    assert any(str(n) == "192.168.0.0/24" for n in s.networks)


def test_invalid_network_rejected():
    with pytest.raises(ValidationError):
        make(allowed_networks="isso-nao-e-rede")


def test_public_view_has_no_secrets():
    s = make()
    view = s.public_view()
    assert SECRET not in str(view)
    assert "auth_secret" not in view
    assert "database_url" not in view


def test_env_variables_are_read(monkeypatch):
    monkeypatch.setenv("TITAN_AUTH_SECRET", SECRET)
    monkeypatch.setenv("TITAN_PORT", "8123")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///./x.db")
    s = Settings(_env_file=None)
    assert s.port == 8123
    assert s.database_url == "sqlite:///./x.db"


def test_paid_env_variable_blocks_startup(monkeypatch):
    monkeypatch.setenv("TITAN_AUTH_SECRET", SECRET)
    monkeypatch.setenv("TITAN_ALLOW_PAID_APIS", "true")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


ANTHROPIC_OK = dict(
    model_provider="anthropic", model_name="claude-opus-5-5", local_only=False,
    allow_external_models=True, allow_paid_apis=True, daily_paid_budget_brl=5,
    usd_brl_rate=5.5, anthropic_api_key="sk-ant-teste-0000000000000000000000",
)


def test_anthropic_accepted_only_with_every_authorization():
    s = make(**ANTHROPIC_OK)
    assert s.model_provider == "anthropic"
    for key, bad in [("local_only", True), ("allow_external_models", False),
                     ("allow_paid_apis", False), ("usd_brl_rate", 0),
                     ("anthropic_api_key", ""), ("model_name", "")]:
        kw = dict(ANTHROPIC_OK, **{key: bad})
        if key == "allow_paid_apis":
            kw["daily_paid_budget_brl"] = 0
        with pytest.raises(ValidationError):
            make(**kw)


def test_anthropic_key_never_in_public_view():
    view = make(**ANTHROPIC_OK).public_view()
    assert "sk-ant" not in str(view)
    assert view["anthropic_api_key_configured"] is True
    assert view["external_provider_active"] is True


def test_lan_without_https_requires_explicit_ack():
    with pytest.raises(ValidationError, match="sem HTTPS"):
        Settings(_env_file=None, env="development", auth_secret=SECRET, host="0.0.0.0",
                 allowed_networks="192.168.0.0/24")
    s = make(host="0.0.0.0", allowed_networks="192.168.0.0/24", lan_acknowledge_http_risk=True)
    assert s.lan_enabled and not s.tls_enabled and not s.secure_cookies


def test_tls_settings(tmp_path):
    from titan.cli import uvicorn_options

    cert, key = tmp_path / "c.pem", tmp_path / "k.pem"
    cert.write_text("x")
    key.write_text("y")
    s = make(host="0.0.0.0", allowed_networks="192.168.0.0/24", tls_cert_file=cert, tls_key_file=key)
    assert s.tls_enabled and s.secure_cookies
    opts = uvicorn_options(s)
    assert opts["ssl_certfile"] == str(cert) and opts["proxy_headers"] is False
    with pytest.raises(ValidationError, match="juntos"):
        make(tls_cert_file=cert)
    with pytest.raises(ValidationError, match="não encontrado"):
        make(tls_cert_file=tmp_path / "nao.pem", tls_key_file=key)
