"""Shared pair-token encode/decode utilities."""

from __future__ import annotations

from backend.services.token_crypto import decrypt_token, encrypt_token


def encode_pair_token(id_a: str, id_b: str) -> str:
    return encrypt_token(f"{id_a},{id_b}")


def decode_pair_token(token: str) -> set[str] | None:
    try:
        parts = decrypt_token(token).split(",")
        return set(parts) if len(parts) == 2 else None
    except Exception:
        return None
