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
    # Add purge_after: 90 days from created_at for existing rows, 90 days from now for future
    op.add_column(
        "feedback_reports",
        sa.Column("purge_after", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        "UPDATE feedback_reports SET purge_after = created_at + INTERVAL '90 days'"
    )


def downgrade() -> None:
    op.drop_column("feedback_reports", "purge_after")
    op.alter_column("feedback_reports", "screenshot_data_enc",
                    new_column_name="screenshot_data")
