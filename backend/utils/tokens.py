"""Shared pair-token encode/decode utilities."""

from __future__ import annotations

import logging

from backend.services.token_crypto import decrypt_token, encrypt_token

logger = logging.getLogger(__name__)


def encode_pair_token(id_a: str, id_b: str) -> str:
    """Encrypt a movie-pair into an opaque token for round-trip validation."""
    return encrypt_token(f"{id_a},{id_b}")


_CONFIG_ERROR_MARKER = "TOKEN_ENC_KEY is not set"


def decode_pair_token(token: str) -> set[str] | None:
    """Decrypt a pair token and return the set of two movie-ID strings.

    Returns None if the token is invalid, malformed, or tampered with.
    RuntimeError from a missing TOKEN_ENC_KEY is re-raised so that
    infrastructure misconfigurations surface as 500s rather than silent 400s.
    Token decryption failures (bad/tampered ciphertext) return None.
    Other unexpected errors are logged and treated as invalid tokens.
    """
    try:
        raw = decrypt_token(token)
        parts = raw.split(",")
        if len(parts) == 2:
            return {parts[0], parts[1]}
    except RuntimeError as exc:
        # Re-raise configuration errors (missing TOKEN_ENC_KEY) so they
        # surface as 500s rather than being silently treated as invalid tokens.
        if _CONFIG_ERROR_MARKER in str(exc):
            raise
        # Otherwise it's a decryption failure (tampered/bad ciphertext) — return None.
    except Exception:
        # Unexpected library or type error — log for diagnostics, treat as invalid.
        logger.error("decode_pair_token: unexpected error during decryption", exc_info=True)
    return None
