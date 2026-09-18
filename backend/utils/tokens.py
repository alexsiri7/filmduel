"""Shared pair-token encode/decode utilities.

A pair token binds the issuing user and the two served movie IDs so that
POST /api/duels only accepts pairs the server offered to that same user. It
expires after PAIR_TOKEN_TTL_SECONDS on that path; GET /api/movies/pair reads
the same token back as an anti-repeat hint, where age does not matter.
"""

from __future__ import annotations

from backend.services.token_crypto import decrypt_token, encrypt_token

# The client prefetches the next pair as soon as one is shown, so a token is
# roughly two deliberations old at submit. 15 minutes covers that while
# bounding how long a served pair can be resubmitted.
PAIR_TOKEN_TTL_SECONDS = 900


def encode_pair_token(id_a: str, id_b: str, *, user_id: str) -> str:
    return encrypt_token(f"{user_id},{id_a},{id_b}")


def decode_pair_token(
    token: str, *, user_id: str, ttl: int | None = PAIR_TOKEN_TTL_SECONDS
) -> set[str] | None:
    """Return the bound movie IDs, or None if the token is invalid, older than
    ``ttl`` seconds (``None`` never expires), or was issued to a different user."""
    try:
        parts = decrypt_token(token, ttl=ttl).split(",")
    except Exception:
        return None
    if len(parts) != 3 or parts[0] != user_id:
        return None
    return {parts[1], parts[2]}
