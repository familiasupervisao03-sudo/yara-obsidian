"""Verificação ponta a ponta do TITAN neste computador.

Uso (na pasta titan/):  .venv/bin/python scripts/verify_local.py [--skip-tests]

Sobe uma instância TEMPORÁRIA (banco, logs e usuário descartáveis, porta 8799,
somente 127.0.0.1) e verifica: health/ready, interface, login, conversa,
persistência após reiniciar, bloqueios de APIs pagas, porta presa ao loopback,
ausência de conexões externas e erros nos logs. Também confere permissões do
.env real. Não lê nem altera o banco real, e não imprime segredos.
Usa apenas a biblioteca padrão (sem curl/ss).
"""

from __future__ import annotations

import http.cookiejar
import json
import os
import secrets
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PORT = 8799
BASE = f"http://127.0.0.1:{PORT}"
PY = sys.executable

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    results.append((name, ok, detail))
    print(f"[{'OK ' if ok else 'FALHA'}] {name}" + (f" — {detail}" if detail else ""), flush=True)
    return ok


# --- HTTP sem dependências -------------------------------------------------

class Client:
    def __init__(self) -> None:
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))

    def req(self, method: str, path: str, body=None):
        data = json.dumps(body).encode() if body is not None else None
        r = urllib.request.Request(BASE + path, data=data, method=method)
        r.add_header("Accept", "application/json")
        if method != "GET":
            r.add_header("X-Titan-Request", "1")
        if data is not None:
            r.add_header("Content-Type", "application/json")
        try:
            with self.opener.open(r, timeout=10) as resp:
                raw = resp.read()
                return resp.status, raw
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    def json(self, method: str, path: str, body=None):
        status, raw = self.req(method, path, body)
        try:
            return status, json.loads(raw or b"null")
        except ValueError:
            return status, None


# --- inspeção de sockets via /proc -----------------------------------------

def _hex_addr(h: str) -> str:
    ip_hex, port_hex = h.split(":")
    if len(ip_hex) == 8:
        ip = socket.inet_ntop(socket.AF_INET, bytes.fromhex(ip_hex)[::-1])
    else:
        b = bytes.fromhex(ip_hex)
        ip = socket.inet_ntop(socket.AF_INET6, b"".join(b[i:i + 4][::-1] for i in range(0, 16, 4)))
    return f"{ip}:{int(port_hex, 16)}"


def _proc_sockets():
    for name in ("tcp", "tcp6"):
        p = Path("/proc/net") / name
        if not p.exists():
            continue
        for line in p.read_text().splitlines()[1:]:
            f = line.split()
            yield _hex_addr(f[1]), _hex_addr(f[2]), f[3], f[9]


def _is_loopback(addr: str) -> bool:
    ip = addr.rsplit(":", 1)[0]
    return ip.startswith("127.") or ip in ("::1", "::ffff:127.0.0.1") or ip.startswith("::ffff:127.")


def listen_addresses(port: int) -> list[str]:
    return [l for l, _r, st, _i in _proc_sockets() if st == "0A" and l.endswith(f":{port}")]


def external_connections(pid: int) -> list[str]:
    inodes = set()
    fd_dir = Path(f"/proc/{pid}/fd")
    for fd in fd_dir.iterdir() if fd_dir.exists() else []:
        try:
            target = os.readlink(fd)
        except OSError:
            continue
        if target.startswith("socket:["):
            inodes.add(target[8:-1])
    out = []
    for local, remote, st, inode in _proc_sockets():
        # 01 ESTABLISHED, 02 SYN_SENT, 03 SYN_RECV
        if inode in inodes and st in ("01", "02", "03") and not _is_loopback(remote):
            out.append(f"{local} -> {remote}")
    return out


# --- servidor temporário ---------------------------------------------------

def temp_env(tmp: Path) -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith("TITAN_") and k != "DATABASE_URL"}
    env.update({
        "TITAN_ENV": "production",
        "TITAN_HOST": "127.0.0.1",
        "TITAN_PORT": str(PORT),
        "TITAN_ALLOWED_NETWORKS": "127.0.0.1/32,::1/128",
        "DATABASE_URL": f"sqlite:///{tmp / 'titan.db'}",
        "TITAN_DATA_DIR": str(tmp / "var"),
        "TITAN_WORKSPACE_ROOT": str(tmp / "var" / "workspaces"),
        "TITAN_AUTH_SECRET": secrets.token_urlsafe(48),
        "TITAN_MODEL_PROVIDER": "none",
        "TITAN_SANDBOX_ENABLED": "false",
        "TITAN_SANDBOX_NETWORK": "false",
        "TITAN_ALLOW_EXTERNAL_MODELS": "false",
        "TITAN_ALLOW_PAID_APIS": "false",
        "TITAN_DAILY_PAID_BUDGET_BRL": "0",
        "TITAN_LOCAL_ONLY": "true",
        "TITAN_WEB_DIST_DIR": str(ROOT / "apps" / "web" / "dist"),
        "TITAN_LOG_LEVEL": "INFO",
    })
    return env


def start(env: dict, log_path: Path) -> subprocess.Popen:
    log = open(log_path, "ab")
    proc = subprocess.Popen([PY, "-m", "titan.cli", "serve"], cwd=ROOT, env=env,
                            stdout=log, stderr=subprocess.STDOUT)
    deadline = time.time() + 60  # hardware antigo pode demorar
    while time.time() < deadline:
        if proc.poll() is not None:
            break
        try:
            with urllib.request.urlopen(BASE + "/health", timeout=2):
                return proc
        except OSError:
            time.sleep(0.5)
    return proc


def stop(proc: subprocess.Popen) -> None:
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            proc.kill()


def create_temp_user(env: dict, username: str, password: str) -> bool:
    code = (
        "import sys\n"
        "from titan.config.settings import get_settings\n"
        "from titan.db.engine import make_engine, make_session_factory\n"
        "from titan.db.migrate import upgrade_head\n"
        "from titan.auth.service import AuthService\n"
        "s = get_settings(); upgrade_head(s.database_url)\n"
        "e = make_engine(s.database_url)\n"
        "with make_session_factory(e).begin() as db:\n"
        "    AuthService.create_user(db, sys.argv[1], sys.stdin.read())\n"
        "e.dispose()\n"
    )
    r = subprocess.run([PY, "-c", code, username], cwd=ROOT, env=env, input=password,
                       text=True, capture_output=True)
    if r.returncode != 0:
        print(r.stderr[-2000:])
    return r.returncode == 0


# --- etapas ----------------------------------------------------------------

def run_tests() -> None:
    try:
        import pytest  # noqa: F401
    except ImportError:
        check("Testes automatizados", False, "pytest não instalado (use TITAN_EXTRAS=dev no setup)")
        return
    r = subprocess.run([PY, "-m", "pytest", "-p", "no:cacheprovider"], cwd=ROOT,
                       capture_output=True, text=True)
    lines = r.stdout.strip().splitlines()
    last = next((l for l in reversed(lines) if " passed" in l or " failed" in l or " error" in l),
                lines[-1] if lines else "(sem saída)")
    check("Testes automatizados (pytest)", r.returncode == 0, last)
    if r.returncode != 0:
        print(r.stdout[-4000:])


def check_real_config() -> None:
    env_file = ROOT / ".env"
    if not env_file.exists():
        check(".env real existe", False, "execute scripts/setup.sh")
        return
    mode = stat.S_IMODE(env_file.stat().st_mode)
    check(".env real com permissão 600", mode == 0o600, oct(mode))
    r = subprocess.run(["git", "check-ignore", "-q", str(env_file)], cwd=ROOT)
    check(".env ignorado pelo Git", r.returncode == 0)
    r = subprocess.run([PY, "-m", "titan.cli", "check-config"], cwd=ROOT,
                       capture_output=True, text=True)
    out = r.stdout
    check("Configuração real válida", r.returncode == 0, (r.stderr or "").strip()[-300:])
    for key, expected in [("allow_paid_apis", "False"), ("daily_paid_budget_brl", "0.0"),
                          ("allow_external_models", "False"), ("local_only", "True"),
                          ("sandbox_enabled", "False"), ("host", "127.0.0.1"),
                          ("model_provider", "none")]:
        line = next((l for l in out.splitlines() if l.startswith(key + " =")), "")
        check(f"config real: {key} = {expected}", line.endswith("= " + expected), line or "ausente")
    data_dir = ROOT / "var"
    if data_dir.exists():
        mode = stat.S_IMODE(data_dir.stat().st_mode)
        check("Pasta de dados var/ com permissão 700", mode == 0o700, oct(mode))


def e2e() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="titan-verify-"))
    os.chmod(tmp, 0o700)
    env = temp_env(tmp)
    log_path = tmp / "server.log"
    user, password = "verificador", secrets.token_urlsafe(16)
    proc = None
    try:
        if not check("Instância temporária: migração e usuário", create_temp_user(env, user, password)):
            return
        t0 = time.time()
        proc = start(env, log_path)
        if not check("Servidor iniciou", proc.poll() is None,
                     f"{time.time() - t0:.1f}s até /health"):
            print(log_path.read_text()[-3000:])
            return

        listens = listen_addresses(PORT)
        check("Porta escuta só no loopback", bool(listens) and all(_is_loopback(a) for a in listens),
              ", ".join(listens))

        c = Client()
        st, body = c.json("GET", "/ready")
        check("/ready", st == 200 and body and body.get("status") == "ready", str(st))
        st, raw = c.req("GET", "/")
        ui = st == 200 and b'<div id="root">' in raw
        check("Interface web servida", ui,
              "" if ui else "interface não compilada (npm run build) — API funciona sem ela")
        st, _ = c.json("GET", "/api/v1/conversations")
        check("Rotas exigem login", st == 401, str(st))
        st, _ = c.json("POST", "/api/v1/auth/login", {"username": user, "password": "senha-errada-x"})
        check("Senha errada recusada", st == 401, str(st))
        st, _ = c.json("POST", "/api/v1/auth/login", {"username": user, "password": password})
        check("Login", st == 200, str(st))
        st, settings = c.json("GET", "/api/v1/settings")
        pol = (settings or {}).get("policies", {})
        check("APIs pagas bloqueadas (servidor)", pol.get("paid_apis") == "blocked"
              and pol.get("daily_paid_budget_brl") == 0, json.dumps(pol)[:200])
        check("Modelos externos bloqueados (servidor)", pol.get("external_models") == "blocked")
        st, conv = c.json("POST", "/api/v1/conversations", {"title": "verificação"})
        cid = (conv or {}).get("id")
        marker = f"persistencia-{secrets.token_hex(4)}"
        st2, msg = c.json("POST", f"/api/v1/conversations/{cid}/messages", {"content": marker})
        check("Conversa e mensagem gravadas", st == 201 and st2 == 201, f"{st}/{st2}")
        check("Sem modelo, nenhuma resposta inventada",
              (msg or {}).get("reply") is None and not (msg or {}).get("model", {}).get("available"))

        ext = external_connections(proc.pid)
        stop(proc)
        proc = start(env, log_path)  # reinicialização
        check("Servidor reiniciou", proc.poll() is None)
        c2 = Client()
        c2.json("POST", "/api/v1/auth/login", {"username": user, "password": password})
        st, detail = c2.json("GET", f"/api/v1/conversations/{cid}")
        contents = [m["content"] for m in (detail or {}).get("messages", [])]
        check("Persistência após reiniciar", st == 200 and contents == [marker], str(contents))
        st, status = c2.json("GET", "/api/v1/system/status")
        check("Cadeia de auditoria íntegra", bool(status) and status.get("audit_chain_ok") is True)
        ext += external_connections(proc.pid)
        check("Nenhuma conexão externa do servidor", not ext, "; ".join(ext))
        stop(proc)
        proc = None

        log_text = (tmp / "var" / "logs" / "titan.log").read_text(errors="replace") \
            if (tmp / "var" / "logs" / "titan.log").exists() else ""
        log_text += log_path.read_text(errors="replace")
        bad = [l for l in log_text.splitlines() if " ERROR " in l or "Traceback" in l or " CRITICAL " in l]
        check("Logs sem erros", not bad, bad[0][:200] if bad else "")
        check("Segredo de sessão ausente dos logs", env["TITAN_AUTH_SECRET"] not in log_text
              and password not in log_text)
    finally:
        if proc is not None:
            stop(proc)
        shutil.rmtree(tmp, ignore_errors=True)


def main() -> int:
    print(f"TITAN — verificação local em {ROOT}\n")
    if "--skip-tests" not in sys.argv:
        run_tests()
    check_real_config()
    e2e()
    failed = [n for n, ok, _ in results if not ok]
    print(f"\nResumo: {len(results) - len(failed)} OK, {len(failed)} falha(s).")
    for n in failed:
        print(f"  - {n}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
