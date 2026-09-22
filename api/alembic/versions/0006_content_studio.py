"""Content Studio: posts, post media, media assets, templates, publishing queue.

Also extends `linkedin_accounts` with the official publishing grant (OAuth
access token for `w_member_social`), which is stored encrypted and is entirely
separate from the automation session cookie already on that table.

Revision ID: 0006_content_studio
Revises: 0005_notifications
Create Date: 2026-09-16
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0006_content_studio"
down_revision = "0005_notifications"
branch_labels = None
depends_on = None

media_kind = postgresql.ENUM("image", "video", "document", name="media_kind", create_type=False)
post_status = postgresql.ENUM(
    "draft",
    "pending_approval",
    "approved",
    "scheduled",
    "publishing",
    "published",
    "failed",
    "cancelled",
    name="post_status",
    create_type=False,
)
post_visibility = postgresql.ENUM(
    "PUBLIC", "CONNECTIONS", name="post_visibility", create_type=False
)

NEW_NOTIFICATION_TYPES = (
    "post_scheduled",
    "post_published",
    "post_failed",
    "post_needs_approval",
    "post_approved",
    "publishing_auth_expired",
)


def upgrade() -> None:
    bind = op.get_bind()
    media_kind.create(bind, checkfirst=True)
    post_status.create(bind, checkfirst=True)
    post_visibility.create(bind, checkfirst=True)

    # Postgres cannot add enum values inside a transaction block before 12; on
    # supported versions IF NOT EXISTS makes this re-runnable.
    for value in NEW_NOTIFICATION_TYPES:
        op.execute(f"ALTER TYPE notification_type ADD VALUE IF NOT EXISTS '{value}'")

    # ── media assets ─────────────────────────────────────────────────────────
    op.create_table(
        "media_assets",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("uploaded_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("kind", media_kind, nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=120), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("storage_key", sa.String(length=400), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("metadata", postgresql.JSONB(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_media_assets"),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"],
            name="fk_media_assets_workspace_id_workspaces", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["uploaded_by_id"], ["users.id"],
            name="fk_media_assets_uploaded_by_id_users", ondelete="SET NULL",
        ),
    )
    op.create_index(
        "ix_media_assets_workspace_created", "media_assets", ["workspace_id", "created_at"]
    )

    # ── posts ────────────────────────────────────────────────────────────────
    op.create_table(
        "linkedin_posts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("linkedin_account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("visibility", post_visibility, nullable=False),
        sa.Column("status", post_status, nullable=False),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("scheduled_timezone", sa.String(length=64), nullable=False),
        sa.Column("queue_position", sa.Integer(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("linkedin_post_id", sa.String(length=200), nullable=False),
        sa.Column("linkedin_url", sa.String(length=400), nullable=False),
        sa.Column("publish_key", sa.String(length=64), nullable=True),
        sa.Column("publishing_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_reason", sa.Text(), nullable=False),
        sa.Column("error_code", sa.String(length=80), nullable=False),
        sa.Column("request_id", sa.String(length=120), nullable=False),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("submitted_for_approval_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_note", sa.Text(), nullable=False),
        sa.Column("analytics", postgresql.JSONB(), nullable=False),
        sa.Column("analytics_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_linkedin_posts"),
        # The double-publish guard.
        sa.UniqueConstraint("publish_key", name="uq_linkedin_posts_publish_key"),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"],
            name="fk_linkedin_posts_workspace_id_workspaces", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"], ["users.id"],
            name="fk_linkedin_posts_created_by_id_users", ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["approved_by_id"], ["users.id"],
            name="fk_linkedin_posts_approved_by_id_users", ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["linkedin_account_id"], ["linkedin_accounts.id"],
            name="fk_linkedin_posts_linkedin_account_id_linkedin_accounts",
            ondelete="CASCADE",
        ),
    )
    op.create_index("ix_linkedin_posts_workspace_status", "linkedin_posts", ["workspace_id", "status"])
    op.create_index("ix_linkedin_posts_due", "linkedin_posts", ["status", "scheduled_at"])
    op.create_index("ix_linkedin_posts_account", "linkedin_posts", ["linkedin_account_id"])
    op.create_index(
        "ix_linkedin_posts_workspace_created", "linkedin_posts", ["workspace_id", "created_at"]
    )

    # ── post media ───────────────────────────────────────────────────────────
    op.create_table(
        "linkedin_post_media",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("post_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("media_asset_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("alt_text", sa.String(length=400), nullable=False),
        sa.Column("linkedin_asset_urn", sa.String(length=200), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_linkedin_post_media"),
        sa.UniqueConstraint("post_id", "position", name="uq_linkedin_post_media_position"),
        sa.ForeignKeyConstraint(
            ["post_id"], ["linkedin_posts.id"],
            name="fk_linkedin_post_media_post_id_linkedin_posts", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["media_asset_id"], ["media_assets.id"],
            name="fk_linkedin_post_media_media_asset_id_media_assets", ondelete="CASCADE",
        ),
    )
    op.create_index("ix_linkedin_post_media_post", "linkedin_post_media", ["post_id"])

    # ── templates ────────────────────────────────────────────────────────────
    op.create_table(
        "post_templates",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("media_asset_ids", postgresql.JSONB(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_post_templates"),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"],
            name="fk_post_templates_workspace_id_workspaces", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"], ["users.id"],
            name="fk_post_templates_created_by_id_users", ondelete="SET NULL",
        ),
    )
    op.create_index("ix_post_templates_workspace", "post_templates", ["workspace_id"])

    # ── publishing queue ─────────────────────────────────────────────────────
    op.create_table(
        "post_queues",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("paused", sa.Boolean(), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("slots", postgresql.JSONB(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_post_queues"),
        sa.UniqueConstraint("workspace_id", name="uq_post_queues_workspace"),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"],
            name="fk_post_queues_workspace_id_workspaces", ondelete="CASCADE",
        ),
    )

    # ── publishing grant on the existing account table ───────────────────────
    op.add_column(
        "linkedin_accounts",
        sa.Column("publishing_token_ciphertext", sa.LargeBinary(), nullable=True),
    )
    op.add_column(
        "linkedin_accounts",
        sa.Column("publishing_refresh_ciphertext", sa.LargeBinary(), nullable=True),
    )
    op.add_column(
        "linkedin_accounts",
        sa.Column("publishing_token_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "linkedin_accounts",
        sa.Column(
            "publishing_scopes", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")
        ),
    )
    op.add_column(
        "linkedin_accounts",
        sa.Column(
            "publishing_member_urn", sa.String(length=120), nullable=False, server_default=""
        ),
    )
    op.add_column(
        "linkedin_accounts",
        sa.Column("publishing_authorized_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "linkedin_accounts",
        sa.Column("publishing_authorized_by_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "linkedin_accounts",
        sa.Column("publishing_error", sa.Text(), nullable=False, server_default=""),
    )
    op.create_foreign_key(
        "fk_linkedin_accounts_publishing_authorized_by_id_users",
        "linkedin_accounts",
        "users",
        ["publishing_authorized_by_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_linkedin_accounts_publishing_authorized_by_id_users",
        "linkedin_accounts",
        type_="foreignkey",
    )
    for column in (
        "publishing_error",
        "publishing_authorized_by_id",
        "publishing_authorized_at",
        "publishing_member_urn",
        "publishing_scopes",
        "publishing_token_expires_at",
        "publishing_refresh_ciphertext",
        "publishing_token_ciphertext",
    ):
        op.drop_column("linkedin_accounts", column)

    op.drop_table("post_queues")
    op.drop_table("post_templates")
    op.drop_table("linkedin_post_media")
    op.drop_table("linkedin_posts")
    op.drop_table("media_assets")

    bind = op.get_bind()
    post_visibility.drop(bind, checkfirst=True)
    post_status.drop(bind, checkfirst=True)
    media_kind.drop(bind, checkfirst=True)
    # Values added to notification_type are intentionally left in place:
    # Postgres cannot remove enum values, and existing rows may reference them.
