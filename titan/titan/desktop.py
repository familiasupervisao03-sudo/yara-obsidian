"""Apps do TITAN no menu do Linux: TITAN, TITAN Casa e TITAN Central.

Clicou no ícone → se o servidor estiver desligado, ele liga em segundo plano → o app abre
numa janela própria (a Central em tela cheia). Cada app usa um perfil de navegador só dele,
que confia no cadeado do TITAN (a CA local), então não aparece aviso de segurança mesmo
quando o certificado do servidor é refeito.
"""

from __future__ import annotations

import os
import shutil
import ssl
import subprocess
import time
import urllib.request
from pathlib import Path
from typing import Optional

APPS = {
    "titan": {"name": "TITAN", "path": "/", "icon": "main", "comment": "IA pessoal do seu notebook"},
    "casa": {"name": "TITAN Casa", "path": "/casa", "icon": "casa", "comment": "Aparelhos, cenas e voz da casa"},
    "central": {"name": "TITAN Central", "path": "/central", "icon": "central",
                "comment": "A tela da nave: núcleo, voz, casa, metas e alertas"},
}
FIREFOX_PREFS = {
    # perfil limpo, sem telas de boas-vindas nem "restaurar sessão"
    "browser.shell.checkDefaultBrowser": False,
    "browser.aboutwelcome.enabled": False,
    "browser.startup.homepage_override.mstone": "ignore",
    "startup.homepage_welcome_url": "",
    "browser.sessionstore.resume_from_crash": False,
    "datareporting.policy.dataSubmissionEnabled": False,
    "toolkit.telemetry.reportingpolicy.firstRun": False,
    "browser.tabs.warnOnClose": False,
    "browser.warnOnQuit": False,
}


def base_url(env: dict) -> str:
    scheme = "https" if env.get("TITAN_TLS_CERT_FILE") else "http"
    return f"{scheme}://localhost:{env.get('TITAN_PORT', '8000')}"


def server_up(url: str, timeout: float = 2.0) -> bool:
    """O servidor responde? (só olha /health no próprio notebook; não precisa do cadeado)."""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        with urllib.request.urlopen(f"{url}/health", timeout=timeout, context=ctx) as r:
            return r.status == 200
    except Exception:
        return False


def start_server(titan_bin: str, project: Path, log: Path, pid_file: Path) -> int:
    """Liga `titan serve` em segundo plano (continua rodando depois que o app fecha)."""
    log.parent.mkdir(parents=True, exist_ok=True)
    out = open(log, "ab")
    proc = subprocess.Popen([titan_bin, "serve"], cwd=project, stdout=out, stderr=subprocess.STDOUT,
                            stdin=subprocess.DEVNULL, start_new_session=True)
    pid_file.write_text(str(proc.pid))
    return proc.pid


def wait_up(url: str, seconds: float = 45, check=None) -> bool:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if (check or server_up)(url):
            return True
        time.sleep(1)
    return False


def stop_server(pid_file: Path) -> bool:
    try:
        pid = int(pid_file.read_text().strip())
    except (OSError, ValueError):
        return False
    try:
        os.killpg(pid, 15)
    except ProcessLookupError:
        pid_file.unlink(missing_ok=True)
        return False
    except PermissionError:
        return False
    pid_file.unlink(missing_ok=True)
    return True


# --- navegador -----------------------------------------------------------------------------

def find_browser() -> Optional[tuple[str, str]]:
    """("chromium", exe) ou ("firefox", exe). Chromium tem janela de app sem barra de endereço."""
    for kind, names in (("chromium", ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable")),
                        ("firefox", ("firefox",))):
        for n in names:
            exe = shutil.which(n)
            if exe:
                return kind, exe
    return None


def prepare_firefox_profile(profile: Path) -> None:
    profile.mkdir(parents=True, exist_ok=True)
    lines = []
    for k, v in FIREFOX_PREFS.items():
        val = "true" if v is True else "false" if v is False else f'"{v}"'
        lines.append(f'user_pref("{k}", {val});')
    (profile / "user.js").write_text("\n".join(lines) + "\n")


def browser_command(kind: str, exe: str, app: str, url: str, profiles: Path) -> list[str]:
    full = url + APPS[app]["path"]
    kiosk = app == "central"
    if kind == "chromium":
        data = profiles / f"chromium-{app}"
        cmd = [exe, f"--user-data-dir={data}", "--no-first-run", "--no-default-browser-check"]
        return cmd + (["--kiosk", full] if kiosk else [f"--app={full}"])
    profile = profiles / f"firefox-{app}"
    prepare_firefox_profile(profile)
    return [exe, "--no-remote", "--profile", str(profile)] + (["--kiosk"] if kiosk else ["--new-window"]) + [full]


def trust_ca(ca: Path, profiles: Path, kind: str) -> list[str]:
    """Põe o cadeado do TITAN (CA local) como confiável nos perfis dos apps. Usa o certutil
    (pacote libnss3-tools). Devolve o que foi feito; lista vazia = certutil não instalado."""
    certutil = shutil.which("certutil")
    if not certutil or not ca.is_file():
        return []
    dbs: list[Path] = []
    if kind == "firefox":
        for app in APPS:
            p = profiles / f"firefox-{app}"
            prepare_firefox_profile(p)
            dbs.append(p)
    else:
        dbs.append(Path.home() / ".pki" / "nssdb")  # o Chromium no Linux usa este banco
    done = []
    for db in dbs:
        db.mkdir(parents=True, exist_ok=True)
        if not (db / "cert9.db").exists():
            subprocess.run([certutil, "-N", "--empty-password", "-d", f"sql:{db}"], capture_output=True)
        r = subprocess.run([certutil, "-A", "-n", "TITAN (CA local)", "-t", "C,,", "-i", str(ca), "-d", f"sql:{db}"],
                           capture_output=True, text=True)
        done.append(f"{db}: {'ok' if r.returncode == 0 else r.stderr.strip()[:120]}")
    return done


def desktop_entry(app: str, titan_bin: str, project: Path, env_file: Path, icon: Path) -> str:
    a = APPS[app]
    return (
        "[Desktop Entry]\n"
        "Type=Application\n"
        f"Name={a['name']}\n"
        f"Comment={a['comment']}\n"
        f'Exec="{titan_bin}" abrir {app} --env-file "{env_file}"\n'
        f"Path={project}\n"
        f"Icon={icon}\n"
        "Terminal=false\n"
        "Categories=Utility;\n"
        f"StartupWMClass=titan-{app}\n"
    )
