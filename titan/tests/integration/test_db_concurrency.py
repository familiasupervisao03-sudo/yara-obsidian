"""Concorrência no SQLite: defeitos achados pela simulação contínua (docs/simulacao.md)."""

import threading
import time

from sqlalchemy import text

from titan.audit import log as audit
from titan.db.engine import make_engine, make_session_factory
from titan.db.models import AppSetting, utcnow


def test_audit_lock_order_does_not_deadlock(settings):
    """A grava algo (pega a trava de escrita do SQLite) e depois audita; B audita no meio.

    Com a ordem invertida (trava da auditoria antes da do SQLite), A e B esperavam um ao
    outro até o limite de 15 s e uma das transações falhava com 'database is locked'.
    """
    engine = make_engine(settings.database_url)
    factory = make_session_factory(engine)
    a_has_write_lock, errors, done = threading.Event(), [], []

    def a() -> None:
        try:
            with factory.begin() as db:
                db.add(AppSetting(key="sim-a", value={"x": 1}, updated_at=utcnow()))
                db.flush()  # agora A tem a trava de escrita do SQLite
                a_has_write_lock.set()
                time.sleep(0.5)  # B começa a auditar neste meio-tempo
                audit.record(db, "teste.a")
            done.append("a")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"A: {exc}")

    def b() -> None:
        a_has_write_lock.wait(5)
        try:
            with factory.begin() as db:
                audit.record(db, "teste.b")
            done.append("b")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"B: {exc}")

    t0 = time.monotonic()
    ts = [threading.Thread(target=a), threading.Thread(target=b)]
    for t in ts:
        t.start()
    for t in ts:
        t.join(30)
    elapsed = time.monotonic() - t0
    with factory() as db:
        ok, _ = audit.verify_chain(db)
        n = db.scalar(text("SELECT COUNT(*) FROM audit_events WHERE event_type LIKE 'teste.%'"))
    engine.dispose()
    assert errors == [] and sorted(done) == ["a", "b"], errors
    assert elapsed < 5, f"esperou {elapsed:.1f} s (travas em ordem invertida)"
    assert ok and n == 2


def test_last_seen_is_written_at_most_once_per_minute(settings):
    """Leituras não viram escritas: o último acesso só é gravado se passou 1 minuto."""
    from datetime import timedelta

    from titan.auth.service import AuthService, LoginThrottle

    engine = make_engine(settings.database_url)
    factory = make_session_factory(engine)
    auth = AuthService("segredo-de-teste-com-mais-de-32-caracteres-0123456789", 12, LoginThrottle(5, 300))
    with factory.begin() as db:
        AuthService.create_user(db, "carla", "senha-forte-de-teste")
        issued = auth.login(db, "carla", "senha-forte-de-teste", "127.0.0.1", "teste")
        token = issued.token
    with factory() as db:
        sess, _ = auth.resolve(db, token)
        assert not db.dirty  # acabou de entrar: nada a gravar
        sess.last_seen_at = utcnow() - timedelta(minutes=2)
        db.commit()
        sess, _ = auth.resolve(db, token)
        assert sess in db.dirty  # passou 1 minuto: grava
    engine.dispose()


def test_chain_monitor_checks_only_new_events_and_still_catches_tampering(settings):
    from titan.db.models import AuditEvent

    engine = make_engine(settings.database_url)
    factory = make_session_factory(engine)
    mon = audit.ChainMonitor(full_every=3600)
    for i in range(5):
        with factory.begin() as db:
            audit.record(db, f"teste.{i}")
    with factory() as db:
        assert mon.check(db) == (True, None)
    with factory.begin() as db:
        audit.record(db, "teste.novo")
    with factory() as db:
        assert mon.check(db) == (True, None)  # só o evento novo foi conferido
        last_id = mon._last[0]
    with factory.begin() as db:  # adultera o último evento já conferido
        db.get(AuditEvent, last_id).event_type = "adulterado"
    with factory() as db:
        assert mon.check(db) == (False, last_id)
        assert mon.check(db) == (False, last_id)  # fica marcado
    engine.dispose()
