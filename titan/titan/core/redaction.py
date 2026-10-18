"""Redação de segredos antes de gravar logs e eventos de auditoria."""

from __future__ import annotations

import re
from typing import Any

REDACTED = "[REDACTED]"

_SENSITIVE_KEY = re.compile(
    r"(pass(word)?|senha|secret|token|api[_-]?key|authorization|cookie|credential|private[_-]?key)",
    re.IGNORECASE,
)
_SENSITIVE_VALUE_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_\-]{16,}"),  # chaves estilo OpenAI/Anthropic
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),  # tokens GitHub
    re.compile(r"AKIA[0-9A-Z]{16}"),  # AWS access key
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]{10,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"(?i)(postgres(ql)?(\+\w+)?://[^:/\s]+:)[^@\s]+(@)"),
]

_extra_secrets: set[str] = set()


def register_secret(value: str) -> None:
    """Registra um valor literal que deve ser sempre redigido (ex.: TITAN_AUTH_SECRET)."""
    if value and len(value) >= 8:
        _extra_secrets.add(value)


def redact_text(text: str) -> str:
    for secret in _extra_secrets:
        if secret in text:
            text = text.replace(secret, REDACTED)
    for pattern in _SENSITIVE_VALUE_PATTERNS:
        if pattern.groups >= 4:
            text = pattern.sub(lambda m: f"{m.group(1)}{REDACTED}{m.group(4)}", text)
        else:
            text = pattern.sub(REDACTED, text)
    return text


def redact(value: Any) -> Any:
    """Redige recursivamente dicts/listas/strings."""
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if isinstance(k, str) and _SENSITIVE_KEY.search(k):
                out[k] = REDACTED
            else:
                out[k] = redact(v)
        return out
    if isinstance(value, (list, tuple)):
        return [redact(v) for v in value]
    if isinstance(value, str):
        return redact_text(value)
    return value
