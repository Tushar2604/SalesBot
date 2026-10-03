"""When the assistant's auto-reply in a thread is scheduled to go out."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0013_bot_send_at"
down_revision = "0012_auto_like"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "conversations",
        sa.Column("bot_send_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("conversations", "bot_send_at")
