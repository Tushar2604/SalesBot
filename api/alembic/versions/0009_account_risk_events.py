"""Per-account risk warnings: LinkedIn push-back and accepted risky overrides.

Adds the account_risk_events table and a notification type used when an
account is automatically paused for reaching its warning limit.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0009_account_risk_events"
down_revision = "0008_campaign_tracking"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE notification_type ADD VALUE IF NOT EXISTS 'account_risk'")

    op.create_table(
        "account_risk_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("linkedin_account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("kind", sa.String(length=60), nullable=False),
        sa.Column("strikes", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("detail", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("cleared_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cleared_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["linkedin_account_id"],
            ["linkedin_accounts.id"],
            name="fk_account_risk_events_linkedin_account_id_linkedin_accounts",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name="fk_account_risk_events_workspace_id_workspaces",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            name="fk_account_risk_events_actor_user_id_users",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["cleared_by_id"],
            ["users.id"],
            name="fk_account_risk_events_cleared_by_id_users",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_account_risk_events"),
    )
    op.create_index(
        "ix_account_risk_events_account_created",
        "account_risk_events",
        ["linkedin_account_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_account_risk_events_account_created", table_name="account_risk_events")
    op.drop_table("account_risk_events")
