"""AI lead finder: saved searches, and the "ai_search" lead source."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0015_lead_searches"
down_revision = "0014_knowledge_accounts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE lead_source ADD VALUE IF NOT EXISTS 'ai_search'")
    op.create_table(
        "lead_searches",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("title", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("messages", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("criteria", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("results", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("provider", sa.String(length=40), nullable=False, server_default=""),
        sa.Column("runs", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_lead_searches_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            name=op.f("fk_lead_searches_created_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_lead_searches")),
    )
    op.create_index(
        "ix_lead_searches_workspace_created", "lead_searches", ["workspace_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_lead_searches_workspace_created", table_name="lead_searches")
    op.drop_table("lead_searches")
    # Postgres cannot drop an enum value; "ai_search" stays, unused.
