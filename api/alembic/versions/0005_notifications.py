"""Notifications: the workspace-wide feed behind the bell icon.

Revision ID: 0005_notifications
Revises: 0004_inbox
Create Date: 2026-09-16
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0005_notifications"
down_revision = "0004_inbox"
branch_labels = None
depends_on = None

notification_type = postgresql.ENUM(
    "inbox_reply",
    "account_action_needed",
    "member_joined",
    "campaign_completed",
    name="notification_type",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    notification_type.create(bind, checkfirst=True)

    op.create_table(
        "notifications",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("type", notification_type, nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("body", sa.String(length=400), nullable=False),
        sa.Column("link", sa.String(length=300), nullable=False),
        sa.Column("read_by", postgresql.JSONB(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_notifications"),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name="fk_notifications_workspace_id_workspaces",
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_notifications_workspace_created", "notifications", ["workspace_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_table("notifications")

    bind = op.get_bind()
    notification_type.drop(bind, checkfirst=True)
