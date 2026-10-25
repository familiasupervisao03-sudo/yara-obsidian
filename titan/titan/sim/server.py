"""Cópia isolada do TITAN para as simulações.

Banco SQLite temporário, pastas temporárias, porta livre, provedor de IA falso
(mock) e diretório de trabalho temporário — o .env real (com a chave da
Anthropic) NUNCA é lido, e variáveis TITAN_*/ANTHROPIC_* do ambiente não passam.
O servidor roda em sessão própria (um Ctrl+C no terminal não o mata no meio) e
recebe SIGTERM se o simulador morrer.
"""

from __future__ import annotations

import ctypes
import http.cookiejar
import json
import os
import secrets
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

PASSWORD = "senha-da-simulacao-123"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _die_with_parent() -> None:  # pragma: no cover - roda no processo filho
    os.setsid()
    try:
        ctypes.CDLL("libc.so.6", use_errno=True).prctl(1, signal.SIGTERM)  # PR_SET_PDEATHSIG
    except OSError:
        pass


@dataclass
class Response:
    status: int
    body: bytes
    headers: dict

    def json(self) -> Any:
        return json.loads(self.body or b"null")

    @property
    def text(self) -> str:
        return self.body.decode("utf-8", "replace")


@dataclass
class Client:
    """Cliente HTTP mínimo (biblioteca padrão) com cookie de sessão e cabeçalho anti-CSRF."""

    base: str
    csrf: bool = True
    timeout: float = 60.0
    extra_headers: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.jar = http.cookiejar.CookieJar()
        # Sem proxy: tudo é local (127.0.0.1).
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}),
                                                  urllib.request.HTTPCookieProcessor(self.jar))

    def request(self, method: str, path: str, body: Any = None, raw: Optional[bytes] = None,
                headers: Optional[dict] = None, csrf: Optional[bool] = None) -> Response:
        h = dict(self.extra_headers)
        data = raw
        if body is not None:
            data = json.dumps(body).encode()
            h["Content-Type"] = "application/json"
        if (self.csrf if csrf is None else csrf) and method not in ("GET", "HEAD"):
            h["X-Titan-Request"] = "1"
        h.update(headers or {})
        req = urllib.request.Request(self.base + path, data=data, method=method, headers=h)
        try:
            with self.opener.open(req, timeout=self.timeout) as r:
                return Response(r.status, r.read(), dict(r.headers))
        except urllib.error.HTTPError as e:
            return Response(e.code, e.read(), dict(e.headers))

    def get(self, path: str, **kw) -> Response:
        return self.request("GET", path, **kw)

    def post(self, path: str, body: Any = None, **kw) -> Response:
        return self.request("POST", path, body, **kw)

    def login(self, username: str, password: str = PASSWORD) -> Response:
        return self.post("/api/v1/auth/login", {"username": username, "password": password})


class IsolatedServer:
    USERS = ("alice", "bob")

    def __init__(self, workdir: Path) -> None:
        self.workdir = workdir
        self.workdir.mkdir(parents=True, exist_ok=True)
        self.port = _free_port()
        self.db_path = workdir / "titan-sim.db"
        self.secret = secrets.token_urlsafe(48)
        self.proc: Optional[subprocess.Popen] = None
        self.log_path = workdir / "servidor.log"
        self.started_at = 0.0
        root = Path(__file__).resolve().parents[2]
        self.env = {k: v for k, v in os.environ.items()
                    if not k.startswith(("TITAN_", "ANTHROPIC_")) and k != "DATABASE_URL"}
        self.env.update({
            "TITAN_ENV": "test", "TITAN_MODEL_PROVIDER": "mock", "TITAN_AUTH_SECRET": self.secret,
            "DATABASE_URL": f"sqlite:///{self.db_path}", "TITAN_DATA_DIR": str(workdir / "data"),
            "TITAN_WORKSPACE_ROOT": str(workdir / "data" / "ws"), "TITAN_BACKUP_DIR": str(workdir / "backups"),
            "TITAN_PORT": str(self.port), "TITAN_HOST": "127.0.0.1", "TITAN_LOG_LEVEL": "WARNING",
            "TITAN_WEB_DIST_DIR": str(workdir / "sem-interface"),
            # Voz: usa os modelos instalados do notebook, se existirem (só leitura).
            "TITAN_VOICE_VOSK_MODEL_DIR": str(root / "var/models/vosk-model-small-pt-0.3"),
            "TITAN_VOICE_PIPER_MODEL": str(root / "var/models/piper/pt_BR-faber-medium.onnx"),
        })
        self.env.setdefault("PYTHONPATH", "")
        self.env["PYTHONPATH"] = os.pathsep.join(p for p in (str(root), str(root / "apps/api"),
                                                             self.env["PYTHONPATH"]) if p)

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def cli(self, *args: str, timeout: float = 300) -> subprocess.CompletedProcess:
        """Roda um comando ``titan`` contra a cópia isolada (ex.: backup)."""
        return subprocess.run([sys.executable, "-m", "titan.cli", *args], cwd=self.workdir, env=self.env,
                              capture_output=True, text=True, timeout=timeout, start_new_session=True)

    def prepare(self) -> None:
        r = self.cli("migrate")
        if r.returncode != 0:
            raise RuntimeError(f"migração falhou: {r.stderr[-500:]}")
        from titan.auth.service import AuthService
        from titan.db.engine import make_engine, make_session_factory

        engine = make_engine(f"sqlite:///{self.db_path}")
        with make_session_factory(engine).begin() as db:
            for u in self.USERS:
                AuthService.create_user(db, u, PASSWORD)
        engine.dispose()

    def start(self, timeout: float = 60) -> None:
        log = open(self.log_path, "ab")
        self.proc = subprocess.Popen([sys.executable, "-m", "titan.cli", "serve"], cwd=self.workdir,
                                     env=self.env, stdout=log, stderr=subprocess.STDOUT,
                                     preexec_fn=_die_with_parent)
        log.close()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.proc.poll() is not None:
                raise RuntimeError(f"servidor encerrou ao iniciar (código {self.proc.returncode}); "
                                   f"ver {self.log_path}")
            try:
                if Client(self.base, timeout=2).get("/ready").status == 200:
                    self.started_at = time.monotonic()
                    return
            except OSError:
                pass
            time.sleep(0.3)
        raise RuntimeError(f"servidor não ficou pronto em {timeout:.0f} s")

    def stop(self, timeout: float = 15) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()
        self.proc = None

    def kill(self) -> None:
        """Queda abrupta (como falta de energia): SIGKILL, sem chance de limpar nada."""
        if self.proc and self.proc.poll() is None:
            self.proc.kill()
            self.proc.wait()
        self.proc = None

    def alive(self) -> bool:
        return bool(self.proc and self.proc.poll() is None)

    def client(self, user: Optional[str] = None) -> Client:
        c = Client(self.base)
        if user:
            r = c.login(user)
            if r.status != 200:
                raise RuntimeError(f"login de {user} falhou: {r.status} {r.text[:200]}")
        return c

    def rss_mb(self) -> Optional[float]:
        return _status_field(self.proc.pid, "VmRSS") if self.alive() else None

    def open_files(self) -> Optional[int]:
        try:
            return len(os.listdir(f"/proc/{self.proc.pid}/fd")) if self.alive() else None
        except OSError:
            return None

    def db_size_kb(self) -> int:
        return sum(p.stat().st_size for p in self.workdir.glob("titan-sim.db*")) // 1024


def _status_field(pid: int, name: str) -> Optional[float]:
    try:
        for line in Path(f"/proc/{pid}/status").read_text().splitlines():
            if line.startswith(name + ":"):
                return int(line.split()[1]) / 1024
    except OSError:
        return None
    return None
