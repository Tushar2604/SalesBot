"""Per-lead connection tracking and an append-only event history.

Adds tracking columns to campaign_leads, the campaign_lead_events table, and a
notification type for accepted invites. Existing enrollments are backfilled from
the timestamps and tasks they already have, so old campaigns get a history too.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0008_campaign_tracking"
down_revision = "0007_assistant"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE notification_type ADD VALUE IF NOT EXISTS 'invite_update'")

    op.add_column(
        "campaign_leads",
        sa.Column("connection_state", sa.String(length=16), nullable=False, server_default="none"),
    )
    op.add_column("campaign_leads", sa.Column("viewed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("campaign_leads", sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("campaign_leads", sa.Column("next_check_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "campaign_leads", sa.Column("check_count", sa.Integer(), nullable=False, server_default="0")
    )
    op.add_column(
        "campaign_leads", sa.Column("connection_resolved_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_index("ix_campaign_leads_check", "campaign_leads", ["connection_state", "next_check_at"])

    op.create_table(
        "campaign_lead_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("campaign_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("campaign_lead_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("detail", sa.String(length=300), nullable=False, server_default=""),
        sa.Column("meta", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"],
            name=op.f("fk_campaign_lead_events_workspace_id_workspaces"), ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["campaign_id"], ["campaigns.id"],
            name=op.f("fk_campaign_lead_events_campaign_id_campaigns"), ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["campaign_lead_id"], ["campaign_leads.id"],
            name=op.f("fk_campaign_lead_events_campaign_lead_id_campaign_leads"), ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_campaign_lead_events")),
    )
    op.create_index(
        "ix_campaign_lead_events_lead", "campaign_lead_events", ["campaign_lead_id", "occurred_at"]
    )
    op.create_index(
        "ix_campaign_lead_events_campaign", "campaign_lead_events", ["campaign_id", "event_type"]
    )

    # ── backfill from what the enrollments already recorded ──────────────────
    op.execute(
        """
        UPDATE campaign_leads SET
            connection_state = CASE
                WHEN accepted_at IS NOT NULL THEN 'connected'
                WHEN invite_sent_at IS NOT NULL THEN 'pending'
                ELSE 'none' END,
            connection_resolved_at = accepted_at,
            next_check_at = CASE
                WHEN accepted_at IS NULL AND invite_sent_at IS NOT NULL THEN now() ELSE NULL END
        """
    )
    op.execute(
        """
        UPDATE campaign_leads cl SET viewed_at = t.finished_at
        FROM (
            SELECT campaign_lead_id, min(finished_at) AS finished_at
            FROM action_tasks
            WHERE action_type = 'view_profile' AND status = 'succeeded'
            GROUP BY campaign_lead_id
        ) t WHERE t.campaign_lead_id = cl.id
        """
    )

    def event(select_sql: str) -> None:
        op.execute(
            "INSERT INTO campaign_lead_events "
            "(id, workspace_id, campaign_id, campaign_lead_id, event_type, detail, meta, occurred_at) "
            + select_sql
        )

    event(
        "SELECT gen_random_uuid(), workspace_id, campaign_id, id, 'enrolled', '', '{}'::jsonb, created_at "
        "FROM campaign_leads"
    )
    event(
        "SELECT gen_random_uuid(), t.workspace_id, cl.campaign_id, cl.id, "
        "CASE t.action_type WHEN 'view_profile' THEN 'profile_viewed' "
        "WHEN 'invite' THEN 'invite_sent' ELSE 'message_sent' END, "
        "'', '{}'::jsonb, coalesce(t.finished_at, t.created_at) "
        "FROM action_tasks t JOIN campaign_leads cl ON cl.id = t.campaign_lead_id "
        "WHERE t.status = 'succeeded' AND t.action_type IN ('view_profile','invite','message')"
    )
    event(
        "SELECT gen_random_uuid(), workspace_id, campaign_id, id, 'invite_accepted', "
        "'Recorded before tracking existed', '{}'::jsonb, accepted_at "
        "FROM campaign_leads WHERE accepted_at IS NOT NULL"
    )
    event(
        "SELECT gen_random_uuid(), workspace_id, campaign_id, id, 'replied', '', '{}'::jsonb, replied_at "
        "FROM campaign_leads WHERE replied_at IS NOT NULL"
    )


def downgrade() -> None:
    op.drop_index("ix_campaign_lead_events_campaign", table_name="campaign_lead_events")
    op.drop_index("ix_campaign_lead_events_lead", table_name="campaign_lead_events")
    op.drop_table("campaign_lead_events")
    op.drop_index("ix_campaign_leads_check", table_name="campaign_leads")
    for column in (
        "connection_resolved_at", "check_count", "next_check_at",
        "last_checked_at", "viewed_at", "connection_state",
    ):
        op.drop_column("campaign_leads", column)
    # The 'invite_update' notification_type value is left in place, as in 0006.
