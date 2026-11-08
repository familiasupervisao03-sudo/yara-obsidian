"""Backups: consistência com escritas simultâneas, restauração testada e retenção."""

import json
import sqlite3
import threading
from pathlib import Path

import pytest

from tests.conftest import CSRF, TEST_SECRET, build_client, create_user, login
from titan.core.backup import (
    BackupError,
    create_backup,
    list_backups,
    prune,
    restore,
    verify_restore,
)


@pytest.fixture
def sqlite_settings(make_settings, tmp_path):
    from titan.db.migrate import upgrade_head

    s = make_settings(database_url=f"sqlite:///{tmp_path / 'titan.db'}",
                      backup_dir=tmp_path / "backups")
    upgrade_head(s.database_url)
    create_user(s)
    with build_client(s) as c:
        login(c)
        cid = c.post("/api/v1/conversations", json={"title": "importante"}, headers=CSRF).json()["id"]
        c.post(f"/api/v1/conversations/{cid}/messages", json={"content": "dado valioso"}, headers=CSRF)
    return s


def test_backup_and_restore_test(sqlite_settings):
    info = create_backup(sqlite_settings)
    assert info.valid and info.path.exists()
    assert (info.path.stat().st_mode & 0o777) == 0o600
    report = verify_restore(info.path)
    assert report["ok"] and report["audit_chain_ok"]
    assert report["row_counts"]["messages"] == 1
    assert report["schema_revision"] is not None


def test_manifest_has_no_secrets(sqlite_settings):
    info = create_backup(sqlite_settings)
    text = info.path.with_suffix(".json").read_text()
    assert TEST_SECRET not in text
    assert json.loads(text)["secrets_included"] is False


def test_backup_consistent_during_concurrent_writes(sqlite_settings):
    db_path = sqlite_settings.database_url.split("///", 1)[1]
    stop = threading.Event()

    def writer():
        conn = sqlite3.connect(db_path, timeout=30)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("CREATE TABLE IF NOT EXISTS carga (i INTEGER, txt TEXT)")
        i = 0
        while not stop.is_set():
            conn.execute("INSERT INTO carga VALUES (?, ?)", (i, "x" * 500))
            conn.commit()
            i += 1
        conn.close()

    t = threading.Thread(target=writer)
    t.start()
    try:
        infos = [create_backup(sqlite_settings) for _ in range(3)]
    finally:
        stop.set()
        t.join()
    for info in infos:
        assert verify_restore(info.path)["ok"]


def test_corrupted_backup_detected(sqlite_settings):
    info = create_backup(sqlite_settings)
    data = bytearray(info.path.read_bytes())
    data[len(data) // 2] ^= 0xFF
    info.path.write_bytes(bytes(data))
    with pytest.raises(BackupError, match="corrompido"):
        verify_restore(info.path)


def test_prune_keeps_latest_valid(sqlite_settings):
    dest = Path(sqlite_settings.backup_dir)
    for _ in range(4):
        create_backup(sqlite_settings)
    # O mais recente fica com manifesto inválido: o último VÁLIDO deve ser protegido.
    newest = list_backups(dest)[-1]
    newest.path.with_suffix(".json").write_text(json.dumps({"integrity": "falhou"}))
    prune(dest, keep=1)
    remaining = list_backups(dest)
    assert newest.path in [b.path for b in remaining]
    assert any(b.valid for b in remaining)
    with pytest.raises(BackupError):
        prune(dest, keep=0)


def test_restore_roundtrip_keeps_safety_copy(sqlite_settings):
    info = create_backup(sqlite_settings)
    db_path = Path(sqlite_settings.database_url.split("///", 1)[1])
    conn = sqlite3.connect(db_path)
    conn.execute("DELETE FROM messages")
    conn.commit()
    conn.close()
    safety = restore(sqlite_settings, info.path)
    assert safety.exists()
    conn = sqlite3.connect(db_path)
    assert conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 1
    conn.close()
    with build_client(sqlite_settings) as c:  # servidor funciona com o banco restaurado
        login(c)
        assert c.get("/api/v1/conversations").json()["total"] == 1


def test_postgres_backup_gives_clear_message(make_settings):
    s = make_settings(database_url="postgresql+psycopg://u:p@127.0.0.1/x")
    with pytest.raises(BackupError, match="pg_dump"):
        create_backup(s)


def test_cli_backup(sqlite_settings, monkeypatch, capsys):
    from titan import cli

    monkeypatch.setattr(cli, "_settings", lambda: sqlite_settings)
    assert cli.main(["backup"]) == 0
    out = capsys.readouterr().out
    assert "Teste de restauração em pasta temporária: OK" in out
    assert cli.main(["restore", "x"]) == 1  # exige --yes
