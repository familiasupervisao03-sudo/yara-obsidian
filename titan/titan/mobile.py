"""Ligar o TITAN ao celular: certificado local (HTTPS), .env e página de instalação.

``titan ligar-celular`` faz, em ordem:
1. descobre o IP do notebook na Wi-Fi (e, com --tailscale, o IP do Tailscale);
2. cria uma autoridade certificadora (CA) só deste notebook e um certificado para
   esses IPs (openssl; a chave da CA nunca sai de var/tls/, permissão 600);
3. ajusta o .env: escuta na rede, só aceita a rede local (e o Tailscale), HTTPS;
4. abre por 15 minutos uma página de instalação SEM cadeado (é o único jeito de o
   celular baixar o cadeado pela primeira vez) que entrega apenas o certificado
   PÚBLICO da CA e instruções; aceita só aparelhos das redes permitidas.

Nada é aberto para a internet: não há encaminhamento de portas nem túnel público.
"""

from __future__ import annotations

import html
import ipaddress
import os
import shutil
import socket
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable, Optional

TLS_DIR = Path("var/tls")
# App Android do TITAN (gerado a partir de apps/android; ver apps/android/README.md).
APK_FILE = Path(__file__).resolve().parents[1] / "apps" / "web" / "public" / "titan.apk"
TAILSCALE_NET = "100.64.0.0/10"
INSTALL_PORT = 8001
INSTALL_MINUTES = 15
ENV_KEYS = ("TITAN_HOST", "TITAN_ALLOWED_NETWORKS", "TITAN_TLS_CERT_FILE", "TITAN_TLS_KEY_FILE")


class MobileError(Exception):
    pass


def lan_ip() -> str:
    """IP do notebook na rede local (o que o roteador deu a ele)."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        try:
            s.connect(("192.0.2.1", 9))  # UDP: só escolhe a interface; nada é enviado
            ip = s.getsockname()[0]
        except OSError as exc:
            raise MobileError("Não encontrei a rede Wi-Fi do notebook. Ele está conectado?") from exc
    addr = ipaddress.ip_address(ip)
    if not addr.is_private or addr.is_loopback:
        raise MobileError(f"O endereço {ip} não é de rede local; o TITAN não deve ser exposto à internet.")
    return ip


def tailscale_ip(run: Callable = subprocess.run) -> Optional[str]:
    if not shutil.which("tailscale"):
        return None
    try:
        out = run(["tailscale", "ip", "-4"], capture_output=True, text=True, timeout=5).stdout.split()
    except (OSError, subprocess.TimeoutExpired):
        return None
    for ip in out:
        try:
            if ipaddress.ip_address(ip) in ipaddress.ip_network(TAILSCALE_NET):
                return ip
        except ValueError:
            continue
    return None


def lan_network(ip: str) -> str:
    return str(ipaddress.ip_network(f"{ip}/24", strict=False))


def _openssl(*args: str) -> None:
    res = subprocess.run(["openssl", *args], capture_output=True, text=True)
    if res.returncode != 0:
        raise MobileError(f"openssl falhou: {res.stderr.strip()[:300]}")


def make_certificates(ips: list[str], tls_dir: Path = TLS_DIR, host_label: str = "") -> tuple[Path, Path, Path]:
    """Cria (ou reaproveita) a CA local e emite o certificado do servidor para ``ips``."""
    if not shutil.which("openssl"):
        raise MobileError("openssl não encontrado. Instale com: sudo apt install openssl")
    tls_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(tls_dir, 0o700)
    ca_key, ca_crt = tls_dir / "titan-ca.key", tls_dir / "titan-ca.crt"
    key, crt = tls_dir / "server.key", tls_dir / "server.crt"
    old = os.umask(0o077)
    try:
        if not (ca_key.exists() and ca_crt.exists()):
            _openssl("req", "-x509", "-newkey", "rsa:3072", "-sha256", "-days", "825", "-nodes",
                     "-keyout", str(ca_key), "-out", str(ca_crt),
                     "-subj", f"/CN=TITAN CA local ({host_label or socket.gethostname()})",
                     "-addext", "basicConstraints=critical,CA:TRUE,pathlen:0",
                     "-addext", "keyUsage=critical,keyCertSign,cRLSign")
        sans = ",".join([f"IP:{ip}" for ip in dict.fromkeys([*ips, "127.0.0.1"])] + ["DNS:localhost"])
        ext = tls_dir / "server.ext"
        ext.write_text("basicConstraints=CA:FALSE\nkeyUsage=critical,digitalSignature,keyEncipherment\n"
                       f"extendedKeyUsage=serverAuth\nsubjectAltName={sans}\n")
        csr = tls_dir / "server.csr"
        _openssl("req", "-newkey", "rsa:2048", "-nodes", "-keyout", str(key), "-out", str(csr), "-subj", f"/CN={ips[0]}")
        _openssl("x509", "-req", "-in", str(csr), "-CA", str(ca_crt), "-CAkey", str(ca_key), "-CAcreateserial",
                 "-out", str(crt), "-days", "397", "-sha256", "-extfile", str(ext))
        csr.unlink(missing_ok=True)
        ext.unlink(missing_ok=True)
    finally:
        os.umask(old)
    for f in tls_dir.iterdir():
        os.chmod(f, 0o600)
    os.chmod(ca_crt, 0o644)  # o certificado da CA é público (vai para o celular)
    return ca_crt, crt, key


def cert_ips(crt: Path) -> set[str]:
    """IPs cobertos pelo certificado do servidor (vazio se não der para ler)."""
    try:
        res = subprocess.run(["openssl", "x509", "-in", str(crt), "-noout", "-ext", "subjectAltName"],
                             capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return set()
    return {part.strip()[len("IP Address:"):] for part in res.stdout.replace("\n", ",").split(",")
            if part.strip().startswith("IP Address:")}


def trust_on_notebook(ca_crt: Path, run: Callable = subprocess.run) -> Optional[str]:
    """Faz o Chrome/Chromium deste usuário confiar na CA local (banco NSS em ~/.pki/nssdb).

    Devolve None se deu certo, ou a explicação do que fazer à mão.
    """
    if not shutil.which("certutil"):
        return "instale com: sudo apt install libnss3-tools  (e rode de novo)"
    db = Path.home() / ".pki" / "nssdb"
    try:
        if not db.exists():
            db.mkdir(parents=True, mode=0o700)
            run(["certutil", "-N", "-d", f"sql:{db}", "--empty-password"], capture_output=True, timeout=20)
        run(["certutil", "-D", "-d", f"sql:{db}", "-n", "TITAN CA local"], capture_output=True, timeout=20)
        res = run(["certutil", "-A", "-d", f"sql:{db}", "-n", "TITAN CA local", "-t", "C,,", "-i", str(ca_crt)],
                  capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"certutil falhou: {exc}"
    return None if res.returncode == 0 else f"certutil falhou: {(res.stderr or '').strip()[:200]}"


def env_updates(ip: str, crt: Path, key: Path, tailscale: bool) -> dict[str, str]:
    nets = ["127.0.0.1/32", "::1/128", lan_network(ip)] + ([TAILSCALE_NET] if tailscale else [])
    return {"TITAN_HOST": "0.0.0.0", "TITAN_ALLOWED_NETWORKS": ",".join(nets),
            "TITAN_TLS_CERT_FILE": str(crt), "TITAN_TLS_KEY_FILE": str(key)}


def qr_text(url: str) -> Optional[str]:
    """QR code para o terminal (precisa da biblioteca opcional 'segno')."""
    try:
        import io

        import segno
    except ImportError:
        return None
    buf = io.StringIO()
    segno.make(url, error="m").terminal(out=buf, compact=True, border=2)
    return buf.getvalue()


# --- página de instalação (temporária, sem cadeado) ---------------------------------

def install_page(app_url: str, ca_name: str, has_apk: bool = False) -> str:
    u = html.escape(app_url)
    apk = (f"""<div class="step"><span class="n">4</span><div><b>Instalar o app TITAN (opcional)</b>
<span class="m">Em vez de "Adicionar à tela inicial", baixe o app. Na primeira vez o Android pede para
permitir instalar apps desta origem: permita só para esta instalação. Ao abrir o app, digite o endereço
<code>{u}</code>.</span><a class="btn" href="/titan.apk" download>BAIXAR O APP (APK)</a></div></div>"""
           if has_apk else "")
    return f"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Instalar o TITAN</title>
<style>
body{{margin:0;font:16px/1.5 system-ui,sans-serif;color:#dff7ff;background:#03070c;padding:20px}}
h1{{font-size:26px;margin:.2em 0 .1em;text-shadow:0 0 14px rgba(62,232,255,.6)}}
.lbl{{font:600 11px ui-monospace,monospace;letter-spacing:.2em;color:#3ee8ff;text-transform:uppercase}}
.step{{display:grid;grid-template-columns:38px 1fr;gap:10px;margin:14px 0;padding:14px;border:1px solid #12303f;background:#07141e}}
.n{{width:34px;height:34px;display:grid;place-items:center;border:1px solid #3ee8ff;color:#3ee8ff;font:800 15px ui-monospace,monospace}}
b{{display:block;font-size:17px}} .m{{color:#86aebe;font-size:14px}}
a.btn{{display:block;text-align:center;margin-top:10px;padding:13px;background:#3ee8ff;color:#00141c;font:700 14px ui-monospace,monospace;
letter-spacing:.1em;text-decoration:none;box-shadow:0 0 18px rgba(62,232,255,.6)}}
code{{color:#3ee8ff}}
</style></head><body>
<div class="lbl">// vinculando dispositivo</div><h1>Instalar o TITAN no celular</h1>
<p class="m">3 passos, uma vez só. Tudo fica entre este celular e o seu notebook.</p>
<div class="step"><span class="n">1</span><div><b>Baixar o cadeado</b>
<span class="m">É o certificado público do seu notebook (não tem senha nem segredo).</span>
<a class="btn" href="/{html.escape(ca_name)}" download>BAIXAR O CADEADO</a></div></div>
<div class="step"><span class="n">2</span><div><b>Instalar o cadeado</b>
<span class="m">Configurações → Segurança (ou "Segurança e privacidade") → Mais configurações → Criptografia e credenciais →
Instalar certificado → <b style="display:inline;font-size:14px">Certificado de CA</b> → escolha <code>{html.escape(ca_name)}</code>.
O Android avisa que "a rede pode ser monitorada": é normal para cadeados instalados por você.</span></div></div>
<div class="step"><span class="n">3</span><div><b>Abrir e instalar o app</b>
<span class="m">Abra o TITAN com cadeado, entre com seu usuário e, no menu do Chrome (⋮), toque em
"Instalar app" ou "Adicionar à tela inicial".</span><a class="btn" href="{u}">ABRIR O TITAN</a>
<span class="m">Se aparecer "conexão não segura", o passo 2 não foi concluído: não continue, volte ao passo 2.</span></div></div>
{apk}
<p class="m">Esta página fecha sozinha em {INSTALL_MINUTES} minutos.</p>
</body></html>"""


def make_install_server(ca_crt: Path, app_url: str, allowed: list[str], port: int = INSTALL_PORT,
                        host: str = "0.0.0.0") -> ThreadingHTTPServer:
    nets = [ipaddress.ip_network(n, strict=False) for n in allowed]
    apk = APK_FILE.read_bytes() if APK_FILE.is_file() else None
    page = install_page(app_url, ca_crt.name, has_apk=apk is not None).encode()
    cert = ca_crt.read_bytes()

    class Handler(BaseHTTPRequestHandler):
        def _deny(self) -> bool:
            ip = ipaddress.ip_address(self.client_address[0])
            return not any(ip in n for n in nets)

        def _send(self, code: int, body: bytes, ctype: str, extra: Optional[dict] = None) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):  # noqa: N802
            if self._deny():
                return self._send(403, b"Fora da rede permitida.", "text/plain; charset=utf-8")
            path = self.path.split("?")[0]
            if path in ("/", "/instalar"):
                return self._send(200, page, "text/html; charset=utf-8")
            if path == f"/{ca_crt.name}":
                return self._send(200, cert, "application/x-x509-ca-cert",
                                  {"Content-Disposition": f'attachment; filename="{ca_crt.name}"'})
            if path == "/titan.apk" and apk is not None:
                return self._send(200, apk, "application/vnd.android.package-archive",
                                  {"Content-Disposition": 'attachment; filename="titan.apk"'})
            return self._send(404, b"Nada aqui.", "text/plain; charset=utf-8")

        def log_message(self, *args):
            pass

    return ThreadingHTTPServer((host, port), Handler)


def serve_install_page(server: ThreadingHTTPServer, minutes: float = INSTALL_MINUTES,
                       stop: Optional[threading.Event] = None) -> None:
    """Mantém a página no ar por ``minutes`` (ou até ``stop``/Ctrl+C) e a fecha."""
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    end = time.monotonic() + minutes * 60
    try:
        while time.monotonic() < end and not (stop and stop.is_set()):
            time.sleep(0.5)
    finally:
        server.shutdown()
        server.server_close()
