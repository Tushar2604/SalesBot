# LinkedIn Content Studio

Compose, preview, schedule and publish LinkedIn posts from inside the platform,
through the same workspace, permission and queue infrastructure the outreach
product already uses.

This module **extends** the existing system. It adds no second authentication
system, no second scheduler, no second storage provider and no second
notification service. What it does add is set out in §2 of
[the audit](LINKEDIN_CONTENT_AUDIT.md).

---

## 1. Architecture

```
web/app/(app)/content/*        Next.js pages: list, composer, calendar, templates, queue
        │  lib/content-api.ts  typed client over the shared apiFetch/uploadForm
        ▼
api/app/api/routes_content.py  thin handlers behind require_workspace
        │
        ├── services/content_service.py   post lifecycle, calendar, templates, queue
        ├── services/media_service.py     S3/MinIO upload + presigned previews
        └── ai/content.py                 Claude suggestions (never auto-publishes)
        │
        ▼
Postgres: linkedin_posts, linkedin_post_media, media_assets,
          post_templates, post_queues
        ▲
        │  content.sweep_due  (Celery Beat, every 60s)
        │  content.publish_post  (queue: content.publish)
        │
api/app/worker/tasks/content.py
        │
        ▼
api/app/linkedin/publishing.py   official REST Posts API, member OAuth token
```

Two boundaries do most of the work:

- **The API never talks to LinkedIn.** It validates, persists and enqueues —
  matching the rule the outreach side already follows.
- **Publishing lives behind one module.** `publishing.py` is the only code that
  posts, and it holds no cookie, fingerprint or proxy. The automation driver
  (`voyager.py`) is untouched by this feature.

### Scheduling is state, not a queued job

A scheduled post is a row: `status = SCHEDULED` plus a UTC `scheduled_at`. A Beat
sweep claims whatever is due. No delayed job is pinned to a timestamp, so
rescheduling, editing and cancelling are ordinary `UPDATE`s. There is no orphaned
job to chase and no way for an old job and a new one to both fire — which is the
usual source of duplicate posts in tools like this.

## 2. User flow

```
Content Studio → Create post → pick the LinkedIn account → write →
attach media → watch the live preview → Save draft | Schedule | Publish now
                                                         │
                                          date + time + timezone
                                                         │
                                       row: SCHEDULED, scheduled_at (UTC)
                                                         │
                                        content.sweep_due claims it when due
                                                         │
                                      content.publish_post → PUBLISHING → PUBLISHED
                                                         │
                                       notification + permalink in the UI
```

Navigation: **Dashboard · Campaigns · Leads · Inbox · Content Studio ·
Accounts** (Settings and Advanced remain as they were). Content Studio contains
All posts · Drafts · Scheduled · Published · Calendar · Templates · Queue, plus
the composer at `/content/new` and `/content/{id}`.

## 3. Database

Migration [`0006_content_studio`](../api/alembic/versions/0006_content_studio.py).

### `linkedin_posts`
`id`, `workspace_id`, `created_by_id`, `linkedin_account_id`, `content`,
`visibility`, `status`, `scheduled_at` (UTC), `scheduled_timezone`,
`queue_position`, `published_at`, `linkedin_post_id`, `linkedin_url`,
`publish_key` **UNIQUE**, `publishing_started_at`, `failure_reason`,
`error_code`, `request_id`, `failed_at`, `attempts`,
`submitted_for_approval_at`, `approved_by_id`, `approved_at`, `review_note`,
`analytics`, `analytics_updated_at`, `created_at`, `updated_at`.

Statuses: `draft · pending_approval · approved · scheduled · publishing ·
published · failed · cancelled`.

`scheduled_at` is always UTC. `scheduled_timezone` stores the IANA zone the user
picked, separately, so the UI can render "9:30 AM Asia/Kolkata" a year later even
if their profile timezone has since changed.

### `linkedin_post_media`
`post_id`, `media_asset_id`, `position` (unique per post), `alt_text`,
`linkedin_asset_urn` — the URN cached after a successful upload, so a retry does
not re-send bytes that already landed.

### `media_assets`
`workspace_id`, `uploaded_by_id`, `kind`, `filename`, `content_type`,
`size_bytes`, `storage_key`, `width`, `height`, `metadata`.

### `post_templates`
`workspace_id`, `created_by_id`, `name`, `content`, `media_asset_ids`.

### `post_queues`
One row per workspace: `paused`, `timezone`, `slots` (`[{weekday, time}]`).

### On `linkedin_accounts` (extended, not duplicated)
`publishing_token_ciphertext`, `publishing_refresh_ciphertext`,
`publishing_token_expires_at`, `publishing_scopes`, `publishing_member_urn`,
`publishing_authorized_at`, `publishing_authorized_by_id`, `publishing_error`.

## 4. API

All under `/api/v1/workspaces/{workspace_id}/content`, behind `require_workspace`.

| Method | Path | Purpose |
|---|---|---|
| GET | `/posts` | list; filters `status` (repeatable), `account_id`, `author_id`, `search`, `date_from`, `date_to`, `limit`, `offset`; returns per-status counts |
| POST | `/posts` | create a draft |
| GET | `/posts/{id}` | one post |
| PATCH | `/posts/{id}` | update — **also the autosave endpoint** |
| DELETE | `/posts/{id}` | delete |
| POST | `/posts/{id}/duplicate` | copy into a new draft |
| POST | `/posts/{id}/repurpose` | AI-rewrite into a new draft |
| POST | `/posts/{id}/schedule` | `{scheduled_date, scheduled_time, timezone}` |
| POST | `/posts/{id}/cancel` | take out of the schedule |
| POST | `/posts/{id}/publish` | Publish Now |
| POST | `/posts/{id}/retry` | retry a failed publish |
| POST | `/posts/{id}/submit` · `/approve` · `/request-changes` | approval workflow |
| GET/PUT | `/settings/approval` | per-workspace approval toggle |
| GET | `/calendar` | `start`, `end`, `timezone`; entries carry a pre-computed local date/time |
| GET | `/media/limits` | what the composer may accept |
| POST/DELETE | `/media`, `/media/{id}` | upload / remove |
| GET/POST/PATCH/DELETE | `/templates…` | templates |
| GET/PATCH | `/queue` | queue config |
| POST/DELETE | `/posts/{id}/queue`, `/posts/{id}/queue/move` | queue membership and order |
| POST | `/ai/improve` · `/ai/generate` | suggestions only |

Plus, on the LinkedIn account:

| Method | Path |
|---|---|
| POST | `/workspaces/{ws}/linkedin-accounts/{id}/publishing/authorize` |
| DELETE | `/workspaces/{ws}/linkedin-accounts/{id}/publishing` |
| GET | `/linkedin/oauth/callback` *(public; authenticated by signed state)* |

## 5. Scheduler

- **Beat**: `content-sweep-due` runs `content.sweep_due` every 60 s, alongside the
  existing `dispatcher-tick`.
- The sweep selects `SCHEDULED` posts with `scheduled_at <= now`, using
  `FOR UPDATE SKIP LOCKED` so two beats never claim the same row, and sends
  `content.publish_post` on the **`content.publish`** queue.
- That queue is isolated from `linkedin.action` on purpose: publishing uses the
  official API and shares none of the automation queue's pacing, slot locks or
  quotas, so a backed-up outreach queue cannot delay a scheduled post.
- Publish Now takes the same path: the API sets `scheduled_at = now` and sends the
  task directly. There is exactly one publishing code path.
- The queue feature is a **slot generator**, not a second scheduler: adding a post
  resolves the next free `{weekday, time}` slot in the queue's timezone and writes
  an ordinary `scheduled_at`.

## 6. Publishing worker

See [LINKEDIN_POST_PUBLISHING.md](LINKEDIN_POST_PUBLISHING.md) for the step-by-step.
The guarantee, in brief:

1. **Claim under a row lock.** `SELECT … FOR UPDATE`, verify the status is still
   `SCHEDULED`, then set `PUBLISHING`, increment `attempts`, and write
   `publish_key = sha256(post:attempt)` — a table-wide UNIQUE.
2. **Commit the claim before any network call.** A redelivered task finds the row
   in `PUBLISHING` and does nothing.
3. **Never republish an unresolved post.** If a worker dies mid-flight the row
   stays `PUBLISHING`; after 15 minutes the sweep fails it with an explicit
   "the outcome is unknown — check your profile" message. Re-sending a post that
   may already be live is worse than an error a human can resolve.
4. **Bounded retries.** Transient classes (`429`, `5xx`, storage read failures)
   are rescheduled with 2 / 10 / 30-minute backoff, at most three automatic
   attempts. Everything else fails immediately with a reason. A user-initiated
   retry starts a fresh budget — the system never loops on its own.
5. **Too late is a failure, not a late post.** A post more than six hours past its
   slot is failed rather than published at the wrong time.

## 7. LinkedIn authentication

Two credentials, deliberately separate:

| | Automation (existing) | Publishing (new) |
|---|---|---|
| Credential | `li_at` session cookie | OAuth 2.0 member access token |
| Obtained by | cookie paste or sign-in in a worker | LinkedIn consent screen |
| Stored in | `session_ciphertext` | `publishing_token_ciphertext` |
| Used by | `voyager.py` (private API) | `publishing.py` (documented REST API) |
| Goes through the proxy | yes | no |

An account can be connected for outreach and not authorized for publishing, or
the reverse. The account card reports the two states separately rather than
collapsing them into one "connected", which would be misleading for either.

Full requirements: [LINKEDIN_PUBLISHING_REQUIREMENTS.md](LINKEDIN_PUBLISHING_REQUIREMENTS.md).

## 8. Media handling

- Stored in the S3/MinIO bucket this stack already runs (`S3_*` settings, `boto3`,
  the `minio` compose service). No new provider was introduced.
- Keys are tenant-prefixed: `workspaces/{workspace_id}/media/{uuid}{ext}`.
- The bucket stays private; previews are short-lived presigned URLs (1 hour), so a
  leaked thumbnail link does not become a permanent public URL to unpublished
  creative.
- boto3 is synchronous, so every call is pushed to a worker thread rather than
  blocking the event loop.
- Type, size and combination are validated on upload *and* again when attached.
  Image dimensions are read from the file header, with no imaging dependency.
- The worker downloads the bytes and registers them with LinkedIn at publish
  time, caching the returned URN on `linkedin_post_media`.

## 9. Failure handling

Stored on the post: `failure_reason`, `error_code`, `request_id` (LinkedIn's own
`x-li-uuid`/`x-restli-id`, which is what makes a support conversation with
LinkedIn possible), `failed_at`, `attempts`.

The UI surfaces all of it on the card and in the composer, with **Retry** and,
when the cause is authorization, **Reconnect LinkedIn**. A `post_failed`
notification goes to the workspace feed. Lost authorization additionally clears
the stored grant and raises `publishing_auth_expired`.

## 10. Permissions

This product's roles are `owner`, `admin`, `member`. The Content Studio maps the
four-tier model from the brief onto them rather than adding a fourth role that
campaigns, leads, inbox and billing would all have to learn:

| Brief | Here | Content Studio rights |
|---|---|---|
| OWNER | `owner` | everything |
| ADMIN | `admin` | create, edit, schedule, publish, approve, manage the queue |
| EDITOR | `member` | create and edit **their own** drafts; submit for approval |
| VIEWER | — | no equivalent role exists in this product |

Enforced server-side in `content_service.require_publish()` and
`_require_author_or_admin()`; the client mirrors it so disabled buttons match what
the API would allow. A member attempting to publish gets 403 with an explanation,
not a silent no-op.

### Approval workflow

Off by default — a solo user is not a committee. When a workspace turns it on
(`workspaces.settings.content_approval_required`), the flow is
`draft → pending_approval → approved → scheduled → published`, and scheduling or
publishing an unapproved post returns 409. Admins approve or request changes with
a note that appears back in the author's composer.

## 11. Security

- **Workspace isolation.** Every route depends on `require_workspace`; a
  non-member gets 404, not 403, so workspace existence is not probeable. Posts,
  media and templates are all filtered by the proven workspace id, never by one
  taken from the request body.
- **Account ownership.** `resolve_account()` is the single place a post is bound
  to a LinkedIn account, and it requires the account to belong to the same
  workspace. Publishing through another tenant's account is not reachable.
- **Media ownership.** `get_assets()` refuses assets outside the workspace, so a
  guessed asset id cannot be attached to a post.
- **No credential ever reaches the client.** The API returns a capability verdict;
  the access token, refresh token and client secret are never serialised. Nothing
  LinkedIn-related is placed in `localStorage`.
- **Encryption at rest.** Tokens use the same Fernet envelope as LinkedIn session
  cookies and proxy credentials.
- **CSRF on the OAuth round trip.** The callback is public by necessity; its
  `state` is a signed 15-minute JWT binding workspace, account and user.
- **Validation.** Pydantic on every request; timezones validated against the IANA
  database; media type/size/combination checked server-side regardless of what the
  client allows.
- **Audit trail.** Create, schedule, publish request, publish, failure, approve,
  duplicate, queue and authorization changes all write `audit_events`.

## 12. Future analytics

Post analytics require `r_member_social`, which is not part of the *Share on
LinkedIn* product and is not granted to this app. Rather than hardcode "no", the
capability is checked per request in `publishing.analytics_capability()`:

- `posts.analytics` (JSONB) and `analytics_updated_at` already exist on the row.
- `PostAnalyticsResponse` returns real values when the column is populated and an
  explicit `available: false` with the reason otherwise.
- The UI renders "Analytics unavailable" plus that reason. **There are no
  zero-filled placeholder metrics anywhere** — a row of zeros is indistinguishable
  from a post nobody engaged with, which would misrepresent the product.

To turn it on later: obtain the scope, add a `content.sync_analytics` Beat task
that reads the member's post statistics and writes `posts.analytics`. Nothing
else needs to change.
