"""AI assistant: knowledge base, per-conversation bot state, message author.

Revision ID: 0007_assistant
Revises: 0006_content_studio
Create Date: 2026-09-19
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0007_assistant"
down_revision = "0006_content_studio"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "knowledge_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("content", sa.Text(), nullable=False, server_default=""),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"],
            name=op.f("fk_knowledge_items_workspace_id_workspaces"), ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_knowledge_items")),
    )
    op.create_index("ix_knowledge_items_workspace_id", "knowledge_items", ["workspace_id"])

    op.add_column("conversations", sa.Column("bot_paused", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("conversations", sa.Column("bot_pause_reason", sa.String(length=200), nullable=False, server_default=""))
    op.add_column("conversations", sa.Column("human_active_until", sa.DateTime(timezone=True), nullable=True))
    op.add_column("conversations", sa.Column("bot_draft", sa.Text(), nullable=False, server_default=""))
    op.add_column("conversations", sa.Column("bot_draft_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "conversations",
        sa.Column("bot_extracted", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
    )
    op.add_column("messages", sa.Column("author", sa.String(length=16), nullable=False, server_default=""))


def downgrade() -> None:
    op.drop_column("messages", "author")
    for column in ("bot_extracted", "bot_draft_at", "bot_draft", "human_active_until", "bot_pause_reason", "bot_paused"):
        op.drop_column("conversations", column)
    op.drop_index("ix_knowledge_items_workspace_id", table_name="knowledge_items")
    op.drop_table("knowledge_items")
