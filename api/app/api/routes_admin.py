"""Platform admin panel: every LinkedIn account across every workspace.

Answers "who is running which LinkedIn account, and is it about to get
banned?" and gives the operator the three levers that matter: pause it, revoke
its access (the workspace can no longer use or reconnect it), or restore it.

Only `User.is_superuser` may call any of this; workspace admins cannot.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import NotFoundError, PermissionDeniedError
from app.db import get_db
from app.deps import CurrentUser
from app.linkedin import browser_profile, risk, session_store
from app.models.campaigns import ActionTask, Campaign, CampaignStatus, TaskStatus
from app.models.linkedin import AccountRiskEvent, LinkedInAccount, LinkedInAccountStatus
from app.models.tenancy import NotificationType, User, Workspace, WorkspaceMember
from app.schemas.admin import AdminAccount, AdminActionRequest, AdminMember, AdminRiskEvent
from app.services import audit, notification_service

router = APIRouter(prefix="/admin", tags=["admin"])


async def require_superuser(user: CurrentUser) -> User:
    if not user.is_superuser:
        raise PermissionDeniedError("platform administrators only")
    return user


Superuser = Annotated[User, Depends(require_superuser)]
DB = Annotated[AsyncSession, Depends(get_db)]


async def _account(db: AsyncSession, account_id: uuid.UUID) -> LinkedInAccount:
    account = await db.get(LinkedInAccount, account_id)
    if account is None:
        raise NotFoundError("LinkedIn account not found")
    return account


async def _row(db: AsyncSession, account: LinkedInAccount) -> AdminAccount:
    return (await _rows(db, [account]))[0]


async def _rows(db: AsyncSession, accounts: list[LinkedInAccount]) -> list[AdminAccount]:
    ids = [a.id for a in accounts]
    workspace_ids = {a.workspace_id for a in accounts}
    strikes = await risk.strikes_by_account(db, ids)

    workspaces = (
        {
            w.id: w
            for w in (
                await db.execute(
                    select(Workspace)
                    .options(selectinload(Workspace.members).selectinload(WorkspaceMember.user))
                    .where(Workspace.id.in_(workspace_ids))
                )
            ).scalars()
        }
        if workspace_ids
        else {}
    )
    creator_ids = {a.created_by_id for a in accounts if a.created_by_id}
    creators = (
        {
            u.id: u
            for u in (await db.execute(select(User).where(User.id.in_(creator_ids)))).scalars()
        }
        if creator_ids
        else {}
    )

    campaigns = (
        dict(
            (
                await db.execute(
                    select(Campaign.linkedin_account_id, func.count())
                    .where(
                        Campaign.linkedin_account_id.in_(ids),
                        Campaign.status == CampaignStatus.RUNNING,
                    )
                    .group_by(Campaign.linkedin_account_id)
                )
            ).all()
        )
        if ids
        else {}
    )

    latest: dict[uuid.UUID, AccountRiskEvent] = {}
    if ids:
        for event in (
            await db.execute(
                select(AccountRiskEvent)
                .where(AccountRiskEvent.linkedin_account_id.in_(ids))
                .order_by(AccountRiskEvent.created_at.desc())
            )
        ).scalars():
            latest.setdefault(event.linkedin_account_id, event)

    out: list[AdminAccount] = []
    for a in accounts:
        ws = workspaces.get(a.workspace_id)
        creator = creators.get(a.created_by_id) if a.created_by_id else None
        count = strikes.get(a.id, 0)
        last = latest.get(a.id)
        out.append(
            AdminAccount(
                id=a.id,
                label=a.label,
                full_name=a.full_name,
                public_id=a.public_id,
                profile_url=f"https://www.linkedin.com/in/{a.public_id}" if a.public_id else "",
                status=a.status,
                status_detail=a.status_detail,
                health_score=a.health_score,
                test_mode=a.test_mode,
                proxy=(f"{a.proxy.label} · {a.proxy.country}" if a.proxy else "direct (no proxy)"),
                last_action_at=a.last_action_at,
                connected_at=a.created_at,
                workspace_id=a.workspace_id,
                workspace_name=ws.name if ws else "",
                connected_by_email=creator.email if creator else "",
                connected_by_name=creator.full_name if creator else "",
                members=[
                    AdminMember(
                        user_id=m.user_id,
                        email=m.user.email,
                        full_name=m.user.full_name,
                        role=m.role.value,
                    )
                    for m in (ws.members if ws else [])
                ],
                warning_count=count,
                warning_limit=risk.STRIKE_LIMIT,
                risk_level=risk.risk_level(count),
                last_warning=last.detail if last else "",
                last_warning_at=last.created_at if last else None,
                active_campaigns=int(campaigns.get(a.id, 0)),
            )
        )
    return out


@router.get("/linkedin-accounts", response_model=list[AdminAccount])
async def list_accounts(_admin: Superuser, db: DB) -> list[AdminAccount]:
    accounts = list(
        (
            await db.execute(select(LinkedInAccount).order_by(LinkedInAccount.created_at.desc()))
        ).scalars()
    )
    rows = await _rows(db, accounts)
    # Most at-risk first: that is what the operator opens this page to find.
    order = {"critical": 0, "at_risk": 1, "watch": 2, "safe": 3}
    return sorted(rows, key=lambda r: (order.get(r.risk_level, 4), -r.warning_count))


@router.get("/linkedin-accounts/{account_id}/events", response_model=list[AdminRiskEvent])
async def list_events(account_id: uuid.UUID, _admin: Superuser, db: DB) -> list[AdminRiskEvent]:
    await _account(db, account_id)
    rows = (
        await db.execute(
            select(AccountRiskEvent, User.email)
            .outerjoin(User, User.id == AccountRiskEvent.actor_user_id)
            .where(AccountRiskEvent.linkedin_account_id == account_id)
            .order_by(AccountRiskEvent.created_at.desc())
            .limit(100)
        )
    ).all()
    window_start = datetime.now(UTC) - risk.STRIKE_WINDOW
    return [
        AdminRiskEvent(
            id=e.id,
            source=e.source,
            kind=e.kind,
            strikes=e.strikes,
            detail=e.detail,
            actor_email=email or "",
            created_at=e.created_at,
            cleared_at=e.cleared_at,
            counts=e.cleared_at is None and e.created_at >= window_start,
        )
        for e, email in rows
    ]


@router.post("/linkedin-accounts/{account_id}/pause", response_model=AdminAccount)
async def pause(
    account_id: uuid.UUID, payload: AdminActionRequest, admin: Superuser, db: DB
) -> AdminAccount:
    account = await _account(db, account_id)
    if account.status is LinkedInAccountStatus.ACTIVE:
        account.status = LinkedInAccountStatus.PAUSED
        account.status_detail = f"Paused by the platform administrator. {payload.reason}".strip()
    await audit.record(
        db,
        "admin.linkedin_account.paused",
        workspace_id=account.workspace_id,
        actor_user_id=admin.id,
        target_type="linkedin_account",
        target_id=account.id,
        note=payload.reason,
    )
    return await _row(db, account)


@router.post("/linkedin-accounts/{account_id}/revoke", response_model=AdminAccount)
async def revoke(
    account_id: uuid.UUID, payload: AdminActionRequest, admin: Superuser, db: DB
) -> AdminAccount:
    """Cuts the workspace off from this LinkedIn account: the stored session is
    destroyed, queued actions are cancelled, and it cannot be reconnected until
    an administrator restores it."""
    account = await _account(db, account_id)
    session_store.clear_session(account)
    session_store.clear_challenge(account)
    browser_profile.wipe(account.id)
    account.status = LinkedInAccountStatus.DISABLED
    account.status_detail = (
        f"Access revoked by the platform administrator. {payload.reason}".strip()
    )
    await db.execute(
        update(ActionTask)
        .where(
            ActionTask.linkedin_account_id == account.id,
            ActionTask.status.in_([TaskStatus.PENDING, TaskStatus.DISPATCHED]),
        )
        .values(
            status=TaskStatus.CANCELLED,
            error_class="cancelled",
            error_detail="access revoked by administrator",
            finished_at=datetime.now(UTC),
        )
    )
    await notification_service.create(
        db,
        account.workspace_id,
        NotificationType.ACCOUNT_RISK,
        f"Access to {account.full_name or account.label or 'a LinkedIn account'} was revoked",
        body=(payload.reason or "An administrator removed this account to protect it.")[:400],
        link="/accounts",
    )
    await audit.record(
        db,
        "admin.linkedin_account.revoked",
        workspace_id=account.workspace_id,
        actor_user_id=admin.id,
        target_type="linkedin_account",
        target_id=account.id,
        note=payload.reason,
    )
    return await _row(db, account)


@router.post("/linkedin-accounts/{account_id}/restore", response_model=AdminAccount)
async def restore(
    account_id: uuid.UUID, payload: AdminActionRequest, admin: Superuser, db: DB
) -> AdminAccount:
    """Gives a revoked account back. Its session was destroyed, so the
    workspace must sign in again before anything runs."""
    account = await _account(db, account_id)
    if account.status is LinkedInAccountStatus.DISABLED:
        account.status = LinkedInAccountStatus.DISCONNECTED
        account.status_detail = "Restored by the administrator. Sign in again to resume."
    await audit.record(
        db,
        "admin.linkedin_account.restored",
        workspace_id=account.workspace_id,
        actor_user_id=admin.id,
        target_type="linkedin_account",
        target_id=account.id,
        note=payload.reason,
    )
    return await _row(db, account)


@router.post("/risk-events/{event_id}/clear", response_model=AdminRiskEvent)
async def clear_event(event_id: uuid.UUID, admin: Superuser, db: DB) -> AdminRiskEvent:
    """Stops a reviewed warning from counting (e.g. a false alarm)."""
    event = await db.get(AccountRiskEvent, event_id)
    if event is None:
        raise NotFoundError("warning not found")
    if event.cleared_at is None:
        event.cleared_at = datetime.now(UTC)
        event.cleared_by_id = admin.id
    await audit.record(
        db,
        "admin.risk_event.cleared",
        workspace_id=event.workspace_id,
        actor_user_id=admin.id,
        target_type="account_risk_event",
        target_id=event.id,
    )
    return AdminRiskEvent(
        id=event.id,
        source=event.source,
        kind=event.kind,
        strikes=event.strikes,
        detail=event.detail,
        actor_email="",
        created_at=event.created_at,
        cleared_at=event.cleared_at,
        counts=False,
    )
