from sqlalchemy import update

from titan.audit.log import record, verify_chain
from titan.db.engine import make_engine, make_session_factory
from titan.db.models import AuditEvent


def test_chain_detects_tampering(settings):
    engine = make_engine(settings.database_url)
    factory = make_session_factory(engine)
    with factory.begin() as db:
        record(db, "a", data={"x": 1})
        record(db, "b", data={"password": "nao-gravar"})
        record(db, "c")
    with factory() as db:
        assert verify_chain(db) == (True, None)
        ev = db.query(AuditEvent).filter_by(event_type="b").one()
        assert ev.data["password"] == "[REDACTED]"
    with factory.begin() as db:
        db.execute(update(AuditEvent).where(AuditEvent.event_type == "b").values(data={"x": 2}))
    with factory() as db:
        ok, bad = verify_chain(db)
        assert not ok and bad is not None
    engine.dispose()


def test_lock_released_after_rollback(settings):
    engine = make_engine(settings.database_url)
    factory = make_session_factory(engine)
    db = factory()
    record(db, "x")
    db.rollback()
    db.close()
    with factory.begin() as db2:  # travaria se o lock não fosse liberado
        record(db2, "y")
    engine.dispose()
