import pytest

from titan.config.settings import Settings
from titan.models.providers import ModelUnavailable, get_provider
from titan.policies.model_gate import ProviderBlocked, ProviderInfo, assert_provider_allowed

SECRET = "x" * 40


def s(**kw):
    return Settings(_env_file=None, auth_secret=SECRET, **kw)


def test_paid_provider_blocked_before_call():
    with pytest.raises(ProviderBlocked, match="pago"):
        assert_provider_allowed(ProviderInfo("caro", local=False, paid=True), s())


def test_external_free_provider_blocked_in_local_mode():
    with pytest.raises(ProviderBlocked, match="externo"):
        assert_provider_allowed(ProviderInfo("gratis", local=False, paid=False), s())


def test_local_free_provider_allowed():
    assert_provider_allowed(ProviderInfo("local", local=True, paid=False), s())


def test_paid_blocked_even_if_settings_object_is_tampered():
    cfg = s()
    object.__setattr__(cfg, "allow_paid_apis", True)  # simula adulteração em memória
    with pytest.raises(ProviderBlocked):
        assert_provider_allowed(ProviderInfo("caro", local=True, paid=True), cfg)


def test_none_provider_reports_unavailable():
    with pytest.raises(ModelUnavailable, match="Nenhum modelo"):
        get_provider(s())


def test_mock_only_in_test_env():
    assert get_provider(s(env="test", model_provider="mock")).info.name == "mock"


def test_local_adapters_not_implemented_yet():
    with pytest.raises(ModelUnavailable, match="Fase 4"):
        get_provider(s(model_provider="ollama"))
