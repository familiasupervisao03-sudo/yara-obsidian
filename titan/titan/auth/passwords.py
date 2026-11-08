"""Hash de senhas com scrypt (biblioteca padrão; sem extensões nativas extras).

Parâmetros n=2**14, r=8 usam ~16 MB por verificação: seguro e viável em
hardware antigo.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

_N, _R, _P, _DKLEN = 2**14, 8, 1, 32
_PREFIX = "scrypt"

MIN_PASSWORD_LENGTH = 10


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=_DKLEN)
    return "$".join(
        [_PREFIX, str(_N), str(_R), str(_P), _b64(salt), _b64(dk)]
    )


def verify_password(password: str, stored: str) -> bool:
    try:
        prefix, n, r, p, salt_b64, dk_b64 = stored.split("$")
        if prefix != _PREFIX:
            return False
        expected = base64.b64decode(dk_b64)
        dk = hashlib.scrypt(
            password.encode(),
            salt=base64.b64decode(salt_b64),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(expected),
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(dk, expected)


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


# Hash fixo usado para equalizar o tempo de resposta quando o usuário não existe.
DUMMY_HASH = hash_password(secrets.token_urlsafe(16))
