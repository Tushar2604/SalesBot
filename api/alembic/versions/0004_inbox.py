"""Phase 5: conversations and messages, the unified inbox.

Revision ID: 0004_inbox
Revises: 0003_outreach
Create Date: 2026-09-15

Creation order follows the foreign keys: conversations (references
workspaces, linkedin_accounts, leads, campaign_leads, all already present)
before messages (references conversations).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0004_inbox"
down_revision = "0003_outreach"
branch_labels = None
depends_on = None

conversation_label = postgresql.ENUM(
    "none",
    "interested",
    "not_interested",
    "out_of_office",
    "question",
    "other",
    name="conversation_label",
    create_type=False,
)
label_source = postgresql.ENUM("manual", "ai", name="label_source", create_type=False)
message_direction = postgresql.ENUM(
    "inbound", "outbound", name="message_direction", create_type=False
)

_ALL_ENUMS = (conversation_label, label_source, message_direction)

_TS = {"server_default": sa.func.now(), "nullable": False}


def upgrade() -> None:
    bind = op.get_bind()
    for enum_type in _ALL_ENUMS:
        enum_type.create(bind, checkfirst=True)

    op.create_table(
        "conversations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("linkedin_account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("lead_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("campaign_lead_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("conversation_urn", sa.String(length=200), nullable=False),
        sa.Column("participant_urn", sa.String(length=200), nullable=False),
        sa.Column("participant_name", sa.String(length=200), nullable=False),
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_message_text", sa.Text(), nullable=False),
        sa.Column("last_message_from_me", sa.Boolean(), nullable=False),
        sa.Column("unread", sa.Boolean(), nullable=False),
        sa.Column("label", conversation_label, nullable=False),
        sa.Column("label_source", label_source, nullable=False),
        sa.Column("snoozed_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), **_TS),
        sa.Column("updated_at", sa.DateTime(timezone=True), **_TS),
        sa.PrimaryKeyConstraint("id", name="pk_conversations"),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name="fk_conversations_workspace_id_workspaces",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["linkedin_account_id"],
            ["linkedin_accounts.id"],
            name="fk_conversations_linkedin_account_id_linkedin_accounts",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["lead_id"],
            ["leads.id"],
            name="fk_conversations_lead_id_leads",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["campaign_lead_id"],
            ["campaign_leads.id"],
            name="fk_conversations_campaign_lead_id_campaign_leads",
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint(
            "linkedin_account_id", "conversation_urn", name="uq_conversations_account_urn"
        ),
    )
    op.create_index("ix_conversations_workspace_id", "conversations", ["workspace_id"])
    op.create_index("ix_conversations_account_id", "conversations", ["linkedin_account_id"])
    op.create_index("ix_conversations_lead_id", "conversations", ["lead_id"])
    op.create_index(
        "ix_conversations_inbox_list", "conversations", ["workspace_id", "last_message_at"]
    )

    op.create_table(
        "messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("remote_event_urn", sa.String(length=200), nullable=False),
        sa.Column("direction", message_direction, nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("raw", postgresql.JSONB(), nullable=False),
        sa.Column("ai_label", conversation_label, nullable=True),
        sa.Column("ai_classified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), **_TS),
        sa.Column("updated_at", sa.DateTime(timezone=True), **_TS),
        sa.PrimaryKeyConstraint("id", name="pk_messages"),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name="fk_messages_workspace_id_workspaces",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            name="fk_messages_conversation_id_conversations",
            ondelete="CASCADE",
        ),
    )
    op.create_index("ix_messages_workspace_id", "messages", ["workspace_id"])
    op.create_index("ix_messages_conversation_id", "messages", ["conversation_id", "sent_at"])
    # Partial: an empty remote_event_urn (synthesized rows, or events LinkedIn
    # doesn't id) must not collide with another empty one in the same thread.
    op.create_index(
        "uq_messages_conversation_event",
        "messages",
        ["conversation_id", "remote_event_urn"],
        unique=True,
        postgresql_where=sa.text("remote_event_urn <> ''"),
    )


def downgrade() -> None:
    op.drop_table("messages")
    op.drop_table("conversations")

    bind = op.get_bind()
    for enum_type in reversed(_ALL_ENUMS):
        enum_type.drop(bind, checkfirst=True)
