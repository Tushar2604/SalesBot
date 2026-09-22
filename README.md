# Salesrobo Clone

Multi-tenant LinkedIn + email outreach automation SaaS.

The product is a **safe action-execution engine**: it performs outreach actions on behalf of
many LinkedIn accounts at human-like pace, from a stable per-account IP and device identity,
enforcing quotas and circuit breakers server-side.

## Layout

| Path | What |
|---|---|
| `api/` | Python service. FastAPI app (`app.main`) **and** Celery workers (`app.worker`) share one package/image. |
| `web/` | Next.js 15 dashboard (App Router, TS, Tailwind). |
| `infra/` | Compose overrides, DB init, observability config. |
| `docs/` | Architecture notes and runbooks. |

## Quick start

```bash
cp .env.example .env          # then edit secrets
docker compose up --build     # api :8010, web :3000, postgres :5432, redis :6379, minio :9001
docker compose exec api alembic upgrade head
```

- API docs: http://localhost:8010/docs
- Dashboard: http://localhost:3000
- MinIO console: http://localhost:9001

Python is not required on the host — everything runs in containers.

```bash
docker compose exec api pytest            # tests
docker compose exec api ruff check .      # lint
docker compose exec api mypy app          # types
docker compose exec api alembic revision --autogenerate -m "msg"
```

## Architecture

See `docs/architecture.md`. The safety engine (quotas, ramp-up, pacing, per-account
single-slot locking, circuit breaker) is documented in `docs/safety-engine.md` — read it
before touching anything under `app/linkedin/` or `app/scheduler/`.

The LinkedIn Content Studio (composing, scheduling and publishing posts) is documented in
`docs/LINKEDIN_CONTENT_STUDIO.md`, with the publish path stepped through in
`docs/LINKEDIN_POST_PUBLISHING.md`. Publishing uses LinkedIn's **official** Posts API with a
member-granted OAuth token, entirely separate from the automation session — what that
requires is in `docs/LINKEDIN_PUBLISHING_REQUIREMENTS.md`.

## Legal

LinkedIn's User Agreement prohibits automated access. This software acts only through
credentials its users supply for their own accounts. Obtain legal review before commercial
distribution.

## Status

| Phase | State |
|---|---|
| 0 — Scaffold (monorepo, Docker, CI, lint/type/test gates) | **done** |
| 1 — Auth & tenancy (signup, login, refresh rotation, workspaces, roles, invites, audit, kill switch) | **done** |
| 2 — LinkedIn layer (mobile/Voyager driver, proxy manager, frozen device identity, encrypted sessions, 2FA/checkpoint states, response classifier, circuit breaker, ramp-up caps) | **done** |
| 3 — Leads (CSV import with column mapping, workspace-wide dedupe ledger, blocklists) | **done** |
| 4 — Campaigns + dispatcher (sequence builder with conditions, templating/spintax, quota ledger, log-normal pacing, single-slot locking, reply + acceptance detection) | **done** |
| 5 — Inbox UI | next |
| 6 — AI · 7 — Email · 8 — Analytics · 9 — Billing · 10 — Hardening | planned |

Nav routes for unbuilt phases render a stand-in describing what will live there,
so the dashboard is honest rather than showing dead links.

Verified: 150 tests green, `mypy --strict` clean, `ruff` clean, no migration drift.
The load-bearing test runs two accounts through **30 simulated days** and asserts
the daily cap, the trailing 7-day invite ceiling, the ramp curve, and that no
account ever has two actions in flight.

Live end-to-end: CSV import with messy rows → campaign with a gated follow-up →
enroll → launch → dispatcher materialises one task per lead at irregular times →
executor takes the account's slot, warms the session, and on LinkedIn's 403
opens the circuit and cancels the whole backlog without attempting a single
invite.
# SalesBot
