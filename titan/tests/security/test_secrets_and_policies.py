"""Segredos não vazam e políticas financeiras/privacidade são aplicadas no backend."""

import logging
from pathlib import Path

from tests.conftest import CSRF, TEST_PASSWORD, TEST_SECRET, build_client, create_user, login


def test_secret_not_in_any_api_response(auth_client):
    cid = auth_client.post("/api/v1/conversations", json={}, headers=CSRF).json()["id"]
    bodies = [
        auth_client.get("/api/v1/settings").text,
        auth_client.get("/api/v1/system/status").text,
        auth_client.get("/api/v1/auth/me").text,
        auth_client.get(f"/api/v1/conversations/{cid}").text,
        auth_client.get("/openapi.json").text,
    ]
    for body in bodies:
        assert TEST_SECRET not in body
        assert TEST_PASSWORD not in body
        assert "password_hash" not in body
        assert "token_hash" not in body


def test_secret_redacted_from_logs(settings):
    with build_client(settings):
        logging.getLogger("titan.test").warning("vazamento %s", TEST_SECRET)
    log_file = Path(settings.data_dir) / "logs" / "titan.log"
    content = log_file.read_text()
    assert "vazamento" in content
    assert TEST_SECRET not in content


def test_data_dirs_are_private(settings):
    with build_client(settings):
        pass
    for d in (settings.data_dir, settings.workspace_root):
        assert (Path(d).stat().st_mode & 0o777) == 0o700


def test_external_provider_cannot_be_selected():
    import pytest
    from pydantic import ValidationError

    from titan.config.settings import Settings

    for provider in ("openai", "anthropic", "gemini", "openrouter"):  # anthropic: sem autorizações
        with pytest.raises(ValidationError):
            Settings(_env_file=None, env="test", model_provider=provider)


def test_settings_endpoint_is_read_only(auth_client):
    r = auth_client.put("/api/v1/settings", json={"allow_paid_apis": True}, headers=CSRF)
    assert r.status_code == 405
    assert auth_client.get("/api/v1/settings").json()["config"]["allow_paid_apis"] is False


def test_errors_are_never_reported_as_success(auth_client):
    r = auth_client.get("/api/v1/conversations/00000000-0000-0000-0000-000000000000")
    assert r.status_code == 404
    assert "error" in r.json()


def test_secret_in_traceback_is_redacted(settings):
    with build_client(settings):
        try:
            raise RuntimeError(f"falha com {TEST_SECRET}")
        except RuntimeError:
            logging.getLogger("titan.test").exception("erro")
    content = (Path(settings.data_dir) / "logs" / "titan.log").read_text()
    assert "RuntimeError" in content and TEST_SECRET not in content
