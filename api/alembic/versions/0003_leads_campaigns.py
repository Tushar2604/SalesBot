"""Phase 3 and 4: leads, lists, blocklists, campaigns, enrollments, action tasks, quota ledger.

Revision ID: 0003_outreach
Revises: 0002_linkedin
Create Date: 2026-09-15

Creation order follows the foreign keys: lists before leads, campaigns before
enrollments and the contacted ledger, enrollments before action tasks.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003_outreach"
down_revision = "0002_linkedin"
branch_labels = None
depends_on = None

lead_source = postgresql.ENUM(
    "csv",
    "linkedin_search",
    "sales_navigator",
    "manual",
    "api",
    name="lead_source",
    create_type=False,
)
import_status = postgresql.ENUM(
    "pending", "running", "completed", "failed", name="import_status", create_type=False
)
blocklist_kind = postgresql.ENUM(
    "domain", "company", "profile", name="blocklist_kind", create_type=False
)
campaign_status = postgresql.ENUM(
    "draft",
    "running",
    "paused",
    "completed",
    "archived",
    name="campaign_status",
    create_type=False,
)
step_type = postgresql.ENUM(
    "view_profile",
    "invite",
    "message",
    "withdraw_invite",
    "wait",
    name="step_type",
    create_type=False,
)
step_condition = postgresql.ENUM(
    "always",
    "if_accepted",
    "if_not_accepted",
    "if_replied",
    "if_not_replied",
    name="step_condition",
    create_type=False,
)
condition_fail_action = postgresql.ENUM(
    "skip", "stop", name="condition_fail_action", create_type=False
)
enrollment_state = postgresql.ENUM(
    "pending",
    "running",
    "replied",
    "completed",
    "stopped",
    "failed",
    "skipped",
    name="enrollment_state",
    create_type=False,
)
task_status = postgresql.ENUM(
    "pending",
    "dispatched",
    "succeeded",
    "failed",
    "skipped",
    "cancelled",
    name="task_status",
    create_type=False,
)

_ALL_ENUMS = (
    lead_source,
    import_status,
    blocklist_kind,
    campaign_status,
    step_type,
    step_condition,
    condition_fail_action,
    enrollment_state,
    task_status,
)

_TS = {"server_default": sa.func.now(), "nullable": False}


def upgrade() -> None:
    bind = op.get_bind()
    for enum_type in _ALL_ENUMS:
        enum_type.create(bind, checkfirst=True)

    op.create_table(
        "lead_lists",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("source", lead_source, nullable=False),
        sa.Column("import_status", import_status, nullable=False),
        sa.Column("import_detail", sa.Text(), nullable=False),
        sa.Column("total_rows", sa.Integer(), nullable=False),
        sa.Column("imported_count", sa.Integer(), nullable=False),
        sa.Column("skipped_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), **_TS),
        sa.Column("updated_at", sa.DateTime(timezone=True), **_TS),
        sa.PrimaryKeyConstraint("id", name="pk_lead_lists"),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name="fk_lead_lists_workspace_id_workspaces",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            name="fk_lead_lists_created_by_id_users",
            ondelete="SET NULL",
        ),
    )
    op.create_index("ix_lead_lists_workspace_id", "lead_lists", ["workspace_id"])

    op.create_table(
        "leads",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("list_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("public_id", sa.String(length=160), nullable=False),
        sa.Column("linkedin_urn", sa.String(length=120), nullable=False),
        sa.Column("first_name", sa.String(length=120), nullable=False),
        sa.Column("last_name", sa.String(length=120), nullable=False),
        sa.Column("headline", sa.String(length=400), nullable=False),
        sa.Column("company", sa.String(length=200), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("location", sa.String(length=200), nullable=False),
        sa.Column("country", sa.String(length=80), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("avatar_url", sa.Text(), nullable=False),
        sa.Column("source", lead_source, nullable=False),
        sa.Column("custom_fields", postgresql.JSONB(), nullable=False),
        sa.Column("enriched", postgresql.JSONB(), nullable=False),
        sa.Column("enriched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), **_TS),
        sa.Column("updated_at", sa.DateTime(timezone=True), **_TS),
        sa.PrimaryKeyConstraint("id", name="pk_leads"),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name="fk_leads_workspace_id_workspaces",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["list_id"],
            ["lead_lists.id"],
            name="fk_leads_list_id_lead_lists",
            ondelete="SET NULL",
        ),
        # Re-importing the same person updates rather than duplicates.
        sa.UniqueConstraint("workspace_id", "public_id", name="uq_leads_workspace_public_id"),
    )
    op.create_index("ix_leads_workspace_id", "leads", ["workspace_id"])
    op.create_index("ix_leads_list_id", "leads", ["list_id"])
    op.create_index("ix_leads_workspace_urn", "leads", ["workspace_id", "linkedin_urn"])

    op.create_table(
        "blocklist_entries",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", blocklist_kind, nullable=False),
        sa.Column("value", sa.String(length=320), nullable=False),
        sa.Column("note", sa.String(length=400), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), **_TS),
        sa.Column("updated_at", sa.DateTime(timezone=True), **_TS),
        sa.PrimaryKeyConstraint("id", name="pk_blocklist_entries"),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name="fk_blocklist_entries_workspace_id_workspaces",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("workspace_id", "kind", "value", name="uq_blocklist_ws_kind_value"),
    )
    op.create_index("ix_blocklist_entries_workspace_id", "blocklist_entries", ["workspace_id"])

    op.create_table(
        "campaigns",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("linkedin_account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("status", campaign_status, nullable=False),
        sa.Column("stop_on_reply", sa.Boolean(), nullable=False),
        sa.Column("settings", postgresql.JSONB(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), **_TS),
        sa.Column("updated_at", sa.DateTime(timezone=True), **_TS),
        sa.PrimaryKeyConstraint("id", name="pk_campaigns"),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name="fk_campaigns_workspace_id_workspaces",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            name="fk_campaigns_created_by_id_users",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["linkedin_account_id"],
            ["linkedin_accounts.id"],
            name="fk_campaigns_linkedin_account_id_linkedin_accounts",
            ondelete="CASCADE",
        ),
    )
    op.create_index("ix_campaigns_workspace_id", "campaigns", ["workspace_id"])
    op.create_index("ix_campaigns_status", "campaigns", ["status"])

    op.create_table(
        "campaign_steps",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("campaign_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("order_index", sa.Integer(), nullable=False),
        sa.Column("step_type", step_type, nullable=False),
        sa.Column("delay_hours", sa.Integer(), nullable=False),
        sa.Column("only_if", step_condition, nullable=False),
        sa.Column("on_condition_fail", condition_fail_action, nullable=False),
        sa.Column("template", sa.Text(), nullable=False),
        sa.Column("config", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), **_TS),
        sa.Column("updated_at", sa.DateTime(timezone=True), **_TS),
        sa.PrimaryKeyConstraint("id", name="pk_campaign_steps"),
        sa.ForeignKeyConstraint(
            ["campaign_id"],
            ["campaigns.id"],
            name="fk_campaign_steps_campaign_id_campaigns",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("campaign_id", "order_index", name="uq_campaign_steps_campaign_order"),
    )
    op.create_index("ix_campaign_steps_campaign_id", "campaign_steps", ["campaign_id"])

    op.create_table(
        "campaign_leads",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("campaign_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("lead_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("linkedin_account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("state", enrollment_state, nullable=False),
        sa.Column("current_step_index", sa.Integer(), nullable=False),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("invite_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("replied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_action_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("variant", sa.String(length=8), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=False),
        sa.Column("stopped_reason", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), **_TS),
        sa.Column("updated_at", sa.DateTime(timezone=True), **_TS),
        sa.PrimaryKeyConstraint("id", name="pk_campaign_leads"),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name="fk_campaign_leads_workspace_id_workspaces",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["campaign_id"],
            ["campaigns.id"],
            name="fk_campaign_leads_campaign_id_campaigns",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["lead_id"],
            ["leads.id"],
            name="fk_campaign_leads_lead_id_leads",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["linkedin_account_id"],
            ["linkedin_accounts.id"],
            name="fk_campaign_leads_linkedin_account_id_linkedin_accounts",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("campaign_id", "lead_id", name="uq_campaign_leads_campaign_lead"),
    )
    op.create_index("ix_campaign_leads_campaign_id", "campaign_leads", ["campaign_id"])
    op.create_index("ix_campaign_leads_due", "campaign_leads", ["state", "next_run_at"])
    op.create_index("ix_campaign_leads_account", "campaign_leads", ["linkedin_account_id"])

    op.create_table(
        "contacted_leads",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("public_id", sa.String(length=160), nullable=False),
        sa.Column("lead_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("linkedin_account_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("campaign_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("first_contacted_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_contacted_leads"),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name="fk_contacted_leads_workspace_id_workspaces",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["lead_id"],
            ["leads.id"],
            name="fk_contacted_leads_lead_id_leads",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["linkedin_account_id"],
            ["linkedin_accounts.id"],
            name="fk_contacted_leads_linkedin_account_id_linkedin_accounts",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["campaign_id"],
            ["campaigns.id"],
            name="fk_contacted_leads_campaign_id_campaigns",
            ondelete="SET NULL",
        ),
        # The dedupe guarantee: one row per person per workspace, enforced by
        # the database rather than by a query that could race.
        sa.UniqueConstraint("workspace_id", "public_id", name="uq_contacted_leads_ws_public_id"),
    )
    op.create_index("ix_contacted_leads_workspace_id", "contacted_leads", ["workspace_id"])

    op.create_table(
        "action_tasks",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("linkedin_account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("campaign_lead_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("step_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("action_type", step_type, nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", task_status, nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=64), nullable=False),
        sa.Column("dispatched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("result", postgresql.JSONB(), nullable=False),
        sa.Column("error_class", sa.String(length=40), nullable=False),
        sa.Column("error_detail", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_action_tasks"),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name="fk_action_tasks_workspace_id_workspaces",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["linkedin_account_id"],
            ["linkedin_accounts.id"],
            name="fk_action_tasks_linkedin_account_id_linkedin_accounts",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["campaign_lead_id"],
            ["campaign_leads.id"],
            name="fk_action_tasks_campaign_lead_id_campaign_leads",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["step_id"],
            ["campaign_steps.id"],
            name="fk_action_tasks_step_id_campaign_steps",
            ondelete="SET NULL",
        ),
        # The property that makes redelivery safe.
        sa.UniqueConstraint("idempotency_key", name="uq_action_tasks_idempotency_key"),
    )
    op.create_index(
        "ix_action_tasks_claim",
        "action_tasks",
        ["linkedin_account_id", "status", "scheduled_at"],
    )
    op.create_index("ix_action_tasks_enrollment", "action_tasks", ["campaign_lead_id"])
    op.create_index(
        "ix_action_tasks_workspace_created", "action_tasks", ["workspace_id", "created_at"]
    )

    op.create_table(
        "daily_quota_ledger",
        sa.Column("linkedin_account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("action_type", step_type, nullable=False),
        sa.Column("used", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint(
            "linkedin_account_id", "day", "action_type", name="pk_daily_quota_ledger"
        ),
        sa.ForeignKeyConstraint(
            ["linkedin_account_id"],
            ["linkedin_accounts.id"],
            name="fk_daily_quota_ledger_linkedin_account_id_linkedin_accounts",
            ondelete="CASCADE",
        ),
    )


def downgrade() -> None:
    op.drop_table("daily_quota_ledger")
    op.drop_table("action_tasks")
    op.drop_table("contacted_leads")
    op.drop_table("campaign_leads")
    op.drop_table("campaign_steps")
    op.drop_table("campaigns")
    op.drop_table("blocklist_entries")
    op.drop_table("leads")
    op.drop_table("lead_lists")

    bind = op.get_bind()
    for enum_type in reversed(_ALL_ENUMS):
        enum_type.drop(bind, checkfirst=True)
