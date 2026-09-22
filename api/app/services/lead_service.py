"""Lead import, dedupe, and blocklists.

The hard part of importing is not parsing CSV — it is deciding what to do with a
row that is a near-duplicate, unusable, or someone the customer has already
burned. Those decisions are made here, once, and reported back per row so an
import never silently drops a third of the file.
"""

from __future__ import annotations

import csv
import io
import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError, ValidationFailedError
from app.deps import WorkspaceContext
from app.models.leads import (
    BlocklistEntry,
    BlocklistKind,
    ContactedLead,
    Lead,
    LeadList,
    LeadSource,
)
from app.services import audit

MAX_CSV_BYTES = 10 * 1024 * 1024  # 10 MB
MAX_ROWS = 50_000

# Matches /in/<slug> in any LinkedIn URL shape, with or without a trailing slash,
# query string, or locale prefix.
_PROFILE_URL_RE = re.compile(
    r"linkedin\.com/(?:[a-z]{2}/)?in/([A-Za-z0-9\-_%À-ÿ.]+)", re.IGNORECASE
)

# Column headers we recognise without the user mapping anything.
_AUTO_MAPPING: dict[str, tuple[str, ...]] = {
    "public_id": (
        "public_id",
        "publicid",
        "profile",
        "profile_url",
        "profileurl",
        "linkedin",
        "linkedin_url",
        "linkedinurl",
        "url",
        "profile link",
        "linkedin profile",
    ),
    "first_name": ("first_name", "firstname", "first", "given name", "given_name"),
    "last_name": ("last_name", "lastname", "last", "surname", "family name", "family_name"),
    "full_name": ("full_name", "fullname", "name"),
    "email": ("email", "email_address", "emailaddress", "work email", "e-mail"),
    "company": (
        "company",
        "company_name",
        "companyname",
        "organisation",
        "organization",
        "account",
        "employer",
    ),
    "title": ("title", "job_title", "jobtitle", "position", "role"),
    "headline": ("headline", "summary", "bio"),
    "location": ("location", "city", "region", "geo", "country"),
}


def extract_public_id(value: str) -> str:
    """Pulls the /in/<slug> handle out of a URL, or accepts a bare handle.

    A bare token is accepted because `priya-sharma` is a legitimate handle and
    is indistinguishable by shape from any other slug. Anything that *looks*
    like a URL or an address but is not a LinkedIn profile is rejected, which
    catches the common mistake of mapping the wrong column.
    """
    raw = (value or "").strip()
    if not raw:
        return ""

    match = _PROFILE_URL_RE.search(raw)
    if match:
        return match.group(1).rstrip("/").lower()

    # URL-ish or address-ish but not a LinkedIn profile: the column is wrong.
    if any(token in raw for token in ("://", "/", "@", " ", ".")):
        return ""

    # A bare slug. LinkedIn handles are alphanumeric with hyphens.
    if len(raw) >= 3 and re.fullmatch(r"[A-Za-z0-9\-_%À-ÿ]+", raw):
        return raw.lower()
    return ""


def _normalize_header(header: str) -> str:
    """Folds the ways a header can be spelled into one form.

    Real exports use "Job Title", "job_title", "Job-Title" and "jobtitle"
    interchangeably, so aliases are matched against a canonical form rather
    than listed four times each.
    """
    return re.sub(r"[\s\-_]+", "_", header.strip().lower()).strip("_")


def guess_mapping(headers: list[str]) -> dict[str, str]:
    """Best-effort column mapping, so the common CSV needs no configuration."""
    mapping: dict[str, str] = {}
    for header in headers:
        normalized = _normalize_header(header)
        collapsed = normalized.replace("_", "")
        for field_name, aliases in _AUTO_MAPPING.items():
            if field_name in mapping.values():
                continue
            canonical = {_normalize_header(alias) for alias in aliases}
            canonical |= {alias.replace("_", "") for alias in canonical}
            if normalized in canonical or collapsed in canonical:
                mapping[header] = field_name
                break
    return mapping


@dataclass(slots=True)
class RowOutcome:
    row_number: int
    status: str  # "imported" | "updated" | "skipped"
    reason: str = ""
    public_id: str = ""


@dataclass(slots=True)
class ImportReport:
    list_id: uuid.UUID
    list_name: str
    total_rows: int = 0
    imported: int = 0
    updated: int = 0
    skipped: int = 0
    # Only the first N problem rows are reported; a 50k-row file with a wrong
    # column should not produce a 50k-entry response.
    problems: list[RowOutcome] = field(default_factory=list)

    def note(self, outcome: RowOutcome, *, keep: int = 50) -> None:
        if outcome.status == "imported":
            self.imported += 1
        elif outcome.status == "updated":
            self.updated += 1
        else:
            self.skipped += 1
            if len(self.problems) < keep:
                self.problems.append(outcome)


async def load_blocklist(
    db: AsyncSession, workspace_id: uuid.UUID
) -> dict[BlocklistKind, set[str]]:
    rows = (
        await db.execute(
            select(BlocklistEntry.kind, BlocklistEntry.value).where(
                BlocklistEntry.workspace_id == workspace_id
            )
        )
    ).all()
    result: dict[BlocklistKind, set[str]] = {kind: set() for kind in BlocklistKind}
    for kind, value in rows:
        result[kind].add(value)
    return result


def is_blocked(
    blocklist: dict[BlocklistKind, set[str]], *, public_id: str, company: str, email: str
) -> str:
    """Returns the blocking reason, or "" when the lead is allowed."""
    if public_id.lower() in blocklist[BlocklistKind.PROFILE]:
        return "profile is on the blocklist"

    company_lower = company.lower()
    for blocked in blocklist[BlocklistKind.COMPANY]:
        if blocked and blocked in company_lower:
            return f"company matches blocklist entry {blocked!r}"

    if "@" in email:
        domain = email.rsplit("@", 1)[1].lower()
        if domain in blocklist[BlocklistKind.DOMAIN]:
            return f"email domain {domain} is on the blocklist"

    return ""


async def add_leads_from_urls(
    db: AsyncSession,
    ctx: WorkspaceContext,
    *,
    raw_input: str,
    list_name: str = "",
) -> ImportReport:
    """Adds leads pasted directly as LinkedIn profile URLs or bare handles.

    Splits on any whitespace, comma, or newline — a user pasting a handful of
    profile links rarely gets the separator "right", so this accepts all of
    the common ones rather than requiring one per line.
    """
    tokens = [t for t in re.split(r"[\s,;]+", raw_input.strip()) if t]
    if not tokens:
        raise ValidationFailedError("paste at least one LinkedIn profile URL or handle")
    if len(tokens) > 500:
        raise ValidationFailedError("paste at most 500 links at a time")

    lead_list = LeadList(
        workspace_id=ctx.workspace_id,
        created_by_id=ctx.user.id,
        name=list_name.strip() or f"Pasted links {datetime.now(UTC):%Y-%m-%d %H:%M}",
        source=LeadSource.MANUAL,
    )
    db.add(lead_list)
    await db.flush()

    report = ImportReport(list_id=lead_list.id, list_name=lead_list.name)
    blocklist = await load_blocklist(db, ctx.workspace_id)
    existing = {
        public_id.lower(): lead_id
        for lead_id, public_id in (
            await db.execute(
                select(Lead.id, Lead.public_id).where(Lead.workspace_id == ctx.workspace_id)
            )
        ).all()
    }
    seen_in_batch: set[str] = set()

    for row_number, token in enumerate(tokens, start=1):
        public_id = extract_public_id(token)
        if not public_id:
            report.note(RowOutcome(row_number, "skipped", "not a usable LinkedIn profile URL or handle"))
            continue
        if public_id in seen_in_batch:
            report.note(RowOutcome(row_number, "skipped", "duplicate in this batch", public_id))
            continue
        seen_in_batch.add(public_id)

        blocked = is_blocked(blocklist, public_id=public_id, company="", email="")
        if blocked:
            report.note(RowOutcome(row_number, "skipped", blocked, public_id))
            continue

        if public_id in existing:
            lead = await db.get(Lead, existing[public_id])
            if lead is not None:
                lead.list_id = lead_list.id
                report.note(RowOutcome(row_number, "updated", "already in your leads", public_id))
                continue

        db.add(
            Lead(
                workspace_id=ctx.workspace_id,
                public_id=public_id,
                source=LeadSource.MANUAL,
                list_id=lead_list.id,
            )
        )
        existing[public_id] = uuid.uuid4()
        report.note(RowOutcome(row_number, "imported", "", public_id))

    lead_list.total_rows = report.total_rows = len(tokens)
    lead_list.imported_count = report.imported + report.updated
    lead_list.skipped_count = report.skipped

    await audit.record(
        db,
        "leads.imported_urls",
        workspace_id=ctx.workspace_id,
        actor_user_id=ctx.user.id,
        target_type="lead_list",
        target_id=lead_list.id,
        metadata={"imported": report.imported, "updated": report.updated, "skipped": report.skipped},
    )
    return report


async def import_csv(
    db: AsyncSession,
    ctx: WorkspaceContext,
    *,
    content: bytes,
    list_name: str,
    mapping: dict[str, str] | None = None,
    skip_already_contacted: bool = True,
) -> ImportReport:
    """Parses a CSV into leads, reporting every row's fate.

    Runs inline rather than in a worker: the user is waiting, and a 10 MB cap
    keeps it fast. Larger imports belong in a background job.
    """
    if len(content) > MAX_CSV_BYTES:
        raise ValidationFailedError(f"that file is larger than {MAX_CSV_BYTES // (1024 * 1024)} MB")

    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        # Exports from Excel on Windows are routinely cp1252.
        text = content.decode("cp1252", errors="replace")

    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise ValidationFailedError("that file has no header row")

    resolved = mapping or guess_mapping(list(reader.fieldnames))
    if "public_id" not in resolved.values():
        raise ValidationFailedError(
            "no LinkedIn profile column found. Include a column of profile URLs "
            "(https://www.linkedin.com/in/...) and map it to 'public_id'."
        )

    lead_list = LeadList(
        workspace_id=ctx.workspace_id,
        created_by_id=ctx.user.id,
        name=list_name.strip() or f"CSV import {datetime.now(UTC):%Y-%m-%d %H:%M}",
        source=LeadSource.CSV,
    )
    db.add(lead_list)
    await db.flush()

    report = ImportReport(list_id=lead_list.id, list_name=lead_list.name)
    blocklist = await load_blocklist(db, ctx.workspace_id)

    contacted: set[str] = set()
    if skip_already_contacted:
        contacted = {
            value.lower()
            for value in (
                await db.execute(
                    select(ContactedLead.public_id).where(
                        ContactedLead.workspace_id == ctx.workspace_id
                    )
                )
            )
            .scalars()
            .all()
        }

    # Existing leads in this workspace, so a re-import updates instead of failing
    # on the unique constraint.
    existing = {
        public_id.lower(): lead_id
        for lead_id, public_id in (
            await db.execute(
                select(Lead.id, Lead.public_id).where(Lead.workspace_id == ctx.workspace_id)
            )
        ).all()
    }

    seen_in_file: set[str] = set()

    for row_number, row in enumerate(reader, start=2):  # row 1 is the header
        report.total_rows += 1
        if report.total_rows > MAX_ROWS:
            report.note(RowOutcome(row_number, "skipped", f"file exceeds {MAX_ROWS} rows"))
            break

        values: dict[str, str] = {}
        custom: dict[str, str] = {}
        for header, raw in row.items():
            if header is None:
                continue
            target = resolved.get(header)
            cleaned = (raw or "").strip()
            if target:
                values[target] = cleaned
            elif cleaned:
                custom[header.strip()] = cleaned

        public_id = extract_public_id(values.get("public_id", ""))
        if not public_id:
            report.note(RowOutcome(row_number, "skipped", "no usable LinkedIn profile URL"))
            continue

        if public_id in seen_in_file:
            report.note(RowOutcome(row_number, "skipped", "duplicate row in this file", public_id))
            continue
        seen_in_file.add(public_id)

        first = values.get("first_name", "")
        last = values.get("last_name", "")
        if not first and values.get("full_name"):
            parts = values["full_name"].split()
            first, last = parts[0], " ".join(parts[1:])

        blocked = is_blocked(
            blocklist,
            public_id=public_id,
            company=values.get("company", ""),
            email=values.get("email", ""),
        )
        if blocked:
            report.note(RowOutcome(row_number, "skipped", blocked, public_id))
            continue

        if skip_already_contacted and public_id in contacted:
            report.note(
                RowOutcome(
                    row_number,
                    "skipped",
                    "already contacted by this workspace",
                    public_id,
                )
            )
            continue

        fields: dict[str, Any] = {
            "first_name": first[:120],
            "last_name": last[:120],
            "headline": values.get("headline", "")[:400],
            "company": values.get("company", "")[:200],
            "title": values.get("title", "")[:200],
            "location": values.get("location", "")[:200],
            "email": values.get("email", "")[:320],
            "custom_fields": custom,
            "source": LeadSource.CSV,
            "list_id": lead_list.id,
        }

        if public_id in existing:
            lead = await db.get(Lead, existing[public_id])
            if lead is not None:
                for key, value in fields.items():
                    # Do not blank an existing value with an empty cell.
                    if value or key in ("custom_fields", "list_id", "source"):
                        setattr(lead, key, value)
                report.note(RowOutcome(row_number, "updated", "", public_id))
                continue

        db.add(Lead(workspace_id=ctx.workspace_id, public_id=public_id, **fields))
        existing[public_id] = uuid.uuid4()  # placeholder: prevents in-file re-add
        report.note(RowOutcome(row_number, "imported", "", public_id))

    lead_list.total_rows = report.total_rows
    lead_list.imported_count = report.imported + report.updated
    lead_list.skipped_count = report.skipped

    await audit.record(
        db,
        "leads.imported_csv",
        workspace_id=ctx.workspace_id,
        actor_user_id=ctx.user.id,
        target_type="lead_list",
        target_id=lead_list.id,
        metadata={
            "total_rows": report.total_rows,
            "imported": report.imported,
            "updated": report.updated,
            "skipped": report.skipped,
        },
    )
    return report


# ── queries ──────────────────────────────────────────────────────────────────


async def list_leads(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    *,
    list_id: uuid.UUID | None = None,
    search: str = "",
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[Lead], int]:
    conditions = [Lead.workspace_id == workspace_id]
    if list_id is not None:
        conditions.append(Lead.list_id == list_id)
    if search:
        pattern = f"%{search.lower()}%"
        conditions.append(
            func.lower(
                Lead.first_name + " " + Lead.last_name + " " + Lead.company + " " + Lead.public_id
            ).like(pattern)
        )

    total = int(await db.scalar(select(func.count()).select_from(Lead).where(*conditions)) or 0)
    rows = (
        (
            await db.execute(
                select(Lead)
                .where(*conditions)
                .order_by(Lead.created_at.desc())
                .limit(min(limit, 200))
                .offset(offset)
            )
        )
        .scalars()
        .all()
    )
    return list(rows), total


async def list_lead_lists(db: AsyncSession, workspace_id: uuid.UUID) -> list[LeadList]:
    return list(
        (
            await db.execute(
                select(LeadList)
                .where(LeadList.workspace_id == workspace_id)
                .order_by(LeadList.created_at.desc())
            )
        )
        .scalars()
        .all()
    )


async def delete_lead_list(
    db: AsyncSession, ctx: WorkspaceContext, list_id: uuid.UUID, *, delete_leads: bool
) -> int:
    lead_list = (
        await db.execute(
            select(LeadList).where(
                LeadList.id == list_id, LeadList.workspace_id == ctx.workspace_id
            )
        )
    ).scalar_one_or_none()
    if lead_list is None:
        raise NotFoundError("lead list not found")

    removed = 0
    if delete_leads:
        leads = (await db.execute(select(Lead).where(Lead.list_id == list_id))).scalars().all()
        for lead in leads:
            await db.delete(lead)
            removed += 1

    await db.delete(lead_list)
    await audit.record(
        db,
        "leads.list_deleted",
        workspace_id=ctx.workspace_id,
        actor_user_id=ctx.user.id,
        target_type="lead_list",
        target_id=list_id,
        metadata={"leads_deleted": removed},
    )
    return removed


# ── blocklist ────────────────────────────────────────────────────────────────


async def list_blocklist(db: AsyncSession, workspace_id: uuid.UUID) -> list[BlocklistEntry]:
    return list(
        (
            await db.execute(
                select(BlocklistEntry)
                .where(BlocklistEntry.workspace_id == workspace_id)
                .order_by(BlocklistEntry.created_at.desc())
            )
        )
        .scalars()
        .all()
    )


async def add_blocklist_entry(
    db: AsyncSession,
    ctx: WorkspaceContext,
    *,
    kind: BlocklistKind,
    value: str,
    note: str = "",
) -> BlocklistEntry:
    # Stored lower-cased so matching never depends on how it was typed.
    normalized = value.strip().lower()
    if not normalized:
        raise ValidationFailedError("a blocklist entry needs a value")
    if kind is BlocklistKind.PROFILE:
        normalized = extract_public_id(normalized) or normalized
    if kind is BlocklistKind.DOMAIN:
        normalized = normalized.removeprefix("@").removeprefix("www.")

    existing = (
        await db.execute(
            select(BlocklistEntry).where(
                BlocklistEntry.workspace_id == ctx.workspace_id,
                BlocklistEntry.kind == kind,
                BlocklistEntry.value == normalized,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    entry = BlocklistEntry(
        workspace_id=ctx.workspace_id, kind=kind, value=normalized, note=note.strip()[:400]
    )
    db.add(entry)
    await db.flush()
    await audit.record(
        db,
        "leads.blocklist_added",
        workspace_id=ctx.workspace_id,
        actor_user_id=ctx.user.id,
        target_type="blocklist_entry",
        target_id=entry.id,
        metadata={"kind": kind.value, "value": normalized},
    )
    return entry


async def remove_blocklist_entry(
    db: AsyncSession, ctx: WorkspaceContext, entry_id: uuid.UUID
) -> None:
    entry = (
        await db.execute(
            select(BlocklistEntry).where(
                BlocklistEntry.id == entry_id,
                BlocklistEntry.workspace_id == ctx.workspace_id,
            )
        )
    ).scalar_one_or_none()
    if entry is None:
        raise NotFoundError("blocklist entry not found")
    await db.delete(entry)
