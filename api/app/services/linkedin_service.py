"""LinkedIn account lifecycle, from the API's side of the boundary.

This module never talks to LinkedIn. It validates, persists intent, and enqueues
a worker task, because the actual sign-in must happen from the account's own
proxy — the session has to be born on the IP it will live on.

**Credential transit.** A password cannot be persisted, but the worker needs it.
It travels through the broker as Fernet ciphertext, so Redis holds an opaque
blob rather than a credential, and the worker discards the plaintext as soon as
LinkedIn has answered.
"""

from __future__ import annotations

import base64
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import encrypt_json
from app.core.errors import ConflictError, NotFoundError, ValidationFailedError
from app.deps import WorkspaceContext
from app.linkedin import caps as caps_mod
from app.linkedin import fingerprint as fp_mod
from app.linkedin import proxy as proxy_mod
from app.linkedin import publishing as publishing_mod
from app.models.linkedin import LinkedInAccount, LinkedInAccountStatus, Proxy
from app.schemas.linkedin import (
    CapsUpdateRequest,
    EffectiveCapsResponse,
    LinkedInAccountResponse,
    PublishingStatus,
    WorkingHours,
)
from app.services import audit


def seal_for_transit(payload: dict[str, Any]) -> str:
    """Encrypts a short-lived secret for the task queue."""
    return base64.b64encode(encrypt_json(payload)).decode()


# ── queries ──────────────────────────────────────────────────────────────────


async def list_accounts(db: AsyncSession, workspace_id: uuid.UUID) -> list[LinkedInAccount]:
    stmt = (
        select(LinkedInAccount)
        .where(LinkedInAccount.workspace_id == workspace_id)
        .order_by(LinkedInAccount.created_at)
    )
    return list((await db.execute(stmt)).scalars().all())


async def get_account(
    db: AsyncSession, workspace_id: uuid.UUID, account_id: uuid.UUID
) -> LinkedInAccount:
    stmt = select(LinkedInAccount).where(
        LinkedInAccount.id == account_id,
        LinkedInAccount.workspace_id == workspace_id,
    )
    account = (await db.execute(stmt)).scalar_one_or_none()
    if account is None:
        raise NotFoundError("LinkedIn account not found")
    return account


async def _claim_proxy(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    proxy_id: uuid.UUID | None,
    account: LinkedInAccount,
) -> Proxy | None:
    """Binds a proxy to an account, refusing to share one between two accounts."""
    if proxy_id is None:
        return None

    stmt = select(Proxy).where(
        Proxy.id == proxy_id,
        # A workspace may use its own proxies or claim from the shared pool.
        (Proxy.workspace_id == workspace_id) | (Proxy.workspace_id.is_(None)),
    )
    proxy = (await db.execute(stmt)).scalar_one_or_none()
    if proxy is None:
        raise NotFoundError("proxy not found")

    holder = await db.scalar(
        select(LinkedInAccount.id).where(
            LinkedInAccount.proxy_id == proxy_id, LinkedInAccount.id != account.id
        )
    )
    if holder is not None:
        raise ConflictError(
            "that proxy is already bound to another LinkedIn account; "
            "one account per IP is what keeps them from being clustered together"
        )

    account.proxy_id = proxy.id
    account.proxy = proxy
    if proxy.workspace_id is None:
        proxy.workspace_id = workspace_id
    return proxy


# ── creating accounts ────────────────────────────────────────────────────────


async def _find_by_login_email(
    db: AsyncSession, workspace_id: uuid.UUID, login_email: str
) -> LinkedInAccount | None:
    """An account already known by this email, regardless of its status.

    Reconnecting with the same email must reuse that row rather than spawn a
    second one — the unique constraint on `profile_urn` can't catch this on
    its own, since `profile_urn` is unknown until the worker signs in.
    """
    if not login_email:
        return None
    stmt = select(LinkedInAccount).where(
        LinkedInAccount.workspace_id == workspace_id,
        LinkedInAccount.login_email == login_email,
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def create_account(
    db: AsyncSession,
    ctx: WorkspaceContext,
    *,
    label: str,
    login_email: str,
    timezone: str,
    proxy_id: uuid.UUID | None,
    reconnect_account_id: uuid.UUID | None = None,
) -> LinkedInAccount:
    """Get-or-create: reconnecting an already-known email reuses that row.

    No network calls happen here either way — this only persists intent and
    freezes the device identity for a genuinely new account.

    `reconnect_account_id` covers the case `login_email` can't: a cookie-based
    reconnect has no email to match on, but the caller may already know which
    row this is (re-establishing a session on an account the UI already shows
    as disconnected). Reusing that row keeps its frozen fingerprint — a fresh
    row here would mean the same LinkedIn session cookie suddenly presenting
    as a different device, which is its own red flag independent of IP.
    """
    if ctx.workspace.outreach_paused:
        # Connecting is harmless, but surfacing this now avoids a confusing
        # "connected but nothing happens" state later.
        pass

    login_email = login_email.strip().lower()
    existing = await _find_by_login_email(db, ctx.workspace_id, login_email)
    if existing is None and reconnect_account_id is not None:
        existing = await db.get(LinkedInAccount, reconnect_account_id)
        if existing is not None and existing.workspace_id != ctx.workspace_id:
            existing = None
    if existing is not None:
        from app.linkedin import session_store

        existing.status = LinkedInAccountStatus.CONNECTING
        existing.status_detail = ""
        if label.strip():
            existing.label = label.strip()
        if timezone:
            existing.timezone = timezone
        session_store.clear_challenge(existing)
        if proxy_id is not None and existing.proxy_id != proxy_id:
            await _claim_proxy(db, ctx.workspace_id, proxy_id, existing)

        await audit.record(
            db,
            "linkedin_account.reconnect_requested",
            workspace_id=ctx.workspace_id,
            actor_user_id=ctx.user.id,
            target_type="linkedin_account",
            target_id=existing.id,
        )
        return existing

    account = LinkedInAccount(
        workspace_id=ctx.workspace_id,
        created_by_id=ctx.user.id,
        label=label.strip() or login_email or "LinkedIn account",
        login_email=login_email.strip().lower(),
        timezone=timezone or "UTC",
        status=LinkedInAccountStatus.CONNECTING,
        # Drawn once, here, and never regenerated for the life of the account.
        fingerprint=fp_mod.generate(timezone=timezone or "UTC"),
        caps=caps_mod.default_caps(),
        test_mode=True,
        ramp_started_at=datetime.now(UTC),
        # Set explicitly so presenting this fresh object never emits a lazy
        # SELECT — that would be IO from sync code inside an async handler.
        proxy=None,
    )
    db.add(account)
    await db.flush()

    await _claim_proxy(db, ctx.workspace_id, proxy_id, account)

    await audit.record(
        db,
        "linkedin_account.created",
        workspace_id=ctx.workspace_id,
        actor_user_id=ctx.user.id,
        target_type="linkedin_account",
        target_id=account.id,
        metadata={
            "device": fp_mod.describe(account.fingerprint),
            "proxy_assigned": proxy_id is not None,
        },
    )
    return account


async def update_caps(
    db: AsyncSession, ctx: WorkspaceContext, account: LinkedInAccount, payload: CapsUpdateRequest
) -> LinkedInAccount:
    """Applies requested limits. `caps.resolve` clamps them on every read."""
    caps = dict(account.caps or caps_mod.default_caps())

    for field in ("daily_invites", "daily_messages", "daily_views", "weekly_invites"):
        value = getattr(payload, field)
        if value is not None:
            caps[field] = value
    if payload.working_hours is not None:
        start, end = payload.working_hours.start, payload.working_hours.end
        if start >= end:
            raise ValidationFailedError("working hours must start before they end")
        caps["working_hours"] = {"start": start, "end": end}
    if payload.weekdays_only is not None:
        caps["weekdays_only"] = payload.weekdays_only

    account.caps = caps
    if payload.test_mode is not None:
        account.test_mode = payload.test_mode
    if payload.timezone is not None:
        account.timezone = payload.timezone
    if payload.label is not None:
        account.label = payload.label.strip() or account.label
    if payload.proxy_id is not None:
        await _claim_proxy(db, ctx.workspace_id, payload.proxy_id, account)

    await audit.record(
        db,
        "linkedin_account.caps_updated",
        workspace_id=ctx.workspace_id,
        actor_user_id=ctx.user.id,
        target_type="linkedin_account",
        target_id=account.id,
        metadata={"caps": caps, "test_mode": account.test_mode},
    )
    return account


async def set_paused(
    db: AsyncSession, ctx: WorkspaceContext, account: LinkedInAccount, paused: bool
) -> LinkedInAccount:
    """Per-account pause. Distinct from the circuit breaker, which is automatic."""
    if paused:
        if account.status is LinkedInAccountStatus.ACTIVE:
            account.status = LinkedInAccountStatus.PAUSED
    elif account.status is LinkedInAccountStatus.PAUSED:
        account.status = (
            LinkedInAccountStatus.ACTIVE
            if account.session_ciphertext
            else LinkedInAccountStatus.DISCONNECTED
        )

    await audit.record(
        db,
        "linkedin_account.paused" if paused else "linkedin_account.resumed",
        workspace_id=ctx.workspace_id,
        actor_user_id=ctx.user.id,
        target_type="linkedin_account",
        target_id=account.id,
    )
    return account


async def disconnect(
    db: AsyncSession, ctx: WorkspaceContext, account: LinkedInAccount
) -> LinkedInAccount:
    """Destroys the stored session but keeps the account's history and identity.

    The fingerprint and proxy survive on purpose: reconnecting the same profile
    with a *new* device identity is a worse signal than reusing the old one.
    """
    from app.linkedin import session_store

    session_store.clear_session(account)
    session_store.clear_challenge(account)
    account.status = LinkedInAccountStatus.DISCONNECTED
    account.status_detail = "disconnected by user"
    account.circuit_open_until = None
    account.circuit_reason = ""
    account.consecutive_errors = 0

    await audit.record(
        db,
        "linkedin_account.disconnected",
        workspace_id=ctx.workspace_id,
        actor_user_id=ctx.user.id,
        target_type="linkedin_account",
        target_id=account.id,
    )
    return account


async def delete_account(db: AsyncSession, ctx: WorkspaceContext, account: LinkedInAccount) -> None:
    # Release the proxy so it can be rebound, but keep the proxy record itself.
    account.proxy_id = None
    account.proxy = None

    await audit.record(
        db,
        "linkedin_account.deleted",
        workspace_id=ctx.workspace_id,
        actor_user_id=ctx.user.id,
        target_type="linkedin_account",
        target_id=account.id,
        metadata={"public_id": account.public_id},
    )
    await db.delete(account)


# ── presentation ─────────────────────────────────────────────────────────────


def to_response(account: LinkedInAccount) -> LinkedInAccountResponse:
    """Maps an account to its API shape, deriving every safety detail."""
    effective = caps_mod.resolve(account)
    in_hours, hours_detail = caps_mod.within_working_hours(account)
    resolved_proxy = proxy_mod.resolve(account.proxy)

    warnings: list[str] = []
    if resolved_proxy is None:
        warnings.append(proxy_mod.direct_connection_warning())
    if account.status is LinkedInAccountStatus.AUTH_LOST:
        warnings.append("The stored session is no longer valid. Reconnect to resume outreach.")
    if account.status is LinkedInAccountStatus.BLOCKED:
        warnings.append(
            "LinkedIn has restricted this account. Resolve it on linkedin.com before "
            "reconnecting; retrying automatically would make it worse."
        )
    if account.status.needs_user_action and account.status_detail:
        warnings.append(account.status_detail)
    geo_mismatch = (
        resolved_proxy is not None
        and bool(account.profile_country)
        and bool(resolved_proxy.country)
        and resolved_proxy.country.upper() != account.profile_country.upper()
    )
    if geo_mismatch and resolved_proxy is not None:
        warnings.append(
            f"The proxy exits in {resolved_proxy.country} but the profile says "
            f"{account.profile_country}. A user who never travels but appears to "
            "is a geolocation anomaly LinkedIn scores."
        )

    capability = publishing_mod.capability_for(account)
    if not capability.available and capability.code is not publishing_mod.CapabilityCode.NOT_CONFIGURED:
        # Surfaced on the account card as well as in the composer: a lapsed
        # posting grant is not obvious from the automation status, which can
        # still read "Active".
        warnings.append(capability.message)

    start, end = effective.working_hours
    return LinkedInAccountResponse(
        id=account.id,
        label=account.label,
        login_email=account.login_email,
        public_id=account.public_id,
        full_name=account.full_name,
        headline=account.headline,
        avatar_url=account.avatar_url,
        profile_url=(
            f"https://www.linkedin.com/in/{account.public_id}" if account.public_id else ""
        ),
        status=account.status,
        status_detail=account.status_detail,
        needs_user_action=account.status.needs_user_action,
        is_connected=account.is_connected,
        health_score=account.health_score,
        consecutive_errors=account.consecutive_errors,
        circuit_open_until=account.circuit_open_until,
        circuit_reason=account.circuit_reason,
        test_mode=account.test_mode,
        caps=EffectiveCapsResponse(
            daily_invites=effective.daily_invites,
            daily_messages=effective.daily_messages,
            daily_views=effective.daily_views,
            weekly_invites=effective.weekly_invites,
            working_hours=WorkingHours(start=f"{start:%H:%M}", end=f"{end:%H:%M}"),
            weekdays_only=effective.weekdays_only,
            timezone=effective.timezone,
            invite_limit_reason=effective.invite_limit_reason,
        ),
        within_working_hours=in_hours,
        working_hours_detail=hours_detail,
        device=fp_mod.describe(account.fingerprint),
        proxy_label=resolved_proxy.label if resolved_proxy else "",
        proxy_country=resolved_proxy.country if resolved_proxy else "",
        using_direct_connection=resolved_proxy is None,
        warnings=warnings,
        publishing=PublishingStatus(
            code=capability.code.value,
            available=capability.available,
            message=capability.message,
            remedy=capability.remedy,
            authorized_at=account.publishing_authorized_at,
            expires_at=account.publishing_token_expires_at,
            scopes=list(account.publishing_scopes or []),
        ),
        session_updated_at=account.session_updated_at,
        last_action_at=account.last_action_at,
        next_allowed_at=account.next_allowed_at,
        created_at=account.created_at,
    )


def next_step_for(account: LinkedInAccount) -> tuple[str, str]:
    """What the UI should do next, and what to tell the user."""
    match account.status:
        case LinkedInAccountStatus.CONNECTING:
            return "poll", "Signing in through this account's assigned connection…"
        case LinkedInAccountStatus.PENDING_2FA:
            return "code", "LinkedIn sent a verification code to your phone. Enter it below."
        case LinkedInAccountStatus.PENDING_EMAIL_PIN:
            return "code", "LinkedIn emailed a verification code. Enter it below."
        case LinkedInAccountStatus.CHALLENGE:
            return (
                "resolve",
                "LinkedIn wants to verify this sign-in. Open linkedin.com, complete the "
                "check, then reconnect.",
            )
        case LinkedInAccountStatus.ACTIVE:
            return "done", "Connected."
        case LinkedInAccountStatus.BLOCKED:
            return "resolve", "LinkedIn has restricted this account."
        case LinkedInAccountStatus.AUTH_LOST:
            return "reconnect", account.status_detail or "Sign-in failed."
        case _:
            return "reconnect", account.status_detail or "Not connected."
