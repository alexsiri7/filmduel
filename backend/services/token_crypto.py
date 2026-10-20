"""Authenticated encryption for secrets the server stores or hands out.

Values are encrypted with Fernet (AES-128-CBC + HMAC-SHA256). Keys are
derived from TOKEN_ENC_KEY via HKDF (not SECRET_KEY) so encryption can be
rotated independently of JWT signing. Each TokenPurpose derives its own key,
so ciphertext minted for one purpose never decrypts as another.
"""

from __future__ import annotations

import base64
from enum import Enum
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from backend.config import get_settings


class TokenPurpose(Enum):
    # The values are HKDF info strings: changing one orphans every ciphertext
    # stored under it unless a migration re-keys it (see migration 028).
    OAUTH = b"fernet-key-v3/oauth-token"
    SCREENSHOT = b"fernet-key-v3/feedback-screenshot"
    PAIR = b"fernet-key-v3/pair-token"


@lru_cache(maxsize=len(TokenPurpose))
def _fernet(purpose: TokenPurpose) -> Fernet:
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
        info=purpose.value,
    ).derive(raw)
    return Fernet(base64.urlsafe_b64encode(derived))


def encrypt_token(plain: str, *, purpose: TokenPurpose) -> str:
    if not plain:
        return ""
    return _fernet(purpose).encrypt(plain.encode()).decode()


def decrypt_token(
    ciphertext: str, *, purpose: TokenPurpose, ttl: int | None = None
) -> str:
    """Decrypt a token, rejecting it once it is older than ``ttl`` seconds.

    ``None`` (the default) never expires — required for OAuth tokens and
    screenshots stored at rest.
    """
    if not ciphertext:
        return ""
    try:
        return _fernet(purpose).decrypt(ciphertext.encode(), ttl=ttl).decode()
    except InvalidToken as exc:
        raise RuntimeError("Token decryption failed — wrong TOKEN_ENC_KEY?") from exc
