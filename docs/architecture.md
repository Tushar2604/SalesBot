# Architecture

## Process boundary

    Browser -> Next.js (web) -> FastAPI (api) -> Postgres / Redis / S3
                                     |
                                     v enqueue intent
                        Celery Beat -> Dispatcher -> Celery workers -> LinkedIn

**The API never talks to LinkedIn.** It authenticates, validates, persists
intent, and enqueues. Workers own every outbound action. That boundary is what
lets the API scale to N stateless replicas while each LinkedIn account keeps
exactly one execution slot.

Campaigns enqueue *intent*, never actions. The dispatcher pulls due work every
60 seconds and evaluates all safety rules against live state at the last
possible moment. A campaign launched at 9am does not pre-schedule its day; it
declares what should happen and the engine decides when.

## Services

| Service | Image | Role |
|---|---|---|
| `api` | `api/` target `dev`/`prod` | FastAPI, stateless, horizontally scalable |
| `worker` | same image | Celery consumer for all queues |
| `beat` | same image | Celery Beat, publishes `scheduler.tick` every 60s |
| `web` | `web/` | Next.js 15 App Router dashboard |
| `postgres` | postgres:16 | system of record |
| `redis` | redis:7 | Celery broker, per-account slot locks, quota buckets, SSE fan-out |
| `minio` | minio | S3-compatible storage for media, CSV uploads, attachments |

The API and worker share one Python package and one image. They differ only by
command, which keeps model and service code from drifting between them.

## Queues

| Queue | Work | Notes |
|---|---|---|
| `linkedin.action` | invites, messages, views, likes, comments, endorsements, media | one in-flight per account, enforced by Redis lock |
| `linkedin.sync` | conversation polling, acceptance checks, invite withdrawal | low priority |
| `email.send` | SMTP/OAuth sends, warmup | per-mailbox rate limited |
| `ai` | Claude generation and classification | free-running |
| `webhooks` | outbound delivery | retry with DLQ |

`task_acks_late` plus `task_reject_on_worker_lost` means a killed worker's task
is redelivered. Duplicate side effects are prevented by the unique idempotency
key on `action_tasks`, never by assuming a task runs exactly once.

## Tenancy

Every tenant-owned row carries `workspace_id`. Access funnels through one
dependency, `require_workspace` in `app/deps.py`, which proves membership and
hands handlers a `WorkspaceContext`. No handler filters by a `workspace_id`
taken from untrusted input.

A non-member receives 404, not 403: whether another tenant's workspace exists is
not something an outsider should be able to probe.

Postgres RLS policies are layered onto the tenant *data* tables as defence in
depth as those tables land. The tenancy tables themselves are exempt because
they are queried before a workspace is known: login, "list my workspaces",
accepting an invite.

## Secrets

`app/core/crypto.py` wraps Fernet envelope encryption. LinkedIn sessions, proxy
credentials, and mailbox credentials are stored as ciphertext and decrypted only
inside a worker. `app/core/logging.py` installs a redaction processor in the
logging pipeline, so secret scrubbing is structural rather than a convention
each developer must remember.

## Scale notes

1,000 users at roughly 100 actions per account per day is about 100k actions per
day: ~1.2/s average, ~6/s at business-hour peak. Each action is one HTTP
round-trip. That is 20-40 concurrent worker slots. Compute is not the
bottleneck, and this is the payoff of the no-browser design.

The real constraints, in order:

1. **Proxies.** The dominant unit cost, linear in customer count. `ProxyManager`
   is provider-agnostic so pools can be swapped or arbitraged.
2. **Postgres write volume** from `action_tasks`, `messages`, `activity_log`.
   Monthly partitioning, a 90-day rollup job, and pre-aggregated
   `analytics_daily` tables so no dashboard scans raw rows.
3. **Redis.** Cheap at this scale. All locks are TTL-guarded so a worker OOM
   cannot deadlock an account forever.
4. **Driver drift.** The operational risk that actually causes incidents.
   Contract tests, `UNKNOWN_SHAPE` alarms, and a canary cohort of internal
   accounts exercising every action type hourly.

## Build order

Phases are listed in the approved plan. Phase 2, the LinkedIn driver spike, is
sequenced before any campaign UI because it is the only phase that can
invalidate the product.
