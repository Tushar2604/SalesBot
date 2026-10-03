"""View-and-like: a feed cache on the account, and a like_post action type."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0011_feed_like"
down_revision = "0010_proxy_exit_country"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE step_type ADD VALUE IF NOT EXISTS 'like_post'")
    op.add_column(
        "linkedin_accounts",
        sa.Column("cached_feed", JSONB, nullable=False, server_default="[]"),
    )
    op.add_column(
        "linkedin_accounts",
        sa.Column("cached_feed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("linkedin_accounts", "cached_feed_at")
    op.drop_column("linkedin_accounts", "cached_feed")
    # Postgres cannot drop an enum value; 'like_post' is left in place.
