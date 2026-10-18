"""Middlewares de segurança: rede autorizada, CSRF e cabeçalhos."""

from __future__ import annotations

import ipaddress
import logging

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from titan.config.settings import Settings

log = logging.getLogger("titan.security")

CSRF_HEADER = "x-titan-request"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
    "connect-src 'self'; font-src 'self'; object-src 'none'; base-uri 'none'; "
    "frame-ancestors 'none'; form-action 'self'; worker-src 'self'; manifest-src 'self'; "
    "media-src 'self' blob:"
)


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message}}, status_code=status)


class NetworkAllowlistMiddleware(BaseHTTPMiddleware):
    """Recusa clientes fora das redes configuradas (TITAN_ALLOWED_NETWORKS).

    Isso NÃO substitui a autenticação: estar na mesma Wi-Fi não prova identidade.
    """

    def __init__(self, app, settings: Settings) -> None:
        super().__init__(app)
        self.networks = settings.networks

    async def dispatch(self, request: Request, call_next) -> Response:
        host = request.client.host if request.client else ""
        try:
            ip = ipaddress.ip_address(host)
        except ValueError:
            return _error(403, "forbidden_network", "Origem de rede não reconhecida.")
        if getattr(ip, "ipv4_mapped", None):
            ip = ip.ipv4_mapped
        if not any(ip in net for net in self.networks):
            log.warning("Cliente recusado fora das redes autorizadas: %s", host)
            return _error(403, "forbidden_network", "Rede não autorizada.")
        return await call_next(request)


class CSRFMiddleware(BaseHTTPMiddleware):
    """Exige cabeçalho customizado em métodos que alteram estado.

    Navegadores não enviam cabeçalhos customizados em requisições entre sites
    sem CORS (que não é habilitado), e o cookie de sessão é SameSite=Strict.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        if request.method not in SAFE_METHODS and request.url.path.startswith("/api/"):
            if request.headers.get(CSRF_HEADER) != "1":
                return _error(403, "csrf_header_missing", "Cabeçalho X-Titan-Request ausente.")
        return await call_next(request)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        response.headers.setdefault("Content-Security-Policy", CSP)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(self), geolocation=()")
        if request.url.path.startswith("/api/"):
            response.headers.setdefault("Cache-Control", "no-store")
        return response
