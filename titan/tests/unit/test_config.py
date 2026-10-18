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
        ({"allow_paid_apis": True}, "APIs pagas"),
        ({"daily_paid_budget_brl": 5}, "DAILY_PAID_BUDGET"),
        ({"allow_external_models": True}, "LOCAL_ONLY"),
        ({"model_provider": "openai"}, "não é local"),
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
    s = make(host="0.0.0.0", allowed_networks="127.0.0.1/32,192.168.0.0/24")
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
