"""Execução e verificação das migrações Alembic."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Engine

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS_DIR = PROJECT_ROOT / "migrations"


def alembic_config(database_url: str) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
    cfg.attributes["database_url"] = database_url
    return cfg


def upgrade_head(database_url: str) -> None:
    command.upgrade(alembic_config(database_url), "head")


def head_revision() -> Optional[str]:
    return ScriptDirectory(str(MIGRATIONS_DIR)).get_current_head()


def current_revision(engine: Engine) -> Optional[str]:
    with engine.connect() as conn:
        return MigrationContext.configure(conn).get_current_revision()
