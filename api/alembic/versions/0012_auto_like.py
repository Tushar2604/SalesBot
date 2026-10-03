"""Opt-in flag for the autonomous liking sweep."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0012_auto_like"
down_revision = "0011_feed_like"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "linkedin_accounts",
        sa.Column("auto_like_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("linkedin_accounts", "auto_like_enabled")
