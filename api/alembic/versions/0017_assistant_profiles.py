"""Named assistants campaigns can pick, and SOPs attached to them."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0017_assistant_profiles"
down_revision = "0016_integrations_like_rules"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "assistant_profiles",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "workspace_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("mode", sa.String(16), nullable=False, server_default="inherit"),
        sa.Column("persona", sa.Text(), nullable=False, server_default=""),
        sa.Column("instructions", sa.Text(), nullable=False, server_default=""),
        sa.Column("handoff_topics", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "collect_fields", postgresql.JSONB(), nullable=False, server_default="[]"
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_assistant_profiles_workspace_id", "assistant_profiles", ["workspace_id"])
    op.add_column(
        "knowledge_items",
        sa.Column(
            "assistant_ids",
            postgresql.ARRAY(postgresql.UUID(as_uuid=True)),
            nullable=False,
            server_default="{}",
        ),
    )


def downgrade() -> None:
    op.drop_column("knowledge_items", "assistant_ids")
    op.drop_index("ix_assistant_profiles_workspace_id", table_name="assistant_profiles")
    op.drop_table("assistant_profiles")
