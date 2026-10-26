"""Authenticated encryption for secrets the server stores or hands out.

Values are encrypted with Fernet (AES-128-CBC + HMAC-SHA256). Keys are
derived from TOKEN_ENC_KEY via HKDF (not SECRET_KEY) so encryption can be
rotated independently of JWT signing. Each TokenPurpose derives its own key,
so ciphertext minted for one purpose never decrypts as another.

TOKEN_ENC_KEY always encrypts. Keys listed in TOKEN_ENC_KEY_PREVIOUS only
decrypt, so values written before a rotation stay readable until
backend/scripts/reencrypt_tokens.py moves them to the current key.
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


class TokenDecryptError(RuntimeError):
    """No configured key decrypts the value (or it is older than its ttl)."""


def _derive(key: str, purpose: TokenPurpose) -> Fernet:
    derived = HKDF(
        algorithm=SHA256(),
        length=32,
        salt=b"filmduel-token-enc",
        info=purpose.value,
    ).derive(key.encode())
    return Fernet(base64.urlsafe_b64encode(derived))


@lru_cache(maxsize=len(TokenPurpose))
def _fernet(purpose: TokenPurpose) -> Fernet:
    settings = get_settings()
    if not settings.TOKEN_ENC_KEY:
        raise RuntimeError(
            "TOKEN_ENC_KEY is not set — required for token encryption at rest"
        )
    return _derive(settings.TOKEN_ENC_KEY, purpose)


def _previous_fernets(purpose: TokenPurpose) -> list[Fernet]:
    # Uncached: only reached when the current key fails, which is rare once
    # a rotation's re-encrypt has run.
    keys = get_settings().TOKEN_ENC_KEY_PREVIOUS.split(",")
    return [_derive(key.strip(), purpose) for key in keys if key.strip()]


def encrypt_token(plain: str, *, purpose: TokenPurpose) -> str:
    if not plain:
        return ""
    return _fernet(purpose).encrypt(plain.encode()).decode()


def _decrypt(
    ciphertext: str, purpose: TokenPurpose, ttl: int | None
) -> tuple[bytes, bool]:
    """Return the plaintext and whether only a previous key could read it."""
    token = ciphertext.encode()
    try:
        return _fernet(purpose).decrypt(token, ttl=ttl), False
    except InvalidToken:
        pass
    for fernet in _previous_fernets(purpose):
        try:
            return fernet.decrypt(token, ttl=ttl), True
        except InvalidToken:
            continue
    raise TokenDecryptError("Token decryption failed — wrong TOKEN_ENC_KEY?")


def decrypt_token(
    ciphertext: str, *, purpose: TokenPurpose, ttl: int | None = None
) -> str:
    """Decrypt a token, rejecting it once it is older than ``ttl`` seconds.

    ``None`` (the default) never expires — required for OAuth tokens and
    screenshots stored at rest. Raises TokenDecryptError when no configured
    key decrypts it.
    """
    if not ciphertext:
        return ""
    return _decrypt(ciphertext, purpose, ttl)[0].decode()


def decrypt_and_rotate(
    ciphertext: str, *, purpose: TokenPurpose
) -> tuple[str, str | None]:
    """Decrypt a stored value; also return it re-encrypted under TOKEN_ENC_KEY.

    The second element is None when the value is already under the current
    key, so callers rewrite only what a previous key minted. Raises
    TokenDecryptError when no configured key decrypts it.
    """
    if not ciphertext:
        return "", None
    plain, stale = _decrypt(ciphertext, purpose, None)
    rotated = _fernet(purpose).encrypt(plain).decode() if stale else None
    return plain.decode(), rotated
