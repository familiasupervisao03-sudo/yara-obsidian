from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import inspect

from titan.db.engine import make_engine
from titan.db.models import Base

EXPECTED_TABLES = {
    "users", "sessions", "conversations", "messages", "tasks", "task_steps", "approvals",
    "executions", "execution_artifacts", "verification_results", "audit_events",
    "memory_items", "app_settings",
}


def test_all_tables_created(settings):
    engine = make_engine(settings.database_url)
    assert EXPECTED_TABLES <= set(inspect(engine).get_table_names())
    engine.dispose()


def test_models_match_migrations(settings):
    """Falha se um modelo mudar sem a migração correspondente."""
    engine = make_engine(settings.database_url)
    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    engine.dispose()
    assert diff == []


def test_foreign_keys_enforced(settings):
    import uuid

    import pytest
    from sqlalchemy.exc import IntegrityError

    from titan.db.engine import make_session_factory
    from titan.db.models import Conversation

    engine = make_engine(settings.database_url)
    with pytest.raises(IntegrityError):
        with make_session_factory(engine).begin() as db:
            db.add(Conversation(user_id=uuid.uuid4(), title="órfã"))
    engine.dispose()
