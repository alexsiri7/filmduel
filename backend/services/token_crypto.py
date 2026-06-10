"""Authenticated encryption for OAuth tokens stored in the database.

Tokens are encrypted with Fernet (AES-128-CBC + HMAC-SHA256). The key is
derived from TOKEN_ENC_KEY via HKDF (not SECRET_KEY) so token encryption
can be rotated independently of JWT signing.
"""

from __future__ import annotations

import base64
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from backend.config import get_settings


@lru_cache(maxsize=1)
def _fernet() -> Fernet:
    settings = get_settings()
    if not settings.TOKEN_ENC_KEY:
        raise RuntimeError(
            "TOKEN_ENC_KEY is not set — required for token encryption at rest"
        )
    raw = settings.TOKEN_ENC_KEY.encode()
    derived = HKDF(
        algorithm=SHA256(),
        length=32,
        salt=b"filmduel-token-enc",
        info=b"fernet-key-v2",
    ).derive(raw)
    return Fernet(base64.urlsafe_b64encode(derived))


def encrypt_token(plain: str) -> str:
    if not plain:
        return ""
    return _fernet().encrypt(plain.encode()).decode()


def decrypt_token(ciphertext: str) -> str:
    if not ciphertext:
        return ""
    try:
        return _fernet().decrypt(ciphertext.encode()).decode()
    except InvalidToken as exc:
        raise RuntimeError("Token decryption failed — wrong TOKEN_ENC_KEY?") from exc
