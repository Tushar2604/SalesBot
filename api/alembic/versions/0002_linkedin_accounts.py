"""Phase 2: LinkedIn accounts and proxies.

Revision ID: 0002_linkedin
Revises: 0001_tenancy
Create Date: 2026-09-15

`proxies` is created first because the account→proxy binding is a single
foreign key on `linkedin_accounts.proxy_id`, and it is UNIQUE: one proxy is
never shared by two accounts.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002_linkedin"
down_revision = "0001_tenancy"
branch_labels = None
depends_on = None

account_status = postgresql.ENUM(
    "disconnected",
    "connecting",
    "pending_2fa",
    "pending_email_pin",
    "challenge",
    "active",
    "paused",
    "auth_lost",
    "blocked",
    "disabled",
    name="linkedin_account_status",
    create_type=False,
)
proxy_status = postgresql.ENUM(
    "untested", "healthy", "degraded", "dead", name="proxy_status", create_type=False
)


def upgrade() -> None:
    bind = op.get_bind()
    account_status.create(bind, checkfirst=True)
    proxy_status.create(bind, checkfirst=True)

    op.create_table(
        "proxies",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("label", sa.String(length=120), nullable=False),
        sa.Column("provider", sa.String(length=60), nullable=False),
        sa.Column("scheme", sa.String(length=10), nullable=False),
        sa.Column("host", sa.String(length=255), nullable=False),
        sa.Column("port", sa.Integer(), nullable=False),
        # Credentials are ciphertext; nothing here is readable without the key.
        sa.Column("username_ciphertext", sa.LargeBinary(), nullable=True),
        sa.Column("password_ciphertext", sa.LargeBinary(), nullable=True),
        sa.Column("country", sa.String(length=2), nullable=False),
        sa.Column("city", sa.String(length=80), nullable=False),
        sa.Column("sticky_session_id", sa.String(length=120), nullable=False),
        sa.Column("status", proxy_status, nullable=False),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_exit_ip", sa.String(length=64), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_proxies"),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name="fk_proxies_workspace_id_workspaces",
            ondelete="CASCADE",
        ),
    )
    op.create_index("ix_proxies_workspace_id", "proxies", ["workspace_id"])

    op.create_table(
        "linkedin_accounts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("label", sa.String(length=120), nullable=False),
        sa.Column("login_email", sa.String(length=320), nullable=False),
        sa.Column("profile_urn", sa.String(length=120), nullable=True),
        sa.Column("public_id", sa.String(length=160), nullable=False),
        sa.Column("full_name", sa.String(length=200), nullable=False),
        sa.Column("headline", sa.String(length=400), nullable=False),
        sa.Column("avatar_url", sa.Text(), nullable=False),
        sa.Column("profile_country", sa.String(length=2), nullable=False),
        sa.Column("status", account_status, nullable=False),
        sa.Column("status_detail", sa.Text(), nullable=False),
        # Secrets: ciphertext only.
        sa.Column("session_ciphertext", sa.LargeBinary(), nullable=True),
        sa.Column("session_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fingerprint", postgresql.JSONB(), nullable=False),
        sa.Column("proxy_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("challenge_ciphertext", sa.LargeBinary(), nullable=True),
        sa.Column("challenge_expires_at", sa.DateTime(timezone=True), nullable=True),
        # Safety state.
        sa.Column("health_score", sa.Integer(), nullable=False),
        sa.Column("consecutive_errors", sa.Integer(), nullable=False),
        sa.Column("circuit_open_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("circuit_reason", sa.String(length=200), nullable=False),
        sa.Column("test_mode", sa.Boolean(), nullable=False),
        sa.Column("caps", postgresql.JSONB(), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("ramp_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_action_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_allowed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_linkedin_accounts"),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name="fk_linkedin_accounts_workspace_id_workspaces",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            name="fk_linkedin_accounts_created_by_id_users",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["proxy_id"],
            ["proxies.id"],
            name="fk_linkedin_accounts_proxy_id_proxies",
            ondelete="SET NULL",
        ),
        # One profile per workspace: two sessions for one account would race
        # for its single execution slot.
        sa.UniqueConstraint("workspace_id", "profile_urn", name="uq_linkedin_accounts_ws_profile"),
        # Two accounts on one IP is itself a clustering signal.
        sa.UniqueConstraint("proxy_id", name="uq_linkedin_accounts_proxy_id"),
    )
    op.create_index("ix_linkedin_accounts_workspace_id", "linkedin_accounts", ["workspace_id"])
    op.create_index("ix_linkedin_accounts_status", "linkedin_accounts", ["status"])
    op.create_index(
        "ix_linkedin_accounts_dispatch", "linkedin_accounts", ["status", "next_allowed_at"]
    )


def downgrade() -> None:
    op.drop_table("linkedin_accounts")
    op.drop_table("proxies")

    bind = op.get_bind()
    proxy_status.drop(bind, checkfirst=True)
    account_status.drop(bind, checkfirst=True)
