"""Backups locais do banco SQLite, com verificação de restauração.

* A cópia usa a API de backup do SQLite: é consistente mesmo com o servidor
  gravando (não é uma cópia de arquivo "no meio da escrita").
* Cada backup tem um manifesto (sem segredos) com hash, tamanho, revisão do
  esquema e resultado do ``PRAGMA integrity_check``.
* ``verify_restore`` restaura numa pasta temporária separada e testa o banco
  restaurado; o banco original nunca é tocado.
* ``prune`` remove backups antigos, mas nunca o mais recente válido.
* O ``.env`` (segredos) NÃO entra no backup: guarde-o à parte.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import stat
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from titan import __version__
from titan.config.settings import Settings

PREFIX = "titan-"
SUFFIX = ".db"


class BackupError(Exception):
    pass


@dataclass
class BackupInfo:
    path: Path
    manifest: dict

    @property
    def valid(self) -> bool:
        return self.manifest.get("integrity") == "ok"


def sqlite_path(settings: Settings) -> Path:
    if not settings.is_sqlite:
        raise BackupError("Backup automático implementado apenas para SQLite. Para PostgreSQL, "
                          "use pg_dump (ver docs/backup.md).")
    raw = settings.database_url.split("///", 1)[-1]
    if not raw or raw == ":memory:":
        raise BackupError("Banco em memória não pode ser copiado.")
    return Path(raw).expanduser().resolve()


def _private_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    os.chmod(path, stat.S_IRWXU)
    return path


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _inspect(db_file: Path) -> dict:
    conn = sqlite3.connect(f"file:{db_file}?mode=ro", uri=True)
    try:
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        revision = None
        if "alembic_version" in tables:
            row = conn.execute("SELECT version_num FROM alembic_version").fetchone()
            revision = row[0] if row else None
        counts = {}
        for t in ("users", "conversations", "messages", "tasks", "audit_events"):
            if t in tables:
                counts[t] = conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
        fk = conn.execute("PRAGMA foreign_key_check").fetchall()
    finally:
        conn.close()
    return {"integrity": integrity, "schema_revision": revision, "row_counts": counts,
            "foreign_key_violations": len(fk)}


def create_backup(settings: Settings, dest: Optional[Path] = None) -> BackupInfo:
    src = sqlite_path(settings)
    if not src.exists():
        raise BackupError(f"Banco não encontrado: {src}")
    dest = _private_dir(Path(dest or settings.backup_dir).expanduser().resolve())
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    target = dest / f"{PREFIX}{stamp}{SUFFIX}"
    tmp = target.with_suffix(".partial")
    old_umask = os.umask(0o077)
    try:
        src_conn = sqlite3.connect(f"file:{src}?mode=ro", uri=True, timeout=30)
        dst_conn = sqlite3.connect(tmp)
        try:
            with dst_conn:
                src_conn.backup(dst_conn, pages=256)  # copia em blocos; tolera escritas
            # Arquivo autocontido (sem -wal/-shm), legível em modo somente leitura.
            dst_conn.execute("PRAGMA journal_mode=DELETE")
        finally:
            dst_conn.close()
            src_conn.close()
        details = _inspect(tmp)
        if details["integrity"] != "ok":
            tmp.unlink(missing_ok=True)
            raise BackupError(f"Backup reprovado no integrity_check: {details['integrity']}")
        os.replace(tmp, target)
        os.chmod(target, stat.S_IRUSR | stat.S_IWUSR)
        manifest = {
            "created_at": datetime.now().astimezone().isoformat(),
            "titan_version": __version__,
            "source": str(src),
            "file": target.name,
            "size_bytes": target.stat().st_size,
            "sha256": _sha256(target),
            **details,
            # Configuração SEM segredos, para ajudar a reconstruir o serviço.
            "config": settings.public_view(),
            "secrets_included": False,
        }
        manifest_path = target.with_suffix(".json")
        manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False),
                                 encoding="utf-8")
        os.chmod(manifest_path, stat.S_IRUSR | stat.S_IWUSR)
    finally:
        os.umask(old_umask)
        if tmp.exists():
            tmp.unlink()
    return BackupInfo(target, manifest)


def list_backups(dest: Path) -> list[BackupInfo]:
    dest = Path(dest).expanduser()
    if not dest.is_dir():
        return []
    out = []
    for db_file in sorted(dest.glob(f"{PREFIX}*{SUFFIX}")):
        mpath = db_file.with_suffix(".json")
        try:
            manifest = json.loads(mpath.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            manifest = {"integrity": "manifesto ausente ou ilegível"}
        out.append(BackupInfo(db_file, manifest))
    return out  # ordem cronológica (nome contém data/hora)


def verify_restore(backup: Path) -> dict:
    """Restaura o backup numa pasta temporária e testa o banco restaurado."""
    backup = Path(backup).expanduser().resolve()
    if not backup.is_file():
        raise BackupError(f"Backup não encontrado: {backup}")
    manifest_path = backup.with_suffix(".json")
    expected_hash = None
    if manifest_path.exists():
        expected_hash = json.loads(manifest_path.read_text(encoding="utf-8")).get("sha256")
    actual_hash = _sha256(backup)
    if expected_hash and expected_hash != actual_hash:
        raise BackupError("O arquivo de backup foi alterado ou corrompido (hash diferente).")
    with tempfile.TemporaryDirectory(prefix="titan-restore-test-") as tmp:
        restored = Path(tmp) / "restaurado.db"
        src = sqlite3.connect(f"file:{backup}?mode=ro", uri=True)
        dst = sqlite3.connect(restored)
        try:
            with dst:
                src.backup(dst)
            dst.execute("PRAGMA journal_mode=DELETE")
        finally:
            dst.close()
            src.close()
        details = _inspect(restored)
        # Teste de aplicação: a cadeia de auditoria do banco restaurado é íntegra?
        from titan.audit.log import verify_chain
        from titan.db.engine import make_engine, make_session_factory

        engine = make_engine(f"sqlite:///{restored}")
        try:
            with make_session_factory(engine)() as db:
                chain_ok, bad = verify_chain(db)
        finally:
            engine.dispose()
    ok = details["integrity"] == "ok" and details["foreign_key_violations"] == 0 and chain_ok
    return {"ok": ok, "sha256_ok": expected_hash in (None, actual_hash),
            "audit_chain_ok": chain_ok, **details}


def prune(dest: Path, keep: int) -> list[Path]:
    """Mantém os ``keep`` backups mais recentes. Nunca remove o último válido."""
    if keep < 1:
        raise BackupError("A retenção deve manter ao menos 1 backup.")
    backups = list_backups(dest)
    valid = [b for b in backups if b.valid]
    protected = {valid[-1].path} if valid else set()
    keep_set = {b.path for b in backups[-keep:]} | protected
    removed = []
    for b in backups:
        if b.path not in keep_set:
            b.path.unlink(missing_ok=True)
            b.path.with_suffix(".json").unlink(missing_ok=True)
            removed.append(b.path)
    return removed


def restore(settings: Settings, backup: Path) -> Path:
    """Substitui o banco atual pelo backup (servidor DEVE estar parado).

    Antes, verifica o backup e guarda uma cópia do banco atual ao lado.
    Retorna o caminho dessa cópia de segurança.
    """
    report = verify_restore(backup)
    if not report["ok"]:
        raise BackupError(f"Backup reprovado na verificação; restauração cancelada: {report}")
    target = sqlite_path(settings)
    safety = target.with_name(f"{target.name}.antes-da-restauracao-"
                              f"{datetime.now():%Y%m%d-%H%M%S}")
    if target.exists():
        shutil.copy2(target, safety)
        os.chmod(safety, stat.S_IRUSR | stat.S_IWUSR)
    src = sqlite3.connect(f"file:{Path(backup).resolve()}?mode=ro", uri=True)
    dst = sqlite3.connect(target, timeout=5)
    try:
        with dst:
            src.backup(dst)
    finally:
        dst.close()
        src.close()
    return safety
