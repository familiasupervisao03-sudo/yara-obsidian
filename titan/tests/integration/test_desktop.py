"""Apps do TITAN no menu do Linux (titan instalar-app / abrir / parar)."""

import http.server
import os
import stat
import threading

from titan import cli, desktop


def test_desktop_entry_and_browser_commands(tmp_path):
    e = desktop.desktop_entry("central", "/p/.venv/bin/titan", tmp_path, tmp_path / ".env", tmp_path / "i.png")
    assert "Name=TITAN Central" in e and 'Exec="/p/.venv/bin/titan" abrir central --env-file' in e
    assert "Terminal=false" in e and f"Path={tmp_path}" in e
    ff = desktop.browser_command("firefox", "/usr/bin/firefox", "central", "https://localhost:8000", tmp_path)
    assert ff[:3] == ["/usr/bin/firefox", "--no-remote", "--profile"] and "--kiosk" in ff
    assert ff[-1] == "https://localhost:8000/central"
    assert 'user_pref("browser.shell.checkDefaultBrowser", false);' in (tmp_path / "firefox-central/user.js").read_text()
    casa = desktop.browser_command("firefox", "ff", "casa", "https://localhost:8000", tmp_path)
    assert "--new-window" in casa and casa[-1].endswith("/casa")
    cr = desktop.browser_command("chromium", "chromium", "casa", "https://localhost:8000", tmp_path)
    assert "--app=https://localhost:8000/casa" in cr
    assert "--kiosk" in desktop.browser_command("chromium", "chromium", "central", "https://x", tmp_path)


def test_base_url():
    assert desktop.base_url({}) == "http://localhost:8000"
    assert desktop.base_url({"TITAN_TLS_CERT_FILE": "c", "TITAN_PORT": "9000"}) == "https://localhost:9000"


def test_server_up_and_wait():
    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200 if self.path == "/health" else 404)
            self.end_headers()

        def log_message(self, *a):
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        assert desktop.server_up(f"http://127.0.0.1:{srv.server_address[1]}")
    finally:
        srv.shutdown()
    assert not desktop.server_up("http://127.0.0.1:1", timeout=0.5)
    calls = iter([False, False, True])
    assert desktop.wait_up("x", seconds=10, check=lambda u: next(calls))


def test_stop_server_without_pid(tmp_path):
    assert desktop.stop_server(tmp_path / "nao.pid") is False
    (tmp_path / "s.pid").write_text("999999")
    assert desktop.stop_server(tmp_path / "s.pid") is False


def _fake_exe(d, name, body="exit 0"):
    f = d / name
    f.write_text(f"#!/bin/sh\n{body}\n")
    f.chmod(f.stat().st_mode | stat.S_IEXEC)
    return f


def test_instalar_app_puts_three_apps_in_menu(tmp_path, monkeypatch, capsys):
    bins = tmp_path / "bin"
    bins.mkdir()
    _fake_exe(bins, "firefox")
    monkeypatch.setenv("PATH", str(bins))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "home/.local/share"))
    proj = tmp_path / "proj"
    (proj / "var/tls").mkdir(parents=True)
    (proj / "var/tls/titan-ca.crt").write_text("-----BEGIN CERTIFICATE-----\n")
    (proj / ".env").write_text("TITAN_PORT=8000\n")
    assert cli.main(["instalar-app", "--env-file", str(proj / ".env"), "--nao-ao-ligar"]) == 0
    out = capsys.readouterr().out
    apps = tmp_path / "home/.local/share/applications"
    assert sorted(p.name for p in apps.iterdir()) == ["titan-casa.desktop", "titan-central.desktop", "titan-titan.desktop"]
    assert "abrir casa" in (apps / "titan-casa.desktop").read_text()
    assert "sudo apt install libnss3-tools" in out  # sem certutil: explica como resolver
    # com o certutil: o cadeado entra nos perfis dos três apps
    log = tmp_path / "certutil.log"
    _fake_exe(bins, "certutil", f'echo "$@" >> {log}')
    assert cli.main(["instalar-app", "--env-file", str(proj / ".env"), "--ao-ligar"]) == 0
    out = capsys.readouterr().out
    assert "Cadeado do TITAN confiável" in out
    adds = [l for l in log.read_text().splitlines() if l.startswith("-A")]
    assert len(adds) == 3 and all("titan-ca.crt" in l for l in adds)
    assert (tmp_path / "home/.config/autostart/titan-central.desktop").exists()
    assert cli.main(["instalar-app", "--env-file", str(proj / ".env"), "--nao-ao-ligar"]) == 0
    assert not (tmp_path / "home/.config/autostart/titan-central.desktop").exists()


def test_abrir_starts_server_when_down(tmp_path, monkeypatch, capsys):
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / ".env").write_text("TITAN_PORT=8123\n")
    state = {"up": False, "started": None, "opened": None}
    monkeypatch.setattr(desktop, "server_up", lambda url, timeout=2.0: state["up"])

    def start(bin_, project, log, pid):
        state["started"] = (bin_, project)
        state["up"] = True
        return 1
    monkeypatch.setattr(desktop, "start_server", start)
    monkeypatch.setattr(desktop, "find_browser", lambda: ("firefox", "firefox"))
    monkeypatch.setattr("subprocess.Popen", lambda cmd, **kw: state.update(opened=cmd))
    assert cli.main(["abrir", "central", "--env-file", str(proj / ".env")]) == 0
    assert state["started"][1] == proj and state["opened"][-1] == "http://localhost:8123/central"
    assert "ligando em segundo plano" in capsys.readouterr().out
    # já ligado: não liga de novo
    state.update(started=None)
    assert cli.main(["central", "--env-file", str(proj / ".env")]) == 0
    assert state["started"] is None and "--kiosk" in state["opened"]
