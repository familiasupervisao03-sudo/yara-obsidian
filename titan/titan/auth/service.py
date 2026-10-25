"""Autenticação local: usuários, sessões opacas e limitação de tentativas."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
import time
from dataclasses import dataclass
from datetime import timedelta
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session as DBSession

from titan.auth.passwords import (
    DUMMY_HASH,
    MIN_PASSWORD_LENGTH,
    hash_password,
    verify_password,
)
from titan.db.models import Session, User, utcnow

LAST_SEEN_EVERY = timedelta(minutes=1)


class AuthError(Exception):
    pass


class LoginLocked(AuthError):
    def __init__(self, retry_after: int) -> None:
        super().__init__("Muitas tentativas. Aguarde antes de tentar novamente.")
        self.retry_after = retry_after


@dataclass
class IssuedSession:
    token: str
    session: Session
    user: User


class LoginThrottle:
    """Bloqueio temporário por usuário+IP após falhas consecutivas (em memória)."""

    def __init__(self, max_attempts: int, lockout_seconds: int) -> None:
        self.max_attempts = max_attempts
        self.lockout_seconds = lockout_seconds
        self._failures: dict[str, tuple[int, float]] = {}
        self._lock = threading.Lock()

    def check(self, key: str) -> None:
        with self._lock:
            count, until = self._failures.get(key, (0, 0.0))
            now = time.monotonic()
            if count >= self.max_attempts and now < until:
                raise LoginLocked(int(until - now) + 1)
            if count >= self.max_attempts and now >= until:
                self._failures.pop(key, None)

    def fail(self, key: str) -> None:
        with self._lock:
            count, _ = self._failures.get(key, (0, 0.0))
            self._failures[key] = (count + 1, time.monotonic() + self.lockout_seconds)

    def reset(self, key: str) -> None:
        with self._lock:
            self._failures.pop(key, None)


class AuthService:
    def __init__(self, secret: str, session_ttl_hours: int, throttle: LoginThrottle) -> None:
        if not secret:
            raise ValueError("segredo de autenticação vazio")
        self._key = hashlib.sha256(("titan-session:" + secret).encode()).digest()
        self.ttl = timedelta(hours=session_ttl_hours)
        self.throttle = throttle

    def token_hash(self, token: str) -> str:
        return hmac.new(self._key, token.encode(), hashlib.sha256).hexdigest()

    # --- usuários -----------------------------------------------------------

    @staticmethod
    def create_user(db: DBSession, username: str, password: str, role: str = "owner") -> User:
        username = username.strip()
        if not username or len(username) > 64:
            raise AuthError("Nome de usuário inválido.")
        if len(password) < MIN_PASSWORD_LENGTH:
            raise AuthError(f"A senha deve ter ao menos {MIN_PASSWORD_LENGTH} caracteres.")
        if db.scalar(select(User).where(User.username == username)):
            raise AuthError("Usuário já existe.")
        user = User(username=username, password_hash=hash_password(password), role=role)
        db.add(user)
        db.flush()
        return user

    # --- sessões ------------------------------------------------------------

    def login(
        self,
        db: DBSession,
        username: str,
        password: str,
        client_ip: Optional[str],
        user_agent: Optional[str],
    ) -> IssuedSession:
        key = f"{username.lower()}|{client_ip}"
        self.throttle.check(key)
        user = db.scalar(select(User).where(User.username == username))
        # Sempre executa o scrypt para não revelar se o usuário existe.
        ok = verify_password(password, user.password_hash if user else DUMMY_HASH)
        if not user or not ok or not user.is_active:
            self.throttle.fail(key)
            raise AuthError("Credenciais inválidas.")
        self.throttle.reset(key)
        token = secrets.token_urlsafe(32)
        now = utcnow()
        session = Session(
            user_id=user.id,
            token_hash=self.token_hash(token),
            expires_at=now + self.ttl,
            last_seen_at=now,
            client_ip=client_ip,
            user_agent=(user_agent or "")[:256] or None,
        )
        db.add(session)
        db.flush()
        return IssuedSession(token=token, session=session, user=user)

    def resolve(self, db: DBSession, token: Optional[str]) -> Optional[tuple[Session, User]]:
        if not token or len(token) > 128:
            return None
        session = db.scalar(select(Session).where(Session.token_hash == self.token_hash(token)))
        if session is None or session.revoked_at is not None:
            return None
        now = utcnow()
        if session.expires_at <= now:
            return None
        user = db.get(User, session.user_id)
        if user is None or not user.is_active:
            return None
        # No máximo uma gravação por minuto: antes, TODA requisição (até leituras) gravava
        # aqui e disputava a trava do banco sob uso simultâneo (simulação contínua).
        if session.last_seen_at is None or now - session.last_seen_at >= LAST_SEEN_EVERY:
            session.last_seen_at = now
        return session, user

    @staticmethod
    def revoke(db: DBSession, session: Session) -> None:
        session.revoked_at = utcnow()
