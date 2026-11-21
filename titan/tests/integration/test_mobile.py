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


def test_install_page_offers_the_app_when_built(tmp_path, monkeypatch):
    apk = tmp_path / "titan.apk"
    apk.write_bytes(b"PK\x03\x04 apk falso")
    monkeypatch.setattr(mobile, "APK_FILE", apk)
    casa = tmp_path / "casa.apk"
    casa.write_bytes(b"PK\x03\x04 apk da casa")
    monkeypatch.setattr(mobile, "CASA_APK_FILE", casa)
    central = tmp_path / "central.apk"
    central.write_bytes(b"PK\x03\x04 apk da central")
    monkeypatch.setattr(mobile, "CENTRAL_APK_FILE", central)
    ca, _crt, _key = mobile.make_certificates(["192.168.0.10"], tmp_path / "tls")
    srv = mobile.make_install_server(ca, "https://192.168.0.10:8000", ["127.0.0.1/32"], port=0, host="127.0.0.1")
    stop = threading.Event()
    t = threading.Thread(target=mobile.serve_install_page, args=(srv, 1, stop), daemon=True)
    t.start()
    try:
        base = f"http://127.0.0.1:{srv.server_address[1]}"
        assert "BAIXAR O APP (APK)" in _get(base + "/instalar")[2].decode()
        code, ctype, body = _get(base + "/titan.apk")
        assert code == 200 and ctype == "application/vnd.android.package-archive" and body == apk.read_bytes()
        page = _get(base + "/instalar")[2].decode()
        assert "BAIXAR O TITAN CASA (APK)" in page and "titancasa://configurar?s=" in page
        code, ctype, body = _get(base + "/casa.apk")
        assert code == 200 and ctype == "application/vnd.android.package-archive" and body == casa.read_bytes()
        assert "BAIXAR O TITAN CENTRAL (APK)" in page and "titancentral://configurar?s=" in page
        code, ctype, body = _get(base + "/central.apk")
        assert code == 200 and body == central.read_bytes()
    finally:
        stop.set()
        t.join(5)
    monkeypatch.setattr(mobile, "APK_FILE", tmp_path / "nao-existe.apk")
    assert "BAIXAR O APP" not in mobile.install_page("https://x", "titan-ca.crt", has_apk=False)
    assert "TITAN CASA" not in mobile.install_page("https://x", "titan-ca.crt", has_apk=True)


def test_ligar_one_command_prepares_both_and_starts_server(tmp_path, monkeypatch, capsys):
    from titan import cli

    monkeypatch.chdir(tmp_path)
    env = tmp_path / ".env"
    env.write_text("TITAN_LOCAL_ONLY=true\nTITAN_PORT=8000\n")
    ip = {"v": "192.168.1.20"}
    monkeypatch.setattr(mobile, "lan_ip", lambda: ip["v"])
    monkeypatch.setattr(mobile, "trust_on_notebook", lambda ca: None)
    served = []
    monkeypatch.setattr(cli, "cmd_serve", lambda a: served.append(a) or 0)
    monkeypatch.setattr("builtins.input", lambda *_: "AUTORIZO")
    args = ["ligar", "--env-file", str(env), "--sem-pagina", "--sem-navegador"]
    assert cli.main(args) == 0 and len(served) == 1
    out = capsys.readouterr().out
    assert "https://localhost:8000" in out and "https://192.168.1.20:8000" in out
    assert "TITAN_TLS_CERT_FILE=var/tls/server.crt" in env.read_text()
    crt = tmp_path / "var/tls/server.crt"
    assert "192.168.1.20" in mobile.cert_ips(crt)

    # Segunda vez: não pergunta nada, não mexe no .env nem no cadeado.
    monkeypatch.setattr("builtins.input", lambda *_: pytest.fail("não deveria perguntar"))
    before, mtime = env.read_text(), crt.stat().st_mtime_ns
    assert cli.main(args) == 0 and len(served) == 2
    assert env.read_text() == before and crt.stat().st_mtime_ns == mtime

    # Mudou de IP: renova só o certificado do servidor (a CA do celular continua).
    ca_before = (tmp_path / "var/tls/titan-ca.crt").read_bytes()
    ip["v"] = "10.0.0.7"
    assert cli.main(args) == 0
    assert "10.0.0.7" in mobile.cert_ips(crt) and "10.0.0.0/24" in env.read_text()
    assert (tmp_path / "var/tls/titan-ca.crt").read_bytes() == ca_before


def test_ligar_refused_changes_nothing(tmp_path, monkeypatch):
    from titan import cli

    monkeypatch.chdir(tmp_path)
    env = tmp_path / ".env"
    env.write_text("TITAN_LOCAL_ONLY=true\n")
    monkeypatch.setattr(mobile, "lan_ip", lambda: "192.168.1.20")
    monkeypatch.setattr(cli, "cmd_serve", lambda a: pytest.fail("não deveria ligar"))
    monkeypatch.setattr("builtins.input", lambda *_: "nao")
    assert cli.main(["ligar", "--env-file", str(env), "--sem-pagina", "--sem-navegador"]) == 1
    assert env.read_text() == "TITAN_LOCAL_ONLY=true\n"


def test_ligar_uses_tailscale_automatically_and_page_configures_app(tmp_path, monkeypatch, capsys):
    from titan import cli

    monkeypatch.chdir(tmp_path)
    env = tmp_path / ".env"
    env.write_text("TITAN_LOCAL_ONLY=true\nTITAN_PORT=8000\n")
    monkeypatch.setattr(mobile, "lan_ip", lambda: "192.168.1.20")
    ts = {"ip": None}
    monkeypatch.setattr(mobile, "tailscale_ip", lambda: ts["ip"])
    monkeypatch.setattr(mobile, "trust_on_notebook", lambda ca: None)
    monkeypatch.setattr(cli, "cmd_serve", lambda a: 0)
    monkeypatch.setattr("builtins.input", lambda *_: "AUTORIZO")
    args = ["ligar", "--env-file", str(env), "--sem-pagina", "--sem-navegador"]
    assert cli.main(args) == 0
    out = capsys.readouterr().out
    assert "FORA DE CASA" in out and "tailscale up" in out  # ensina a ligar
    assert mobile.TAILSCALE_NET not in env.read_text()
    # Tailscale ligado depois: sem flag, entra sozinho (sem perguntar de novo).
    ts["ip"] = "100.101.102.103"
    monkeypatch.setattr("builtins.input", lambda *_: pytest.fail("não deveria perguntar"))
    assert cli.main(args) == 0
    out = capsys.readouterr().out
    assert "EM QUALQUER LUGAR (Tailscale):  https://100.101.102.103:8000" in out
    assert "Wi-Fi de casa (reserva):         https://192.168.1.20:8000" in out
    assert mobile.TAILSCALE_NET in env.read_text()
    assert "100.101.102.103" in mobile.cert_ips(tmp_path / "var/tls/server.crt")
    # --sem-tailscale tira a rede do Tailscale.
    assert cli.main(args + ["--sem-tailscale"]) == 0
    assert mobile.TAILSCALE_NET not in env.read_text()


def test_install_page_has_one_tap_app_config(tmp_path):
    page = mobile.install_page("https://100.1.2.3:8000", "titan-ca.crt", has_apk=True, alt_url="https://192.168.1.20:8000")
    assert "titan://configurar?s=https%3A%2F%2F100.1.2.3%3A8000&amp;alt=https%3A%2F%2F192.168.1.20%3A8000" in page
    assert "CONFIGURAR O APP SOZINHO" in page and "qualquer lugar" in page
