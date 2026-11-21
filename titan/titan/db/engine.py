"""Criação do engine e sessões do banco (SQLite ou PostgreSQL)."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker


def make_engine(database_url: str) -> Engine:
    if database_url.startswith("sqlite"):
        _ensure_sqlite_dir(database_url)
        engine = create_engine(
            database_url,
            connect_args={"check_same_thread": False, "timeout": 15},
        )

        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_conn, _record):  # pragma: no cover - trivial
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA synchronous=NORMAL")
            cur.execute("PRAGMA busy_timeout=15000")
            cur.close()

        return engine
    # Pool pequeno: hardware modesto e processo único.
    return create_engine(
        database_url, pool_size=3, max_overflow=2, pool_pre_ping=True
    )


def _ensure_sqlite_dir(database_url: str) -> None:
    path = database_url.split("///", 1)[-1]
    if path and path != ":memory:":
        parent = Path(path).expanduser().resolve().parent
        parent.mkdir(parents=True, exist_ok=True, mode=0o700)


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)


@contextmanager
def transaction(factory: sessionmaker[Session]) -> Iterator[Session]:
    """Sessão com commit no sucesso e rollback em qualquer exceção."""
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def ping(engine: Engine) -> None:
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
