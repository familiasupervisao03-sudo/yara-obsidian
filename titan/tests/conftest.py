"""Fixtures compartilhadas.

Os testes rodam com SQLite temporário. Se TITAN_TEST_DATABASE_URL apontar para
um PostgreSQL de testes, os testes marcados com ``db_url`` rodam também nele.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable

import pytest
from sqlalchemy import MetaData, create_engine
from starlette.testclient import TestClient

from titan.config.settings import Settings
from titan.db.migrate import upgrade_head

PG_URL = os.environ.get("TITAN_TEST_DATABASE_URL")
TEST_SECRET = "segredo-de-teste-com-mais-de-32-caracteres-0123456789"
TEST_PASSWORD = "senha-forte-de-teste"
CSRF = {"X-Titan-Request": "1"}
LOCAL_CLIENT = ("127.0.0.1", 50000)


def _reset_postgres(url: str) -> None:
    engine = create_engine(url)
    meta = MetaData()
    meta.reflect(bind=engine)
    meta.drop_all(bind=engine)
    with engine.begin() as conn:
        conn.exec_driver_sql("DROP TABLE IF EXISTS alembic_version")
    engine.dispose()


@pytest.fixture(params=["sqlite"] + (["postgres"] if PG_URL else []))
def db_url(request, tmp_path: Path) -> str:
    if request.param == "postgres":
        _reset_postgres(PG_URL)
        return PG_URL
    return f"sqlite:///{tmp_path / 'titan.db'}"


@pytest.fixture
def make_settings(tmp_path: Path, db_url: str) -> Callable[..., Settings]:
    def factory(**overrides: Any) -> Settings:
        values: dict[str, Any] = dict(
            env="test",
            database_url=db_url,
            data_dir=tmp_path / "data",
            workspace_root=tmp_path / "data" / "workspaces",
            auth_secret=TEST_SECRET,
            web_dist_dir=tmp_path / "no-web",
            log_level="WARNING",
            task_runner="inline",
        )
        values.update(overrides)
        return Settings(_env_file=None, **values)

    return factory


@pytest.fixture
def settings(make_settings) -> Settings:
    s = make_settings()
    upgrade_head(s.database_url)
    return s


def build_client(settings: Settings, client=LOCAL_CLIENT) -> TestClient:
    from titan_api.app import create_app

    return TestClient(create_app(settings), client=client)


def create_user(settings: Settings, username: str = "operador", password: str = TEST_PASSWORD):
    from titan.auth.service import AuthService
    from titan.db.engine import make_engine, make_session_factory

    engine = make_engine(settings.database_url)
    with make_session_factory(engine).begin() as db:
        user = AuthService.create_user(db, username, password)
        uid = user.id
    engine.dispose()
    return uid


def login(client: TestClient, username: str = "operador", password: str = TEST_PASSWORD):
    return client.post(
        "/api/v1/auth/login", json={"username": username, "password": password}, headers=CSRF
    )


@pytest.fixture
def client(settings: Settings) -> TestClient:
    with build_client(settings) as c:
        yield c


@pytest.fixture
def auth_client(settings: Settings) -> TestClient:
    create_user(settings)
    with build_client(settings) as c:
        r = login(c)
        assert r.status_code == 200, r.text
        yield c
