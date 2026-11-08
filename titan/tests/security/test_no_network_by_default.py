"""Nenhuma conexão de rede externa ocorre durante o uso normal."""

import socket

from tests.conftest import CSRF, build_client, create_user, login


def test_no_outbound_connections(settings, monkeypatch):
    attempts = []
    real_connect = socket.socket.connect

    def guarded(self, address):
        host = address[0] if isinstance(address, tuple) else address
        if isinstance(host, str) and host not in ("127.0.0.1", "::1", "localhost") \
                and self.family in (socket.AF_INET, socket.AF_INET6):
            attempts.append(address)
            raise OSError("conexão externa bloqueada no teste")
        return real_connect(self, address)

    monkeypatch.setattr(socket.socket, "connect", guarded)
    create_user(settings)
    with build_client(settings) as c:
        login(c)
        cid = c.post("/api/v1/conversations", json={}, headers=CSRF).json()["id"]
        c.post(f"/api/v1/conversations/{cid}/messages", json={"content": "oi"}, headers=CSRF)
        c.get("/api/v1/system/status")
        c.get("/api/v1/settings")
    assert attempts == []
