"""Lead import, browsing, lists, and blocklists."""

from __future__ import annotations

import csv
import io
import json
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ValidationFailedError
from app.db import get_db
from app.deps import Workspace_
from app.models.leads import BlocklistKind
from app.models.tenancy import WorkspaceRole
from app.schemas.outreach import (
    BlocklistCreateRequest,
    BlocklistEntryResponse,
    CsvPreviewResponse,
    ImportReportResponse,
    ImportUrlsRequest,
    LeadListResponse,
    LeadPage,
    LeadResponse,
    RowProblem,
)
from app.services import lead_service

router = APIRouter(prefix="/workspaces/{workspace_id}", tags=["leads"])

MAPPABLE_FIELDS = [
    "public_id",
    "first_name",
    "last_name",
    "full_name",
    "email",
    "company",
    "title",
    "headline",
    "location",
]


def _to_lead(lead: object) -> LeadResponse:
    return LeadResponse.model_validate(lead)


@router.post("/leads/preview-csv", response_model=CsvPreviewResponse)
async def preview_csv(
    ctx: Workspace_,
    file: Annotated[UploadFile, File()],
) -> CsvPreviewResponse:
    """Reads only the header and a few rows, so the user can confirm the mapping.

    Importing straight away and reporting failures afterwards wastes the user's
    time when the profile-URL column is simply named something unexpected.
    """
    ctx.require_role(WorkspaceRole.MEMBER)

    raw = await file.read(512 * 1024)
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("cp1252", errors="replace")

    reader = csv.DictReader(io.StringIO(text))
    headers = list(reader.fieldnames or [])
    if not headers:
        raise ValidationFailedError("that file has no header row")

    samples: list[dict[str, str]] = []
    for row in reader:
        samples.append({k: (v or "")[:120] for k, v in row.items() if k})
        if len(samples) >= 3:
            break

    return CsvPreviewResponse(
        headers=headers,
        guessed_mapping=lead_service.guess_mapping(headers),
        sample_rows=samples,
        mappable_fields=MAPPABLE_FIELDS,
    )


@router.post(
    "/leads/import-csv", response_model=ImportReportResponse, status_code=status.HTTP_201_CREATED
)
async def import_csv(
    ctx: Workspace_,
    db: Annotated[AsyncSession, Depends(get_db)],
    file: Annotated[UploadFile, File()],
    list_name: Annotated[str, Form()] = "",
    mapping: Annotated[str, Form()] = "",
    skip_already_contacted: Annotated[bool, Form()] = True,
) -> ImportReportResponse:
    """Imports a CSV. `mapping` is JSON: {"CSV Header": "field_name"}."""
    ctx.require_role(WorkspaceRole.MEMBER)

    parsed_mapping: dict[str, str] | None = None
    if mapping.strip():
        try:
            candidate = json.loads(mapping)
        except json.JSONDecodeError as exc:
            raise ValidationFailedError("mapping must be valid JSON") from exc
        if not isinstance(candidate, dict):
            raise ValidationFailedError("mapping must be a JSON object")
        parsed_mapping = {str(k): str(v) for k, v in candidate.items() if v}

    content = await file.read(lead_service.MAX_CSV_BYTES + 1)
    report = await lead_service.import_csv(
        db,
        ctx,
        content=content,
        list_name=list_name,
        mapping=parsed_mapping,
        skip_already_contacted=skip_already_contacted,
    )

    return ImportReportResponse(
        list_id=report.list_id,
        list_name=report.list_name,
        total_rows=report.total_rows,
        imported=report.imported,
        updated=report.updated,
        skipped=report.skipped,
        problems=[
            RowProblem(row_number=p.row_number, reason=p.reason, public_id=p.public_id)
            for p in report.problems
        ],
    )


@router.post(
    "/leads/import-urls", response_model=ImportReportResponse, status_code=status.HTTP_201_CREATED
)
async def import_urls(
    payload: ImportUrlsRequest,
    ctx: Workspace_,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ImportReportResponse:
    """Adds leads pasted directly as LinkedIn profile links or handles."""
    ctx.require_role(WorkspaceRole.MEMBER)
    report = await lead_service.add_leads_from_urls(
        db, ctx, raw_input=payload.urls, list_name=payload.list_name
    )
    return ImportReportResponse(
        list_id=report.list_id,
        list_name=report.list_name,
        total_rows=report.total_rows,
        imported=report.imported,
        updated=report.updated,
        skipped=report.skipped,
        problems=[
            RowProblem(row_number=p.row_number, reason=p.reason, public_id=p.public_id)
            for p in report.problems
        ],
    )


@router.get("/leads", response_model=LeadPage)
async def list_leads(
    ctx: Workspace_,
    db: Annotated[AsyncSession, Depends(get_db)],
    list_id: uuid.UUID | None = None,
    search: Annotated[str, Query(max_length=120)] = "",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> LeadPage:
    leads, total = await lead_service.list_leads(
        db, ctx.workspace_id, list_id=list_id, search=search, limit=limit, offset=offset
    )
    return LeadPage(
        items=[_to_lead(lead) for lead in leads], total=total, limit=limit, offset=offset
    )


@router.get("/lead-lists", response_model=list[LeadListResponse])
async def list_lead_lists(
    ctx: Workspace_, db: Annotated[AsyncSession, Depends(get_db)]
) -> list[LeadListResponse]:
    lists = await lead_service.list_lead_lists(db, ctx.workspace_id)
    return [LeadListResponse.model_validate(item) for item in lists]


@router.delete("/lead-lists/{list_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_lead_list(
    list_id: uuid.UUID,
    ctx: Workspace_,
    db: Annotated[AsyncSession, Depends(get_db)],
    delete_leads: bool = False,
) -> None:
    ctx.require_role(WorkspaceRole.ADMIN)
    await lead_service.delete_lead_list(db, ctx, list_id, delete_leads=delete_leads)


# ── blocklist ────────────────────────────────────────────────────────────────


@router.get("/blocklist", response_model=list[BlocklistEntryResponse])
async def list_blocklist(
    ctx: Workspace_, db: Annotated[AsyncSession, Depends(get_db)]
) -> list[BlocklistEntryResponse]:
    entries = await lead_service.list_blocklist(db, ctx.workspace_id)
    return [BlocklistEntryResponse.model_validate(entry) for entry in entries]


@router.post(
    "/blocklist", response_model=BlocklistEntryResponse, status_code=status.HTTP_201_CREATED
)
async def add_blocklist_entry(
    payload: BlocklistCreateRequest,
    ctx: Workspace_,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> BlocklistEntryResponse:
    ctx.require_role(WorkspaceRole.ADMIN)
    entry = await lead_service.add_blocklist_entry(
        db, ctx, kind=BlocklistKind(payload.kind), value=payload.value, note=payload.note
    )
    return BlocklistEntryResponse.model_validate(entry)


@router.delete("/blocklist/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_blocklist_entry(
    entry_id: uuid.UUID, ctx: Workspace_, db: Annotated[AsyncSession, Depends(get_db)]
) -> None:
    ctx.require_role(WorkspaceRole.ADMIN)
    await lead_service.remove_blocklist_entry(db, ctx, entry_id)
