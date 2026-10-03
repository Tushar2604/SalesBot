"""AI lead finder: chat → criteria → provider search → rank → import.

No LinkedIn account is involved at any step (see app/leadsearch). A found
lead meets LinkedIn only later, through the campaign's paced profile visit.
"""

from __future__ import annotations

import asyncio
import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import assistant as ai
from app.config import settings
from app.core.errors import NotFoundError, QuotaExceededError, ValidationFailedError
from app.core.logging import get_logger
from app.deps import WorkspaceContext
from app.leadsearch import criteria as criteria_mod
from app.leadsearch import providers as providers_mod
from app.leadsearch.criteria import SearchCriteria
from app.leadsearch.providers import Candidate, ProviderError
from app.models.lead_search import LeadSearch
from app.models.leads import ContactedLead, Lead, LeadList, LeadSource
from app.models.tenancy import AuditEvent
from app.services import audit, lead_service
from app.services.lead_service import ImportReport, RowOutcome, is_blocked, load_blocklist

log = get_logger(__name__)

_RAN = "lead_search.ran"
_MAX_MESSAGES = 60


@dataclass(slots=True)
class ChatOutcome:
    search: LeadSearch
    reply: str
    needs_clarification: bool = False
    # Provider problems worth showing ("Apollo is out of credits").
    notices: list[str] = field(default_factory=list)


def status() -> dict[str, Any]:
    ready = [p.name for p in providers_mod.configured()]
    return {
        "providers": ready,
        "ready": bool(ready),
        "ai_available": bool(ai.available_providers()),
        "daily_limit": settings.lead_search_daily_limit,
    }


async def searches_today(db: AsyncSession, workspace_id: uuid.UUID) -> int:
    start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    return int(
        await db.scalar(
            select(func.count(AuditEvent.id)).where(
                AuditEvent.workspace_id == workspace_id,
                AuditEvent.action == _RAN,
                AuditEvent.created_at >= start,
            )
        )
        or 0
    )


async def get_search(db: AsyncSession, workspace_id: uuid.UUID, search_id: uuid.UUID) -> LeadSearch:
    search = await db.get(LeadSearch, search_id)
    if search is None or search.workspace_id != workspace_id:
        raise NotFoundError("search not found")
    return search


async def list_searches(
    db: AsyncSession, workspace_id: uuid.UUID, limit: int = 30
) -> list[LeadSearch]:
    rows = await db.execute(
        select(LeadSearch)
        .where(LeadSearch.workspace_id == workspace_id)
        .order_by(LeadSearch.updated_at.desc())
        .limit(limit)
    )
    return list(rows.scalars())


def _say(search: LeadSearch, role: str, text: str) -> None:
    entry = {"role": role, "text": text, "at": datetime.now(UTC).isoformat()}
    # Reassign so SQLAlchemy sees the JSONB change.
    search.messages = [*(search.messages or []), entry][-_MAX_MESSAGES:]


# ── ranking ─────────────────────────────────────────────────────────────────


def _tokens(text: str) -> set[str]:
    return {t for t in re.split(r"[^a-z0-9+#]+", text.lower()) if len(t) > 1}


_STOP = {"of", "and", "the", "at", "in", "for", "head", "senior", "lead"}


def score(candidate: Candidate, criteria: SearchCriteria) -> Candidate:
    """How well a candidate fits, and why — providers rank loosely, and the
    reasons tell the user what each result was matched on."""
    reasons: list[str] = []
    points = 0.0
    role_text = f"{candidate.title} {candidate.headline}"
    role = _tokens(role_text)
    for title in criteria.titles:
        want = _tokens(title) - _STOP or _tokens(title)
        if want and want <= role:
            points += 3
            reasons.append(f"title matches “{title}”")
            break
        if want & role:
            points += 1.5
            reasons.append(f"title close to “{title}”")
            break
    location = candidate.location.lower()
    for place in criteria.locations:
        city = place.split(",")[0].strip().lower()
        if city and city in location:
            points += 2
            reasons.append(f"in {place.split(',')[0].strip()}")
            break
    company = candidate.company.lower()
    for name in criteria.companies:
        if name.lower() in company:
            points += 2
            reasons.append(f"works at {candidate.company}")
            break
    text = f"{role_text} {candidate.company}".lower()
    hits = [k for k in criteria.keywords + criteria.industries if k.lower() in text]
    if hits:
        points += len(hits)
        reasons.append("mentions " + ", ".join(hits[:3]))
    if candidate.first_name and (candidate.title or candidate.headline):
        points += 0.5  # a complete record is more useful than a bare URL
    candidate.score = points
    candidate.match_reasons = reasons
    return candidate


# ── chat ────────────────────────────────────────────────────────────────────


async def _existing(
    db: AsyncSession, workspace_id: uuid.UUID, ids: list[str]
) -> tuple[set[str], set[str]]:
    if not ids:
        return set(), set()
    in_leads = set(
        (
            await db.execute(
                select(func.lower(Lead.public_id)).where(
                    Lead.workspace_id == workspace_id, func.lower(Lead.public_id).in_(ids)
                )
            )
        ).scalars()
    )
    contacted = set(
        (
            await db.execute(
                select(func.lower(ContactedLead.public_id)).where(
                    ContactedLead.workspace_id == workspace_id,
                    func.lower(ContactedLead.public_id).in_(ids),
                )
            )
        ).scalars()
    )
    return in_leads, contacted


async def _find(
    criteria: SearchCriteria,
    exclude: set[str],
    transport: httpx.AsyncBaseTransport | None,
) -> tuple[list[Candidate], list[str], list[str]]:
    """Candidates from the providers in order, until enough new people are
    found. Returns (candidates, providers used, notices)."""
    wanted = criteria.count
    found: dict[str, Candidate] = {}
    used: list[str] = []
    notices: list[str] = []
    async with providers_mod.new_client(transport) as client:
        for provider in providers_mod.configured():
            # Ask for more than needed: some are dropped as already seen,
            # contacted or blocklisted.
            limit = min(100, wanted * 2 + len(exclude))
            try:
                rows = await provider.search(criteria, limit, client)
            except ProviderError as exc:
                notices.append(str(exc))
                log.warning("lead_search.provider_failed", provider=provider.name, detail=str(exc))
                continue
            except httpx.HTTPError as exc:
                notices.append(f"{provider.name} could not be reached ({type(exc).__name__})")
                log.warning(
                    "lead_search.provider_unreachable", provider=provider.name, exc_info=True
                )
                continue
            added = 0
            for row in rows:
                if row.public_id in exclude or row.public_id in found:
                    continue
                found[row.public_id] = row
                added += 1
            if added:
                used.append(provider.name)
            if len(found) >= wanted * 2:
                break
    return list(found.values()), used, notices


async def chat(
    db: AsyncSession,
    ctx: WorkspaceContext,
    message: str,
    search_id: uuid.UUID | None = None,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> ChatOutcome:
    """One chat turn: read the message, search, and store the results.

    `transport` replaces the HTTP transport to the providers (tests)."""
    message = message.strip()
    if not message:
        raise ValidationFailedError("Type what kind of people you are looking for")

    if search_id is not None:
        search = await get_search(db, ctx.workspace_id, search_id)
    else:
        search = LeadSearch(workspace_id=ctx.workspace_id, created_by_id=ctx.user.id)
        db.add(search)
        await db.flush()

    previous = SearchCriteria(**search.criteria) if search.criteria else None
    _say(search, "user", message)
    reading = await asyncio.to_thread(criteria_mod.interpret, message, previous)

    if reading.needs_clarification:
        _say(search, "assistant", reading.reply)
        await db.commit()
        return ChatOutcome(search=search, reply=reading.reply, needs_clarification=True)

    if not providers_mod.configured():
        reply = (
            "No lead data provider is connected yet, so I can't search. Add an EXA_API_KEY, "
            "PDL_API_KEY, APOLLO_API_KEY or BRAVE_SEARCH_API_KEY to the server's .env and "
            "restart the api."
        )
        _say(search, "assistant", reply)
        await db.commit()
        return ChatOutcome(search=search, reply=reply, needs_clarification=True)

    if await searches_today(db, ctx.workspace_id) >= settings.lead_search_daily_limit:
        raise QuotaExceededError(
            f"This workspace has used today's {settings.lead_search_daily_limit} lead searches. "
            "The limit resets at midnight UTC."
        )

    criteria = reading.criteria
    # "more" / "different people" in the same chat: never show someone twice.
    shown = {str(r.get("public_id", "")).lower() for r in search.results or []}
    same_search = previous is not None and criteria.model_dump(
        exclude={"count"}
    ) == previous.model_dump(exclude={"count"})
    exclude = shown if same_search else set()

    candidates, used, notices = await _find(criteria, exclude, transport)

    blocklist = await load_blocklist(db, ctx.workspace_id)
    in_leads, contacted = await _existing(db, ctx.workspace_id, [c.public_id for c in candidates])
    kept: list[Candidate] = []
    for candidate in candidates:
        if candidate.public_id in contacted:
            continue
        if is_blocked(
            blocklist, public_id=candidate.public_id, company=candidate.company, email=""
        ):
            continue
        kept.append(score(candidate, criteria))
    # Stable: equal scores keep the provider's own order.
    kept.sort(key=lambda c: -c.score)
    kept = kept[: criteria.count]

    rows = []
    for candidate in kept:
        row = candidate.to_dict()
        row["in_leads"] = candidate.public_id in in_leads
        rows.append(row)

    search.criteria = criteria.model_dump()
    search.results = rows
    search.provider = ",".join(used)
    search.runs = (search.runs or 0) + 1
    if not search.title:
        search.title = criteria.describe()[:200]

    skipped = len(candidates) - len(kept)
    if rows:
        reply = f"{reading.reply} Found {len(rows)} people."
        if skipped and contacted:
            reply += " I left out anyone you've already contacted or blocklisted."
    elif notices and not used:
        reply = "The lead data providers couldn't answer right now. " + " ".join(notices[:2])
    else:
        reply = (
            f"{reading.reply} Nobody new matched. Try a broader title, a nearby city, "
            "or fewer filters."
        )
    _say(search, "assistant", reply)
    await audit.record(
        db,
        _RAN,
        workspace_id=ctx.workspace_id,
        actor_user_id=ctx.user.id,
        target_type="lead_search",
        target_id=search.id,
        metadata={"providers": used, "results": len(rows), "criteria": criteria.describe()[:300]},
    )
    await db.commit()
    return ChatOutcome(search=search, reply=reply, notices=notices)


# ── import ──────────────────────────────────────────────────────────────────


async def import_results(
    db: AsyncSession,
    ctx: WorkspaceContext,
    search_id: uuid.UUID,
    public_ids: list[str],
    list_name: str = "",
) -> ImportReport:
    """Adds the chosen people from a search to a new lead list, ready to be
    added to a campaign. Existing leads are moved to the list and only have
    empty fields filled in."""
    search = await get_search(db, ctx.workspace_id, search_id)
    by_id = {str(r.get("public_id", "")).lower(): r for r in search.results or []}
    wanted = list(dict.fromkeys(p.strip().lower() for p in public_ids if p.strip()))
    if not wanted:
        raise ValidationFailedError("Choose at least one person to add")

    lead_list = LeadList(
        workspace_id=ctx.workspace_id,
        created_by_id=ctx.user.id,
        name=(list_name.strip() or f"AI search: {search.title}")[:160],
        source=LeadSource.AI_SEARCH,
    )
    db.add(lead_list)
    await db.flush()
    report = ImportReport(list_id=lead_list.id, list_name=lead_list.name)
    blocklist = await load_blocklist(db, ctx.workspace_id)

    for row_number, public_id in enumerate(wanted, start=1):
        row = by_id.get(public_id)
        if row is None:
            report.note(
                RowOutcome(row_number, "skipped", "not in this search's results", public_id)
            )
            continue
        company = str(row.get("company") or "")
        blocked = is_blocked(blocklist, public_id=public_id, company=company, email="")
        if blocked:
            report.note(RowOutcome(row_number, "skipped", blocked, public_id))
            continue
        values = {
            "first_name": str(row.get("first_name") or "")[:120],
            "last_name": str(row.get("last_name") or "")[:120],
            "headline": str(row.get("headline") or "")[:400],
            "company": company[:200],
            "title": str(row.get("title") or "")[:200],
            "location": str(row.get("location") or "")[:200],
            "avatar_url": str(row.get("avatar_url") or ""),
        }
        found_by = {
            "provider": row.get("provider", ""),
            "search_id": str(search.id),
            "criteria": search.title,
        }
        lead = (
            await db.execute(
                select(Lead).where(
                    Lead.workspace_id == ctx.workspace_id, func.lower(Lead.public_id) == public_id
                )
            )
        ).scalar_one_or_none()
        if lead is not None:
            for key, value in values.items():
                if value and not getattr(lead, key):
                    setattr(lead, key, value)
            lead.list_id = lead_list.id
            lead.enriched = {**(lead.enriched or {}), "found_by": found_by}
            report.note(RowOutcome(row_number, "updated", "already in your leads", public_id))
            continue
        db.add(
            Lead(
                workspace_id=ctx.workspace_id,
                public_id=public_id,
                source=LeadSource.AI_SEARCH,
                list_id=lead_list.id,
                enriched={"found_by": found_by},
                **values,
            )
        )
        report.note(RowOutcome(row_number, "imported", "", public_id))

    lead_list.total_rows = report.total_rows = len(wanted)
    lead_list.imported_count = report.imported + report.updated
    lead_list.skipped_count = report.skipped
    # Reflect it in the stored results so the chat shows "in your leads".
    skipped = {p.public_id for p in report.problems}
    added = {p for p in wanted if p in by_id and p not in skipped}
    search.results = [
        {**r, "in_leads": bool(r.get("in_leads")) or str(r.get("public_id", "")).lower() in added}
        for r in search.results or []
    ]
    await audit.record(
        db,
        "leads.imported_ai_search",
        workspace_id=ctx.workspace_id,
        actor_user_id=ctx.user.id,
        target_type="lead_list",
        target_id=lead_list.id,
        metadata={
            "search_id": str(search.id),
            "imported": report.imported,
            "updated": report.updated,
        },
    )
    await lead_service.emit_imported(db, ctx, report, "ai_lead_finder")
    await db.commit()
    return report
