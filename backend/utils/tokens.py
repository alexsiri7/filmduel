"""Shared pair-token encode/decode utilities."""

from __future__ import annotations

from backend.services.token_crypto import decrypt_token, encrypt_token


def encode_pair_token(id_a: str, id_b: str) -> str:
    return encrypt_token(f"{id_a},{id_b}")


def decode_pair_token(token: str) -> set[str] | None:
    try:
        raw = decrypt_token(token)
        parts = raw.split(",")
        if len(parts) == 2:
            return {parts[0], parts[1]}
    except Exception:
        pass
    return None
