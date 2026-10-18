"""Preparação do ambiente local: diretórios com permissões restritas e logs rotativos."""

from __future__ import annotations

import logging
import os
import stat
from logging.handlers import RotatingFileHandler
from pathlib import Path

from titan.config.settings import Settings
from titan.core.redaction import redact_text, register_secret


def ensure_private_dir(path: Path) -> Path:
    """Cria (se preciso) e restringe o diretório ao dono (0700)."""
    path = path.expanduser().resolve()
    path.mkdir(parents=True, exist_ok=True)
    os.chmod(path, stat.S_IRWXU)
    return path


class RedactingFormatter(logging.Formatter):
    """Redige a linha final, incluindo tracebacks de exceções."""

    def format(self, record: logging.LogRecord) -> str:
        return redact_text(super().format(record))


def configure_logging(settings: Settings) -> None:
    register_secret(settings.auth_secret.get_secret_value())
    root = logging.getLogger("titan")
    root.setLevel(settings.log_level)
    # Substitui handlers de uma configuração anterior (ex.: outro diretório de dados).
    for old in [h for h in root.handlers if getattr(h, "_titan", False)]:
        root.removeHandler(old)
        old.close()
    fmt = RedactingFormatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    log_dir = ensure_private_dir(settings.data_dir / "logs")
    file_handler = RotatingFileHandler(
        log_dir / "titan.log",
        maxBytes=settings.log_max_bytes,
        backupCount=settings.log_backup_count,
        encoding="utf-8",
    )
    stream = logging.StreamHandler()
    for h in (file_handler, stream):
        h.setFormatter(fmt)
        h._titan = True  # type: ignore[attr-defined]
        root.addHandler(h)


def prepare_runtime(settings: Settings) -> None:
    ensure_private_dir(settings.data_dir)
    ensure_private_dir(settings.workspace_root)
    configure_logging(settings)
