"""Attach knowledge items (SOPs) to specific LinkedIn accounts."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0014_knowledge_accounts"
down_revision = "0013_bot_send_at"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "knowledge_items",
        sa.Column(
            "linkedin_account_ids",
            postgresql.ARRAY(postgresql.UUID(as_uuid=True)),
            nullable=False,
            server_default="{}",
        ),
    )


def downgrade() -> None:
    op.drop_column("knowledge_items", "linkedin_account_ids")
