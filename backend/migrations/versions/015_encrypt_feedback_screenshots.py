"""Encrypt feedback screenshot data and add purge_after column

Revision ID: 015
Revises: 014
Create Date: 2026-05-16
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "015"
down_revision: Union[str, None] = "014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Scrub any existing plaintext screenshots (cannot encrypt without runtime key)
    op.execute("UPDATE feedback_reports SET screenshot_data = NULL")
    # Rename column to make encryption expectation explicit
    op.alter_column("feedback_reports", "screenshot_data",
                    new_column_name="screenshot_data_enc")
    # Backfill purge_after for existing rows using their original created_at timestamp.
    # New submissions have purge_after set at write time in backend/routers/feedback.py.
    op.add_column(
        "feedback_reports",
        sa.Column("purge_after", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        "UPDATE feedback_reports SET purge_after = created_at + INTERVAL '90 days'"
    )


def downgrade() -> None:
    # NOTE: screenshot data NULLed in upgrade() is NOT restored.
    # Downgrade only reverses the schema; existing rows will have screenshot_data = NULL.
    op.drop_column("feedback_reports", "purge_after")
    # Scrub encrypted values before renaming so old code never sees ciphertext
    op.execute("UPDATE feedback_reports SET screenshot_data_enc = NULL")
    op.alter_column("feedback_reports", "screenshot_data_enc",
                    new_column_name="screenshot_data")
