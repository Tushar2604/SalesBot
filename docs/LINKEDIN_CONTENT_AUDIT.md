# LinkedIn Content Studio — Pre-implementation Audit

Audit of the existing codebase performed before writing any Content Studio code,
to establish what must be reused and what genuinely has to be built.

Repository layout: `api/` (FastAPI + Celery, Python 3.12), `web/` (Next.js 15 App
Router + Tailwind), Postgres + Redis + MinIO via `docker-compose.yml`.

---

## 1. Existing LinkedIn integration

**It is an unofficial private-API integration, not an official LinkedIn API app.**

| Piece | File | What it does |
|---|---|---|
| Driver seam (Protocol) | [driver.py](../api/app/linkedin/driver.py) | The interface every LinkedIn call goes through: `authenticate_with_cookie`, `authenticate_with_credentials`, `submit_challenge`, `verify_session`, `get_profile`, `search_people`, `list_conversations`, `send_invitation`, `send_message`, `warm_session`. **There is no `create_post` / `share` method.** |
| Implementation | [voyager.py](../api/app/linkedin/voyager.py) | `MobileVoyagerDriver` — httpx client against `https://www.linkedin.com/voyager/api/*` carrying a mobile fingerprint and the account's `li_at` session cookie through its bound proxy. |
| Response classifier | [classify.py](../api/app/linkedin/classify.py) | Maps every response to a `ResponseClass` the safety engine reasons about. |
| Session persistence | [session_store.py](../api/app/linkedin/session_store.py) | Fernet-encrypted `SessionBundle` (cookies + CSRF) on `linkedin_accounts.session_ciphertext`. |
| Device identity | [fingerprint.py](../api/app/linkedin/fingerprint.py) | Frozen-at-connect mobile client identity. |
| Egress identity | [proxy.py](../api/app/linkedin/proxy.py) | One proxy per account, bound for life. |
| Volume/ramp limits | [caps.py](../api/app/linkedin/caps.py) | Daily/weekly caps, warm-up ramp, working hours. |
| Account health | [health.py](../api/app/linkedin/health.py) | Health score + circuit breaker. |

**Critical finding for this project:** there is **no OAuth flow, no LinkedIn
developer-app credentials, no `access_token`/`refresh_token` column, and no
`w_member_social` grant anywhere in the codebase.** `grep` for `oauth`,
`access_token` (LinkedIn sense), `client_secret`, `w_member_social`, `ugcPosts`,
`/rest/posts` returns nothing. The only "token" columns are our own JWT refresh
sessions (`refresh_sessions`) and the encrypted LinkedIn *cookie* bundle.

Consequence, per the project's Phase 13 rule: publishing **cannot** be built on
the existing Voyager driver, because that would mean posting through a private,
undocumented endpoint using a harvested session cookie. A separate, officially
sanctioned authorization is required. See
[LINKEDIN_PUBLISHING_REQUIREMENTS.md](LINKEDIN_PUBLISHING_REQUIREMENTS.md).

## 2. Existing authentication

- **Application auth**: Argon2id passwords, JWT access token (30 min, memory-only
  on the client) + rotating httpOnly refresh cookie with reuse detection
  ([security.py](../api/app/core/security.py), [routes_auth.py](../api/app/api/routes_auth.py),
  [auth_service.py](../api/app/services/auth_service.py)).
- **Client**: `web/lib/api.ts` keeps the access token in module memory only,
  single-flight refresh on 401. Nothing auth-related is in `localStorage`.
- **Reuse**: all Content Studio endpoints sit behind the same `CurrentUser` /
  `require_workspace` dependencies. No new auth system.

## 3. Existing account model

`LinkedInAccount` ([linkedin.py](../api/app/models/linkedin.py)):
`workspace_id`, `created_by_id`, `label`, `login_email`, `profile_urn`,
`public_id`, `full_name`, `headline`, `avatar_url`, `status`
(`LinkedInAccountStatus`: disconnected/connecting/pending_2fa/pending_email_pin/
challenge/active/paused/auth_lost/blocked/disabled), `session_ciphertext`,
`fingerprint`, `proxy_id` (UNIQUE), `challenge_ciphertext`, health/circuit fields,
`caps`, `timezone`, pacing fields.

Unique constraint `(workspace_id, profile_urn)`. Every query goes through
`linkedin_service.get_account(db, workspace_id, account_id)`, which is already the
workspace-ownership check the Content Studio needs for "posting as".

**Reuse**: this is *the* account model. Publishing authorization is added as
columns on this table, not a second account entity.

## 4. Existing API capabilities

`/api/v1` router ([router.py](../api/app/api/router.py)) with
auth, workspaces, linkedin, leads, campaigns, inbox, notifications, analytics.
Conventions to follow exactly:

- Tenant routes are prefixed `/workspaces/{workspace_id}/…`; `Workspace_`
  dependency proves membership and yields `WorkspaceContext`.
- Domain errors (`NotFoundError`, `ConflictError`, `ValidationFailedError`,
  `PermissionDeniedError`, `QuotaExceededError`, `UpstreamError`) are raised from
  services and translated centrally; the client maps them in `ApiError`.
- Routers are thin; logic lives in `app/services/*`, schemas in `app/schemas/*`.
- Async handlers use `AsyncSession`; Celery tasks use `session_scope()` (sync).
- Multipart upload precedent exists: `POST /leads/import-csv` with
  `Annotated[UploadFile, File()]`, plus `uploadForm()` on the client.

## 5. Existing scheduling infrastructure

Fully built and must be reused:

- **Celery + Redis** ([celery_app.py](../api/app/worker/celery_app.py)) with
  queues `linkedin.action`, `linkedin.sync`, `email.send`, `ai`, `webhooks`,
  `default`; `acks_late` + `reject_on_worker_lost`.
- **Beat**: `scheduler.tick` every 60 s, session verification every 30 min,
  inbound polling every 10 min.
- **Durable task rows**: `ActionTask` with a UNIQUE `idempotency_key` — the
  established pattern for "a redelivered broker message must not act twice".
- **Per-account execution slot**: Redis lock in
  [locks.py](../api/app/scheduler/locks.py) (`li:acct:{id}:slot`, TTL-guarded,
  released only by the owner).
- **Pacing / quota / gates**: [pacing.py](../api/app/scheduler/pacing.py),
  [quota.py](../api/app/scheduler/quota.py),
  [dispatcher.py](../api/app/scheduler/dispatcher.py).

No second scheduler will be created. Scheduled posts get a durable row with a
status machine, a Beat sweep that claims due rows, and the same
transaction/lock discipline.

## 6. Existing media handling

**None.** This is the one infrastructure gap.

- `boto3` is already a dependency (`api/pyproject.toml`).
- `S3_ENDPOINT_URL`, `S3_REGION`, `S3_BUCKET`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`
  already exist in `app/config.py`, `.env.example`, and `docker-compose.yml`.
- A **MinIO service is already running** in compose with a `miniodata` volume.
- But no code references S3 at all: no bucket bootstrap, no upload helper, no
  asset model. CSV import reads `UploadFile` into memory and never stores it.

**Decision**: build the media layer on the storage provider that is already
configured and running (S3/MinIO via boto3). No new provider.

## 7. Existing permissions

Roles are `WorkspaceRole.OWNER | ADMIN | MEMBER` with `rank` / `can_act_as`,
enforced by `ctx.require_role(...)` or `Depends(require_role(...))`; the client
mirrors it with `hasRole()`. Non-members receive 404, not 403, so workspace
existence is not probeable.

The brief's `OWNER/ADMIN/EDITOR/VIEWER` is a four-tier model this product does not
have. Introducing new roles would change the tenancy enum used by campaigns,
leads, inbox and billing — exactly the kind of replacement Phase 34 forbids. The
existing three tiers are mapped instead (documented in
[LINKEDIN_CONTENT_STUDIO.md](LINKEDIN_CONTENT_STUDIO.md)):

| Brief role | This product | Content Studio rights |
|---|---|---|
| OWNER | `owner` | everything, incl. delete + approve + publish |
| ADMIN | `admin` | create/edit/schedule/publish/approve |
| EDITOR | `member` | create/edit/delete own drafts, submit for approval |
| VIEWER | *(no equivalent; nearest is `member` read paths)* | — |

## 8. Existing UI components

Next.js 15 App Router, Tailwind with a custom palette (`ink`, `accent`, `brand`,
`state.ok/warn/bad`) and component classes in `globals.css` (`.card`, `.input`,
`.btn-primary`, `.btn-ghost`, `.btn-danger`, `.badge`, `.label`).

Reusable: `AppSidebar` (nav lives in the `NAV` array), `AppTopbar`, `TabBar`,
`StatusPill`/`HealthBar`, `StatCard`, `NotificationBell`, `icons.tsx`,
`Placeholder`, `lib/session.tsx` (`useSession`, `hasRole`), `lib/api.ts`
(`apiFetch`, `uploadForm`, `ApiError`).

Note: `@tanstack/react-query` is a dependency but **is not used anywhere** —
every page uses `useEffect` + `useState`. New pages follow the existing pattern
rather than introducing a second data-fetching style.

## 9. What can be reused

1. Auth, session, workspace scoping, role checks — unchanged.
2. `LinkedInAccount` as the single account entity (extended with publishing-grant
   columns).
3. Celery app, queues, Beat, `session_scope()`, Redis locks, idempotency-key
   discipline.
4. `Notification` + `notification_service.create` / `create_sync` + the bell UI.
5. `audit.record` / `record_sync` for every state change.
6. Fernet `app.core.crypto` for the publishing token.
7. Anthropic client pattern from `app/ai/classify.py`, plus the already-configured
   but unused `AI_GENERATION_MODEL`.
8. Error taxonomy, API/service/schema layering, alembic migration style.
9. Tailwind design system and shell components.
10. S3/MinIO configuration + running service + `boto3`.

## 10. What is missing

| Missing | Plan |
|---|---|
| Any post/content model | New `linkedin_posts`, `linkedin_post_media`, `post_templates`, `media_assets`, `post_queues` tables (migration `0006_content_studio`). |
| Official publishing authorization | New OAuth 2.0 (3-legged) grant for `w_member_social`, stored **encrypted on the existing account row**, with explicit capability detection and a reconnect flow. Never faked. |
| Publishing driver method | New `app/linkedin/publishing.py` speaking the documented REST Posts API — kept separate from the Voyager driver on purpose. |
| Media storage | New `app/services/media_service.py` on boto3/MinIO. |
| Post scheduler/worker | New `app/worker/tasks/content.py` + a Beat sweep, reusing locks and status-transition idempotency. |
| AI generation | New `app/ai/content.py` (generate/improve), reusing the Anthropic client pattern. |
| Post analytics | Architecture prepared; **no fabricated numbers** — the UI shows "Analytics unavailable" until a `r_member_social` grant exists. |
| Approval workflow | New statuses + a per-workspace toggle in `workspaces.settings`; off by default. |
| Content Studio UI | New `/content` routes and components. |
| Notification types | Extend `notification_type` enum (post scheduled/published/failed/approval/authorization). |
