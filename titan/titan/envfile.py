"""Edição segura do arquivo .env (preserva comentários e demais linhas, permissão 600)."""

from __future__ import annotations

import os
import shutil
import stat
from datetime import datetime
from pathlib import Path


def read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            s = line.strip()
            if s and not s.startswith("#") and "=" in s:
                k, v = s.split("=", 1)
                values[k.strip()] = v.strip()
    return values


def update_env(path: Path, updates: dict[str, str | None]) -> Path | None:
    """Atualiza/insere chaves (None remove). Faz cópia de segurança 600 antes."""
    for k, v in updates.items():
        if v is not None and ("\n" in v or "\r" in v):
            raise ValueError(f"valor inválido para {k}")
    backup = None
    lines: list[str] = []
    if path.exists():
        backup = path.with_name(f"{path.name}.bak-{datetime.now():%Y%m%d-%H%M%S}")
        shutil.copy2(path, backup)
        os.chmod(backup, stat.S_IRUSR | stat.S_IWUSR)
        lines = path.read_text(encoding="utf-8").splitlines()
    pending = dict(updates)
    out: list[str] = []
    for line in lines:
        s = line.strip()
        key = s.split("=", 1)[0].strip() if s and not s.startswith("#") and "=" in s else None
        if key in pending:
            value = pending.pop(key)
            if value is not None:
                out.append(f"{key}={value}")
            continue
        out.append(line)
    extra = {k: v for k, v in pending.items() if v is not None}
    if extra:
        out.append("")
        out.append(f"# Alterado por 'titan' em {datetime.now():%Y-%m-%d %H:%M}")
        out.extend(f"{k}={v}" for k, v in extra.items())
    old_umask = os.umask(0o077)
    try:
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text("\n".join(out) + "\n", encoding="utf-8")
        os.chmod(tmp, stat.S_IRUSR | stat.S_IWUSR)
        os.replace(tmp, path)
    finally:
        os.umask(old_umask)
    return backup
