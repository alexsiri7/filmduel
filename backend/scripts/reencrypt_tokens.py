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

from backend.db_models import EncryptedToken, FeedbackReport, User
from backend.services.token_crypto import (
    TokenDecryptError,
    TokenPurpose,
    decrypt_and_rotate,
)

logger = logging.getLogger("reencrypt_tokens")

_COLUMNS = (
    *((column, TokenPurpose.OAUTH) for column in EncryptedToken.columns(User)),
    (FeedbackReport.__table__.c.screenshot_data_enc, TokenPurpose.SCREENSHOT),
)


def reencrypt(conn: sa.Connection) -> tuple[int, int]:
    """Rewrite every value a previous key minted; return (rewritten, unreadable)."""
    rewritten = unreadable = 0
    for column, purpose in _COLUMNS:
        table = column.table
        # One value at a time: screenshots run to megabytes each.
        ids = conn.execute(
            sa.select(table.c.id).where(column.is_not(None), column != "")
        ).scalars().all()
        for row_id in ids:
            value = conn.execute(
                sa.select(column).where(table.c.id == row_id)
            ).scalar_one_or_none()
            if not value:
                continue  # deleted or cleared since the id listing
            try:
                _, rotated = decrypt_and_rotate(value, purpose=purpose)
            except TokenDecryptError:
                logger.warning(
                    "unreadable %s id=%s — no configured key decrypts it",
                    column,
                    row_id,
                )
                unreadable += 1
                continue
            if rotated is None:
                continue
            # A live request may have stored a newer value since the read.
            result = conn.execute(
                sa.update(table)
                .where(table.c.id == row_id, column == value)
                .values({column: rotated})
            )
            rewritten += result.rowcount
    return rewritten, unreadable


async def main() -> None:
    from backend.db import engine

    async with engine.begin() as conn:
        rewritten, unreadable = await conn.run_sync(reencrypt)
    logger.info("done rewritten=%d unreadable=%d", rewritten, unreadable)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
