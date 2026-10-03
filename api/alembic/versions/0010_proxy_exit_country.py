"""Where each proxy was measured to exit, as opposed to the country it claims."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0010_proxy_exit_country"
down_revision = "0009_account_risk_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "proxies",
        sa.Column("exit_country", sa.String(length=2), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("proxies", "exit_country")
