"""Leads, lists, the dedupe ledger, and blocklists.

Two invariants live in this schema rather than in application code, because
application checks get forgotten and constraints do not:

1. **`contacted_leads` is unique per (workspace, person).** Nobody is contacted
   twice by two of the same customer's accounts. Two of your own reps hitting
   one prospect is the complaint that loses a customer.
2. **`leads` is unique per (workspace, person)** so re-importing the same CSV
   or search twice updates rows instead of multiplying them.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, Timestamps, UUIDPrimaryKey


class LeadSource(enum.StrEnum):
    CSV = "csv"
    LINKEDIN_SEARCH = "linkedin_search"
    SALES_NAVIGATOR = "sales_navigator"
    MANUAL = "manual"
    API = "api"


class ImportStatus(enum.StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class BlocklistKind(enum.StrEnum):
    """What a blocklist entry matches on."""

    DOMAIN = "domain"  # email domain, e.g. "competitor.com"
    COMPANY = "company"  # company name, case-insensitive contains
    PROFILE = "profile"  # a specific LinkedIn public id


class LeadList(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "lead_lists"
    __table_args__ = (Index("ix_lead_lists_workspace_id", "workspace_id"),)

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    source: Mapped[LeadSource] = mapped_column(
        Enum(LeadSource, name="lead_source", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        default=LeadSource.CSV,
    )
    # Import progress, so the UI can report "412 of 900 imported" honestly.
    import_status: Mapped[ImportStatus] = mapped_column(
        Enum(ImportStatus, name="import_status", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        default=ImportStatus.COMPLETED,
    )
    import_detail: Mapped[str] = mapped_column(Text, nullable=False, default="")
    total_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    imported_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    skipped_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    leads: Mapped[list[Lead]] = relationship(back_populates="lead_list")


class Lead(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "leads"
    __table_args__ = (
        # Re-importing the same person updates rather than duplicates. The
        # public id is the stable human-readable handle; the URN can be absent
        # until the profile is fetched.
        UniqueConstraint("workspace_id", "public_id", name="uq_leads_workspace_public_id"),
        Index("ix_leads_workspace_id", "workspace_id"),
        Index("ix_leads_list_id", "list_id"),
        Index("ix_leads_workspace_urn", "workspace_id", "linkedin_urn"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    list_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("lead_lists.id", ondelete="SET NULL")
    )

    # Identity. `public_id` is the /in/<slug> handle and is required: without it
    # there is no way to act on the person.
    public_id: Mapped[str] = mapped_column(String(160), nullable=False)
    linkedin_urn: Mapped[str] = mapped_column(String(120), nullable=False, default="")

    first_name: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    last_name: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    headline: Mapped[str] = mapped_column(String(400), nullable=False, default="")
    company: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    title: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    location: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    country: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    email: Mapped[str] = mapped_column(String(320), nullable=False, default="")
    avatar_url: Mapped[str] = mapped_column(Text, nullable=False, default="")

    source: Mapped[LeadSource] = mapped_column(
        Enum(LeadSource, name="lead_source", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        default=LeadSource.CSV,
    )
    # Arbitrary CSV columns the user mapped, available to message templates.
    custom_fields: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    # Whatever the profile fetch returned, kept for AI personalisation context.
    enriched: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    enriched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    lead_list: Mapped[LeadList | None] = relationship(back_populates="leads")

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()

    @property
    def profile_url(self) -> str:
        return f"https://www.linkedin.com/in/{self.public_id}" if self.public_id else ""


class ContactedLead(UUIDPrimaryKey, Base):
    """Workspace-wide ledger of everyone already contacted.

    Written the moment an outbound action succeeds, and checked before any
    enrollment. The unique constraint is the enforcement — not a query.
    """

    __tablename__ = "contacted_leads"
    __table_args__ = (
        UniqueConstraint("workspace_id", "public_id", name="uq_contacted_leads_ws_public_id"),
        Index("ix_contacted_leads_workspace_id", "workspace_id"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    public_id: Mapped[str] = mapped_column(String(160), nullable=False)
    lead_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("leads.id", ondelete="SET NULL")
    )
    # Which account and campaign reached them, for the "why did we contact
    # this person" question support will eventually ask.
    linkedin_account_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("linkedin_accounts.id", ondelete="SET NULL")
    )
    campaign_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="SET NULL")
    )
    first_contacted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now()
    )


class BlocklistEntry(UUIDPrimaryKey, Timestamps, Base):
    """Never contact these. Checked at enrollment, not at send time."""

    __tablename__ = "blocklist_entries"
    __table_args__ = (
        UniqueConstraint("workspace_id", "kind", "value", name="uq_blocklist_ws_kind_value"),
        Index("ix_blocklist_entries_workspace_id", "workspace_id"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[BlocklistKind] = mapped_column(
        Enum(BlocklistKind, name="blocklist_kind", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )
    # Stored lower-cased so matching never depends on how it was typed.
    value: Mapped[str] = mapped_column(String(320), nullable=False)
    note: Mapped[str] = mapped_column(String(400), nullable=False, default="")
