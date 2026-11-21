from titan.core.redaction import REDACTED, redact, redact_text, register_secret


def test_sensitive_keys_redacted_recursively():
    data = {"user": "a", "password": "p", "nested": {"api_key": "k", "ok": 1}, "list": [{"token": "t"}]}
    out = redact(data)
    assert out["password"] == REDACTED
    assert out["nested"]["api_key"] == REDACTED
    assert out["nested"]["ok"] == 1
    assert out["list"][0]["token"] == REDACTED
    assert out["user"] == "a"


def test_secret_patterns_in_text():
    text = "chave sk-abcdefghijklmnopqrstuvwx e ghp_abcdefghijklmnopqrstuvwxyz e Bearer abc.def.ghijkl"
    out = redact_text(text)
    assert "sk-abc" not in out and "ghp_" not in out and "abc.def" not in out


def test_database_password_in_url():
    out = redact_text("postgresql+psycopg://titan:supersenha@localhost/titan")
    assert "supersenha" not in out
    assert "titan:" in out and "@localhost" in out


def test_registered_secret_redacted():
    register_secret("valor-literal-secreto-123")
    assert "valor-literal" not in redact_text("x valor-literal-secreto-123 y")
