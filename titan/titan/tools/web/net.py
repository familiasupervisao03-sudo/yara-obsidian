"""Download seguro de páginas públicas.

* Só http/https, só portas 80/443 (fora a busca local configurada).
* O nome é resolvido UMA vez e TODOS os endereços precisam ser públicos; a
  conexão vai para o endereço já conferido (evita troca de DNS no meio).
* Redirecionamentos são seguidos à mão (no máximo 5), conferindo cada destino.
* Sem cookies, sem credenciais, sem cabeçalhos do usuário; nenhum segredo do
  TITAN é enviado. Tamanho e tempo limitados; só tipos de texto.
"""

from __future__ import annotations

import http.client
import ipaddress
import socket
import ssl
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Optional
from urllib.parse import urljoin, urlsplit

USER_AGENT = "TITAN/0.1 (assistente pessoal local; pesquisa sob pedido do usuario)"
MAX_REDIRECTS = 5
TEXT_TYPES = ("text/html", "text/plain", "application/xhtml+xml", "application/json")

Resolver = Callable[[str, int], list[str]]


class WebError(Exception):
    """Falha ao buscar uma página (mensagem curta, em português, sem segredos)."""

    def __init__(self, message: str, code: str = "fetch_failed") -> None:
        super().__init__(message)
        self.code = code


class BlockedDestination(WebError):
    def __init__(self, message: str) -> None:
        super().__init__(message, "blocked")


@dataclass
class Page:
    url: str  # endereço final, depois dos redirecionamentos
    status: int
    content_type: str
    charset: Optional[str]
    body: bytes

    def text(self) -> str:
        for enc in (self.charset, "utf-8", "latin-1"):
            if not enc:
                continue
            try:
                return self.body.decode(enc)
            except (LookupError, UnicodeDecodeError):
                continue
        return self.body.decode("utf-8", "replace")


def ip_is_public(ip: str) -> bool:
    addr = ipaddress.ip_address(ip)
    if isinstance(addr, ipaddress.IPv6Address):
        # ::ffff:10.0.0.1 e semelhantes: confere o IPv4 embutido.
        if addr.ipv4_mapped is not None:
            return ip_is_public(str(addr.ipv4_mapped))
        if addr.sixtofour is not None or addr.teredo is not None:
            return False
    return addr.is_global and not addr.is_multicast


def system_resolver(force_ipv4: bool) -> Resolver:
    def resolve(host: str, port: int) -> list[str]:
        family = socket.AF_INET if force_ipv4 else socket.AF_UNSPEC
        try:
            infos = socket.getaddrinfo(host, port, family, socket.SOCK_STREAM)
        except socket.gaierror as exc:
            raise WebError(f"Endereço não encontrado: {host}.", "dns") from exc
        return list(dict.fromkeys(info[4][0] for info in infos))
    return resolve


def _split(url: str):
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise BlockedDestination("Só endereços http e https são aceitos.")
    if parts.username or parts.password:
        raise BlockedDestination("Endereços com usuário/senha não são aceitos.")
    host = (parts.hostname or "").rstrip(".").lower()
    if not host:
        raise BlockedDestination("Endereço sem nome de site.")
    try:
        port = parts.port or (443 if parts.scheme == "https" else 80)
    except ValueError as exc:
        raise BlockedDestination("Porta inválida no endereço.") from exc
    return parts, host, port


class _PinnedHTTP(http.client.HTTPConnection):
    def __init__(self, host: str, port: int, ip: str, timeout: float) -> None:
        super().__init__(host, port, timeout=timeout)
        self._ip = ip

    def connect(self) -> None:
        self.sock = socket.create_connection((self._ip, self.port), self.timeout)


class _PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self, host: str, port: int, ip: str, timeout: float) -> None:
        super().__init__(host, port, timeout=timeout, context=ssl.create_default_context())
        self._ip = ip

    def connect(self) -> None:
        raw = socket.create_connection((self._ip, self.port), self.timeout)
        # O certificado é conferido contra o NOME do site, não contra o IP.
        self.sock = self._context.wrap_socket(raw, server_hostname=self.host)


@dataclass
class Fetcher:
    timeout: float = 10.0
    max_bytes: int = 2_000_000
    force_ipv4: bool = True
    resolver: Optional[Resolver] = None
    # Exceção única e explícita: a busca local (SearXNG) configurada pelo usuário.
    trusted_local: frozenset[tuple[str, int]] = frozenset()
    allowed_ports: frozenset[int] = frozenset({80, 443})
    min_interval_per_host: float = 1.0
    _last_hit: dict[str, float] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def __post_init__(self) -> None:
        if self.resolver is None:
            self.resolver = system_resolver(self.force_ipv4)

    def check(self, url: str) -> tuple[str, int, str]:
        """Confere o destino e devolve (host, porta, ip conferido). Não conecta."""
        parts, host, port = _split(url)
        if (host, port) in self.trusted_local:
            ips = self.resolver(host, port)
            if not ips:
                raise WebError(f"Endereço não encontrado: {host}.", "dns")
            return host, port, ips[0]
        if port not in self.allowed_ports:
            raise BlockedDestination("Só as portas padrão da web (80 e 443) são aceitas.")
        if host == "localhost" or host.endswith((".localhost", ".local", ".internal", ".lan",
                                                 ".home.arpa")):
            raise BlockedDestination("Endereços da rede interna não são acessados.")
        ips = self.resolver(host, port)
        if not ips:
            raise WebError(f"Endereço não encontrado: {host}.", "dns")
        bad = [ip for ip in ips if not ip_is_public(ip)]
        if bad:
            # Qualquer endereço interno na resposta do DNS recusa o site inteiro.
            raise BlockedDestination("O site aponta para um endereço interno ou reservado; "
                                     "acesso bloqueado por segurança.")
        return host, port, ips[0]

    def _pace(self, host: str) -> None:
        with self._lock:
            wait = self._last_hit.get(host, 0) + self.min_interval_per_host - time.monotonic()
            self._last_hit[host] = time.monotonic() + max(wait, 0)
        if wait > 0:
            time.sleep(wait)

    def get(self, url: str, accept: str = "text/html,text/plain;q=0.9,*/*;q=0.1",
            deadline: Optional[float] = None) -> Page:
        deadline = deadline or time.monotonic() + self.timeout * 2
        for _ in range(MAX_REDIRECTS + 1):
            parts, _host, _port = _split(url)
            host, port, ip = self.check(url)
            self._pace(host)
            left = deadline - time.monotonic()
            if left <= 0:
                raise WebError("Tempo esgotado ao buscar a página.", "timeout")
            cls = _PinnedHTTPS if parts.scheme == "https" else _PinnedHTTP
            conn = cls(host, port, ip, min(self.timeout, left))
            path = parts.path or "/"
            if parts.query:
                path += "?" + parts.query
            try:
                conn.request("GET", path, headers={
                    "User-Agent": USER_AGENT, "Accept": accept,
                    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.5",
                    "Accept-Encoding": "identity", "Connection": "close"})
                resp = conn.getresponse()
                if resp.status in (301, 302, 303, 307, 308):
                    location = resp.getheader("Location")
                    if not location:
                        raise WebError("Redirecionamento sem destino.")
                    url = urljoin(url, location)
                    continue
                ctype = (resp.getheader("Content-Type") or "").lower()
                media = ctype.split(";")[0].strip()
                if resp.status >= 400:
                    raise WebError(f"O site respondeu com erro {resp.status}.", f"http_{resp.status}")
                if media and not media.startswith(TEXT_TYPES):
                    raise WebError(f"Tipo de conteúdo não suportado ({media}).", "content_type")
                length = resp.getheader("Content-Length")
                if length and length.isdigit() and int(length) > self.max_bytes:
                    raise WebError("Página grande demais.", "too_large")
                body = bytearray()
                while len(body) <= self.max_bytes:
                    if time.monotonic() > deadline:
                        raise WebError("Tempo esgotado ao buscar a página.", "timeout")
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    body += chunk
                if len(body) > self.max_bytes:
                    body = body[: self.max_bytes]  # o começo basta para extrair o texto
                charset = None
                if "charset=" in ctype:
                    charset = ctype.split("charset=")[-1].split(";")[0].strip().strip('"') or None
                return Page(url, resp.status, media, charset, bytes(body))
            except (OSError, http.client.HTTPException, ssl.SSLError) as exc:
                if isinstance(exc, socket.timeout):
                    raise WebError("Tempo esgotado ao buscar a página.", "timeout") from exc
                raise WebError(f"Falha de conexão com {host}.", "connection") from exc
            finally:
                conn.close()
        raise WebError("Redirecionamentos demais.", "redirects")
