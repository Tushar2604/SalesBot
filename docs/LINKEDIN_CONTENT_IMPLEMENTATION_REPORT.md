# LinkedIn Content Studio — implementation report

What was built, what it reuses, what it deliberately does not do, and what is
verified. Written after the work, against the running stack.

---

## 1. Existing architecture reused

Nothing below was rebuilt or replaced.

| Reused | How |
|---|---|
| Authentication | Same JWT access token + httpOnly refresh cookie. No second auth system. |
| Workspace scoping | Every route depends on `require_workspace`; handlers receive a proven `WorkspaceContext`. |
| Roles | `owner` / `admin` / `member` via `ctx.require_role` and `hasRole` — no fourth role introduced. |
| `LinkedInAccount` | *Extended* with publishing-grant columns rather than a second account entity. |
| Celery + Redis + Beat | New queue and Beat entry alongside `dispatcher-tick`. No second scheduler. |
| Idempotency discipline | The `ActionTask` pattern (durable row + UNIQUE key) applied to posts. |
| `session_scope()` | Worker transactions use the existing sync session helper. |
| Notifications | `notification_service.create` / `create_sync` and the existing bell UI. |
| Audit trail | `audit.record` / `record_sync` on every state change. |
| Fernet encryption | `app.core.crypto` for the OAuth token, as for session cookies and proxy credentials. |
| Error taxonomy | `NotFoundError`, `ConflictError`, `ValidationFailedError`, `PermissionDeniedError`, `UpstreamError`. |
| Anthropic client pattern | Copied from `app/ai/classify.py`; uses the already-configured, previously unused `AI_GENERATION_MODEL`. |
| S3/MinIO | The `S3_*` settings, `boto3` dependency and `minio` compose service that already existed with no code behind them. |
| Design system | Tailwind palette, `.card` / `.input` / `.btn-*` / `.badge`, `AppSidebar`, `TabBar`, icons, `useSession`, `apiFetch` / `uploadForm`. |

The automation product — campaign creation, lead import, the dispatcher, the
Voyager driver, the safety engine — is untouched. The only edits to existing
files are additive: nav entries, publishing columns/fields, a panel on the account
card, six new notification enum values, and doc links.

## 2. New components

**Backend**

| File | Purpose |
|---|---|
| `app/models/content.py` | `LinkedInPost`, `LinkedInPostMedia`, `MediaAsset`, `PostTemplate`, `PostQueue` |
| `app/linkedin/publishing.py` | Official REST publishing: capability detection, OAuth, Posts API, media upload |
| `app/services/content_service.py` | Post lifecycle, permissions, calendar, templates, queue |
| `app/services/media_service.py` | S3/MinIO upload, validation, presigned previews |
| `app/api/routes_content.py` | 24 endpoints |
| `app/schemas/content.py` | Request/response models |
| `app/worker/tasks/content.py` | `content.publish_post`, `content.sweep_due` |
| `app/ai/content.py` | Generate / improve suggestions |
| `alembic/versions/0006_content_studio.py` | Migration |

**Frontend**

| File | Purpose |
|---|---|
| `lib/content-api.ts` | Typed client + display helpers |
| `app/(app)/content/layout.tsx` | Section shell, sub-nav, toast host |
| `app/(app)/content/page.tsx`, `drafts/`, `scheduled/`, `published/` | Post lists |
| `app/(app)/content/new/`, `[id]/` | Composer |
| `app/(app)/content/calendar/` | Month / week / list views |
| `app/(app)/content/templates/`, `queue/` | Templates and publishing queue |
| `components/content/PostComposer.tsx` | Editor, autosave, action bar |
| `components/content/LinkedInPreview.tsx` | Live preview with the "see more" fold and media grid |
| `components/content/MediaUploader.tsx` | Drag & drop, progress, validation, alt text |
| `components/content/PostList.tsx` | Cards, filters, search, pagination, row actions |
| `components/content/ScheduleDialog.tsx` | Scheduling + publish confirmation |
| `components/content/AiAssistant.tsx` | Improve / generate panel |
| `components/content/ContentUi.tsx` | Status pill, modal, toasts, skeletons, empty states, publishing banner |

## 3. New APIs

26 endpoints: 24 under `/workspaces/{ws}/content`, plus
`POST|DELETE …/linkedin-accounts/{id}/publishing[/authorize]` and the public
`GET /linkedin/oauth/callback`. Full table in
[LINKEDIN_CONTENT_STUDIO.md §4](LINKEDIN_CONTENT_STUDIO.md).

## 4. Database changes

Migration `0006_content_studio`, applied and verified:

- New tables: `linkedin_posts`, `linkedin_post_media`, `media_assets`,
  `post_templates`, `post_queues`.
- New enums: `media_kind`, `post_status`, `post_visibility`; six values added to
  `notification_type` (`ADD VALUE IF NOT EXISTS`, so it is re-runnable).
- `linkedin_accounts` gains eight `publishing_*` columns.
- Key constraints: `uq_linkedin_posts_publish_key` (the double-publish guard),
  `uq_linkedin_post_media_position`, `uq_post_queues_workspace`, and the
  `ix_linkedin_posts_due` index the sweep reads.

## 5. Scheduler changes

- New Celery queue `content.publish`, routed by `content.*`, added to the worker's
  `-Q` list in compose.
- New Beat entry `content-sweep-due` → `content.sweep_due`, every 60 s.
- `app/worker/tasks/content.py` registered in the Celery `include` list.
- The existing `dispatcher-tick`, action queues and slot locks are unchanged.

## 6. LinkedIn integration changes

- `app/linkedin/publishing.py` is new and speaks only documented, versioned REST
  endpoints with a member OAuth token.
- `voyager.py`, `driver.py`, `session_store.py`, `fingerprint.py`, `proxy.py`,
  `caps.py` and `health.py` are **unmodified**. The Voyager driver has no
  publishing method and was not given one.
- `linkedin_service.to_response` now includes a publishing verdict and adds a
  warning when a grant is missing or lapsed.

## 7. Security changes

- OAuth tokens encrypted at rest; never serialised by any endpoint; never in
  `localStorage`. Asserted by a test that greps the whole account payload.
- Workspace isolation on posts, media, templates and queue; cross-workspace reads
  return 404 and cross-workspace account binding returns 404 (both tested).
- Publishing/scheduling gated on `admin`; members are limited to their own drafts
  (tested).
- OAuth callback protected by a signed, 15-minute `state` JWT; a forged state is
  rejected (tested).
- Media type, size and combination validated server-side regardless of the client.
- Every state change writes an audit event.

## 8. Tests

`215 passed` — the 170 that existed before, plus 45 new:

**`tests/test_content_api.py` (29)** — create/edit/delete draft, autosave and
reload, duplicate, media upload with a real PNG, unsupported type refused,
cross-workspace media refused, timezone conversion (09:30 IST → 04:00 UTC),
past-date refusal, reschedule leaving no second job, cancel, empty-post refusal,
publish enqueues the worker, missing capability reported (not faked),
unconfigured deployment reported, no token in the account payload, authorize URL
+ signed state, forged state rejected, analytics unavailable rather than zeroed,
workspace isolation, account-binding isolation, member cannot publish or schedule,
member cannot edit another's draft, approval workflow off by default and
configurable, template CRUD, calendar in the viewer's timezone, queue slot
assignment and reordering, status/search filters.

**`tests/test_content_worker.py` (16)** — publishes and records the URN/permalink,
uploads media first and caches the URN, **redelivery publishes exactly once**,
a post already `PUBLISHING` is not published again, cancelled/not-due/missing
posts are skipped, transient failure retried with backoff, retries bounded,
permanent failure stops and notifies, lost authorization clears the grant and
asks for a reconnect, expired grant fails before any network call, no grant means
never sent, badly overdue post failed rather than posted late, unexpected
exception never leaves a row stuck, sweep resolves an interrupted publish without
republishing.

**Live end-to-end** against the running stack (real Postgres, real MinIO, real
ASGI app): 25/25 checks — signup, capability, draft, autosave, upload, attach,
refusal, schedule with timezone conversion, calendar placement, cancel,
duplicate, template, queue slot, OAuth URL, worker publish, permalink, exactly
one post from three deliveries, media before post, analytics honesty,
notifications.

Frontend: `tsc --noEmit` clean, `next lint` clean, `next build` succeeds with all
8 Content Studio routes. Backend: `ruff check` clean on every new file.

## 9. Known limitations

1. **Analytics are unavailable in practice.** `r_member_social` is not part of the
   *Share on LinkedIn* product. The architecture is ready and the capability is
   checked per request; until a deployment is granted the scope, the UI says so.
   No placeholder numbers are shown anywhere.
2. **Video uploads are buffered in memory**, so the cap is 200 MB rather than
   LinkedIn's 500 MB. Raising it means converting that path to a streaming read.
3. **Mentions are not resolved.** `@name` is styled in the preview but sent as
   plain text; real mentions need entity URNs the current scopes do not provide.
4. **Link previews are not rendered.** LinkedIn generates the card server-side from
   the URL; faking one in the preview would show something that may not match.
5. **An interrupted publish requires human confirmation.** By design — see
   [LINKEDIN_POST_PUBLISHING.md §7](LINKEDIN_POST_PUBLISHING.md).
6. **No VIEWER role.** This product has three tiers; adding a fourth would touch
   campaigns, leads, inbox and billing. The mapping is documented instead.
7. **Media objects are not garbage-collected** when detached from a post. They may
   still be referenced by a template or another post; cleanup belongs in a storage
   lifecycle job.
8. **Approval is a single step.** One approver, no multi-stage chain.
9. **UI freshness while publishing** is a 5-second poll, matching how the accounts
   page already handles worker-driven state. No websockets were introduced.
10. **Refresh tokens are stored but not yet used.** LinkedIn issues them only to
    approved apps; when a token expires the product asks for a reconnect. Wiring
    the refresh exchange is a small, isolated change in `publishing.py`.

## 10. Future improvements

- `content.sync_analytics` Beat task once `r_member_social` is available.
- Streaming media upload, to lift the video cap to LinkedIn's own.
- Organization (Company Page) posting via `w_organization_social`.
- First-comment scheduling, a common LinkedIn practice.
- Best-time-to-post suggestions derived from real engagement, once analytics exist.
- Mention resolution if the required scope becomes available.

## 11. Final audit

| # | Question | Result |
|---|---|---|
| 1 | Can a user create a post? | Yes — `POST /content/posts`, tested + live |
| 2 | Can they save a draft? | Yes — `DRAFT` row, explicit **Save draft** and autosave |
| 3 | Does auto-save work? | Yes — 1.2 s debounce, snapshot-guarded, survives refresh; tested |
| 4 | Can they upload media? | Yes — real MinIO round trip, drag & drop, validation, alt text |
| 5 | Does the preview update live? | Yes — fold, hashtag tinting, media grid, per keystroke |
| 6 | Can they schedule? | Yes — date, time and timezone |
| 7 | Does timezone conversion work? | Yes — stored UTC, zone kept beside it; 09:30 IST = 04:00 UTC, tested and verified live |
| 8 | Does the worker execute? | Yes — Beat sweep + `content.publish_post`, verified end to end |
| 9 | Does publishing use the authorized integration? | Yes — official Posts API with a member OAuth token; the Voyager driver is not used and has no publish method |
| 10 | Is duplicate publishing prevented? | Yes — row lock + status check + UNIQUE `publish_key`; three deliveries produced one post |
| 11 | Can they reschedule? | Yes — a plain UPDATE; no second job is created (tested) |
| 12 | Can they cancel? | Yes — `CANCELLED`, schedule cleared |
| 13 | Can they retry a failure? | Yes — user-initiated, fresh attempt budget |
| 14 | Are permissions enforced? | Yes — publish/schedule require admin; members limited to their own drafts; both tested |
| 15 | Is workspace isolation enforced? | Yes — posts, media and account binding all tested cross-tenant |
| 16 | Are tokens secure? | Yes — Fernet at rest, never serialised, never in `localStorage`, signed OAuth state |
| 17 | Loading / error / empty states? | Yes — skeletons, empty states with a next action, error panels with retry, toasts, confirmations |
| 18 | Are tests passing? | Yes — 215 backend, `tsc`/`lint`/`build` clean, 25/25 live |
| 19 | Is documentation complete? | Yes — audit, requirements, studio, publishing walkthrough, this report |

**Nothing in this module is mocked.** Save draft, Schedule, Reschedule, Cancel,
Publish now, Retry, Duplicate, Repurpose, Submit, Approve, Request changes,
Delete, template CRUD, queue add/move/remove/pause, media upload and removal, and
Connect for publishing each call a real endpoint that changes a real row. The one
thing this deployment cannot do is reach LinkedIn itself — because no LinkedIn app
is configured here — and that is reported as a missing capability, with a route to
fixing it, rather than simulated.
