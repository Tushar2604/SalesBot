# How a post gets published

The end-to-end path of one LinkedIn post, from the first keystroke to the status
the user finally sees. Companion to
[LINKEDIN_CONTENT_STUDIO.md](LINKEDIN_CONTENT_STUDIO.md), which covers the module
as a whole.

---

## 1. The user creates a post

`/content/new`. The composer loads the workspace's LinkedIn accounts and asks the
API what media it may accept (`GET /content/media/limits`) rather than carrying
its own copy of LinkedIn's rules.

The **Posting as** selector lists only accounts belonging to this workspace —
they came from `GET /workspaces/{ws}/linkedin-accounts`, which is workspace-scoped
at the dependency level. Accounts without a publishing grant are still listed, but
labelled *needs authorization*, and a banner explains what is missing.

As the user types, the right-hand pane renders the post as it will read on
LinkedIn: the ~210-character "see more" fold, blue hashtags/mentions/URLs, and the
real media in a 1 / 2 / 3 / 2×2 grid. Character and word counts update live; above
3,000 characters the counter turns red and Schedule/Publish are disabled, because
LinkedIn would reject it.

## 2. It becomes a draft

1,200 ms after the user stops typing, the composer saves.

- **First save**: `POST /content/posts` creates the row (`status = DRAFT`,
  `workspace_id`, `created_by_id`, `linkedin_account_id`, content, media) and the
  composer swaps the URL to `/content/{id}`. A refresh mid-sentence reopens the
  same draft.
- **Subsequent saves**: `PATCH /content/posts/{id}`. A snapshot of the last
  persisted payload is kept in a ref, so an unchanged draft never generates a
  request.

The indicator reads *Auto-saving…* then *Saved ✓*. A `beforeunload` guard catches
the case where the tab is closed inside the debounce window.

Media follows its own path: each file is uploaded immediately
(`POST /content/media`), stored under `workspaces/{ws}/media/…` in MinIO/S3, and
the autosave then attaches the returned asset ids in order.

## 3. It is scheduled

`POST /content/posts/{id}/schedule` with `{scheduled_date, scheduled_time,
timezone}` — a **local wall-clock time plus its IANA zone**, never a UTC instant
the browser computed. The user's chosen zone is routinely not the browser's, and
their choice is the one that must decide when the post goes out.

Server-side:

```python
local = datetime.combine(day, time(hour, minute), tzinfo=ZoneInfo(tz_name))
post.scheduled_at = local.astimezone(UTC)   # stored in UTC
post.scheduled_timezone = tz_name           # kept beside it, for display
```

Before accepting, the service checks that the post has text or media, is within
3,000 characters, is in a schedulable state, has been approved if the workspace
requires it, and — critically — that the account's publishing capability is
`ready`. A missing permission returns **409** with the capability code in
`error.details`; the post stays a draft.

**No job is enqueued.** The schedule is the row. That is what makes rescheduling
a plain `UPDATE` with no earlier job left behind to fire a second time, and makes
cancelling a status change rather than a job lookup.

A `post_scheduled` notification is written and the post appears on the calendar,
placed by the local date the server computed for the viewer's chosen zone.

## 4. The background worker executes

`content.sweep_due` runs on Celery Beat every 60 seconds:

```sql
SELECT … FROM linkedin_posts
 WHERE status = 'scheduled' AND scheduled_at <= now()
 ORDER BY scheduled_at LIMIT 100
 FOR UPDATE SKIP LOCKED
```

`SKIP LOCKED` means two beats never claim the same row. Each id is sent as
`content.publish_post` on the **`content.publish`** queue — isolated from
`linkedin.action`, so a backed-up outreach queue cannot delay a post.

The same sweep also resolves abandoned publishes (§7).

### Transaction 1 — the claim

```python
post = SELECT … WHERE id = :id FOR UPDATE
if post.status is not SCHEDULED:      return "skipped"   # redelivery
if post.scheduled_at > now + 30s:     return "skipped"   # not due
if now - post.scheduled_at > 6h:      fail("too_late")   # not published late
if account missing / capability not ready: fail with the reason
post.status = PUBLISHING
post.attempts += 1
post.publish_key = sha256(f"post:{id}:{attempts}")       # UNIQUE table-wide
```

Then **commit**. The claim is durable before anything touches the network. A
second worker arriving now sees `PUBLISHING` and does nothing; if one somehow
raced past the row lock, both would compute the same `publish_key` and one commit
would fail.

### Transaction 2 — the publish

1. Build the publisher: capability re-checked, token decrypted (worker-side only).
2. Upload each attachment — `initializeUpload`, `PUT` the bytes, and for video
   `finalizeUpload` with the returned part ETags. The URN is cached on the media
   row, so a later retry does not re-upload bytes that already landed.
3. `POST /rest/posts` with `author` (`urn:li:person:…` from the grant),
   `commentary`, `visibility`, `distribution`, `lifecycleState: PUBLISHED`, and
   the attachment block — `media` for one item, `multiImage` for several images.
   The claim's `publish_key` also travels as an idempotency hint.
4. Record the outcome.

## 5. How the authorization is used

The token comes from the member's own OAuth consent, not from the automation
session cookie. It is decrypted only inside the worker and used as
`Authorization: Bearer …` with the versioned `LinkedIn-Version` header. No proxy,
no fingerprint, no cookie is involved. See
[LINKEDIN_PUBLISHING_REQUIREMENTS.md](LINKEDIN_PUBLISHING_REQUIREMENTS.md).

## 6. Success

```python
post.status = PUBLISHED
post.published_at = now
post.linkedin_post_id = urn                      # from x-restli-id
post.linkedin_url = f"https://www.linkedin.com/feed/update/{urn}/"
post.failure_reason = post.error_code = post.request_id = ""
post.queue_position = None
```

A `post_published` notification goes to the workspace feed and an audit event is
written. The composer and the card show **✓ Published successfully** with a
**View on LinkedIn** link.

## 7. Failure

| Case | What happens |
|---|---|
| Transient (`429`, `5xx`, storage read failed) | back to `SCHEDULED` with 2 / 10 / 30-minute backoff, at most 3 automatic attempts, then `FAILED` |
| Rejected content (`422`) | `FAILED` immediately with LinkedIn's own message |
| `401` / `403` | `FAILED`; the stored grant is **cleared**; `publishing_auth_expired` notification; the UI offers **Reconnect LinkedIn** |
| Capability already gone at claim time | `FAILED` before any network call |
| More than 6 hours late | `FAILED` with `too_late` — not published at the wrong time |
| Unexpected exception | `FAILED` with `unexpected_error`; the row never stays stuck in `PUBLISHING` |
| Worker killed mid-publish | row stays `PUBLISHING`; after 15 minutes the sweep marks it `FAILED` with **"Publishing was interrupted and its outcome is unknown. Check your LinkedIn profile before retrying — the post may already be live."** |

That last row is the deliberate choice at the heart of this design: when we
cannot tell whether a post went out, we tell the user rather than trying again.
A duplicate post on someone's profile is worse than an error they can resolve.

Every failure stores `failure_reason`, `error_code`, `request_id` (LinkedIn's own
reference) and `failed_at`. **Retry** is user-initiated and starts a fresh attempt
budget — the system never retries indefinitely on its own.

## 8. How the UI reflects the final state

| Status | What the user sees |
|---|---|
| `draft` | *Draft* pill, Auto-saving/Saved, full editing |
| `pending_approval` | *Pending approval* pill; an admin sees **Approve** / **Request changes** |
| `scheduled` | *Scheduled* pill, the local time and zone, **Reschedule** / **Cancel** |
| `publishing` | animated *Publishing…* pill; the list auto-refreshes every 5 s while any post is in flight |
| `published` | green banner, permalink, and either real analytics or an explicit *Analytics unavailable* with the reason |
| `failed` | red panel with the reason, LinkedIn's reference id, **Retry**, and **Reconnect LinkedIn** when that is the cause |
| `cancelled` | *Cancelled* pill; editable again |

Nothing in this chain is mocked. Every button — Save draft, Schedule, Reschedule,
Cancel, Publish now, Retry, Duplicate, Repurpose, Approve, Delete, queue
reordering, media upload and removal — calls a real endpoint that changes a real
row, and the worker's decision is what sets the terminal state.
