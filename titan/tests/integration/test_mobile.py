"""titan ligar-celular: certificados, .env, página de instalação e retorno ao modo local."""

import subprocess
import threading
import urllib.error
import urllib.request

import pytest

from titan import mobile


def test_certificates_cover_lan_and_tailscale(tmp_path):
    ca, crt, key = mobile.make_certificates(["192.168.0.10", "100.101.102.103"], tmp_path / "tls", "teste")
    text = subprocess.run(["openssl", "x509", "-in", str(crt), "-noout", "-text"], capture_output=True, text=True).stdout
    for san in ("IP Address:192.168.0.10", "IP Address:100.101.102.103", "IP Address:127.0.0.1", "DNS:localhost"):
        assert san in text
    ok = subprocess.run(["openssl", "verify", "-CAfile", str(ca), str(crt)], capture_output=True, text=True)
    assert ok.returncode == 0, ok.stderr
    assert oct(key.stat().st_mode & 0o777) == "0o600" and oct((tmp_path / "tls" / "titan-ca.key").stat().st_mode & 0o777) == "0o600"
    assert oct(ca.stat().st_mode & 0o777) == "0o644"  # só o certificado público é legível
    first = (tmp_path / "tls" / "titan-ca.key").read_bytes()
    mobile.make_certificates(["192.168.0.11"], tmp_path / "tls")
    assert (tmp_path / "tls" / "titan-ca.key").read_bytes() == first  # a CA é reaproveitada


def test_env_updates_pass_the_security_rules(tmp_path, make_settings):
    _ca, crt, key = mobile.make_certificates(["192.168.0.10"], tmp_path / "tls")
    up = mobile.env_updates("192.168.0.10", crt, key, tailscale=True)
    assert up["TITAN_ALLOWED_NETWORKS"] == "127.0.0.1/32,::1/128,192.168.0.0/24,100.64.0.0/10"
    s = make_settings(host=up["TITAN_HOST"], allowed_networks=up["TITAN_ALLOWED_NETWORKS"],
                      tls_cert_file=up["TITAN_TLS_CERT_FILE"], tls_key_file=up["TITAN_TLS_KEY_FILE"])
    assert s.tls_enabled and s.lan_enabled and s.secure_cookies


def test_lan_ip_refuses_public_address(monkeypatch):
    class FakeSock:
        def __init__(self, *a): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def connect(self, addr): pass
        def getsockname(self): return ("8.8.8.8", 1234)
    monkeypatch.setattr(mobile.socket, "socket", FakeSock)
    with pytest.raises(mobile.MobileError, match="não é de rede local"):
        mobile.lan_ip()


def _get(url):
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            return r.status, r.headers.get("Content-Type"), r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("Content-Type"), e.read()


def test_install_page_serves_only_public_cert_to_allowed_networks(tmp_path):
    ca, _crt, _key = mobile.make_certificates(["192.168.0.10"], tmp_path / "tls")
    srv = mobile.make_install_server(ca, "https://192.168.0.10:8000", ["127.0.0.1/32"], port=0, host="127.0.0.1")
    port = srv.server_address[1]
    stop = threading.Event()
    t = threading.Thread(target=mobile.serve_install_page, args=(srv, 1, stop), daemon=True)
    t.start()
    try:
        base = f"http://127.0.0.1:{port}"
        code, ctype, body = _get(base + "/instalar")
        assert code == 200 and "Instalar o TITAN" in body.decode() and "https://192.168.0.10:8000" in body.decode()
        code, ctype, body = _get(base + "/titan-ca.crt")
        assert code == 200 and ctype == "application/x-x509-ca-cert" and body == ca.read_bytes()
        for path in ("/titan-ca.key", "/server.key", "/../tls/titan-ca.key", "/api/v1/auth/me"):
            assert _get(base + path)[0] == 404
    finally:
        stop.set()
        t.join(5)
    srv2 = mobile.make_install_server(ca, "https://x", ["10.0.0.0/8"], port=0, host="127.0.0.1")
    t2 = threading.Thread(target=mobile.serve_install_page, args=(srv2, 1, stop := threading.Event()), daemon=True)
    t2.start()
    try:
        assert _get(f"http://127.0.0.1:{srv2.server_address[1]}/instalar")[0] == 403  # fora da rede permitida
    finally:
        stop.set()
        t2.join(5)


def test_cli_on_and_off(tmp_path, monkeypatch, capsys):
    from titan import cli

    monkeypatch.chdir(tmp_path)
    env = tmp_path / ".env"
    env.write_text("TITAN_LOCAL_ONLY=true\n")
    monkeypatch.setattr(mobile, "lan_ip", lambda: "192.168.1.20")
    monkeypatch.setattr("builtins.input", lambda *_: "AUTORIZO")
    assert cli.main(["ligar-celular", "--env-file", str(env), "--sem-pagina"]) == 0
    text = env.read_text()
    assert "TITAN_HOST=0.0.0.0" in text and "192.168.1.0/24" in text and "TITAN_TLS_CERT_FILE=var/tls/server.crt" in text
    assert (tmp_path / "var/tls/titan-ca.crt").exists()
    assert cli.main(["desligar-celular", "--env-file", str(env), "--apagar-certificados"]) == 0
    text = env.read_text()
    assert "TITAN_HOST" not in text and "TITAN_TLS" not in text and not (tmp_path / "var/tls").exists()
    monkeypatch.setattr("builtins.input", lambda *_: "nao")
    assert cli.main(["ligar-celular", "--env-file", str(env), "--sem-pagina"]) == 1
    assert "TITAN_HOST" not in env.read_text()


def test_qr_code_when_segno_installed():
    pytest.importorskip("segno")
    qr = mobile.qr_text("http://192.168.0.10:8001/instalar")
    assert qr and len(qr.splitlines()) > 10
