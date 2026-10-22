"""Re-encrypt stored secrets from TOKEN_ENC_KEY_PREVIOUS keys under TOKEN_ENC_KEY.

Run once a rotated TOKEN_ENC_KEY is deployed, before TOKEN_ENC_KEY_PREVIOUS is
removed (see "Rotating TOKEN_ENC_KEY" in docs/PRD.md):

    python -m backend.scripts.reencrypt_tokens

Values already under the current key are left alone, so it is idempotent and
safe to re-run. A value no configured key decrypts is left as stored and
logged by row: removing TOKEN_ENC_KEY_PREVIOUS while any remain makes them
unrecoverable, so re-run until it reports unreadable=0 or accept those losses.
"""

from __future__ import annotations

import asyncio
import logging

import sqlalchemy as sa

from backend.services.token_crypto import (
    TokenDecryptError,
    TokenPurpose,
    decrypt_and_rotate,
)

logger = logging.getLogger("reencrypt_tokens")

_COLUMNS = (
    ("users", "trakt_access_token", TokenPurpose.OAUTH),
    ("users", "trakt_refresh_token", TokenPurpose.OAUTH),
    ("users", "simkl_access_token", TokenPurpose.OAUTH),
    ("users", "simkl_refresh_token", TokenPurpose.OAUTH),
    ("feedback_reports", "screenshot_data_enc", TokenPurpose.SCREENSHOT),
)


def reencrypt(conn: sa.Connection) -> tuple[int, int]:
    """Rewrite every value a previous key minted; return (rewritten, unreadable)."""
    rewritten = unreadable = 0
    for table, column, purpose in _COLUMNS:
        # One value at a time: screenshots run to megabytes each.
        ids = conn.execute(
            sa.text(f"SELECT id FROM {table} WHERE {column} IS NOT NULL AND {column} != ''")
        ).scalars().all()
        for row_id in ids:
            value = conn.execute(
                sa.text(f"SELECT {column} FROM {table} WHERE id = :id"), {"id": row_id}
            ).scalar_one()
            try:
                _, rotated = decrypt_and_rotate(value, purpose=purpose)
            except TokenDecryptError:
                logger.warning(
                    "unreadable %s.%s id=%s — no configured key decrypts it",
                    table,
                    column,
                    row_id,
                )
                unreadable += 1
                continue
            if rotated is not None:
                conn.execute(
                    sa.text(f"UPDATE {table} SET {column} = :v WHERE id = :id"),
                    {"id": row_id, "v": rotated},
                )
                rewritten += 1
    return rewritten, unreadable


async def main() -> None:
    from backend.db import engine

    async with engine.begin() as conn:
        rewritten, unreadable = await conn.run_sync(reencrypt)
    logger.info("done rewritten=%d unreadable=%d", rewritten, unreadable)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
