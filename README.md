# Sentinel API

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![CI](https://github.com/PetrefiedThunder/sentinel-api/actions/workflows/ci.yml/badge.svg)](https://github.com/PetrefiedThunder/sentinel-api/actions/workflows/ci.yml)

**Backend for [Sentinel](https://pauseapi.app)** — a cooperative human-review
workflow for applications that need to pause a proposed action, collect an
approve/reject decision, and resume their own execution.

Sentinel uses FastAPI, PostgreSQL, and Redis. The customer-owned application
remains responsible for deciding whether and how to execute an approved action.

## Current release status

> [!IMPORTANT]
> The atomic idempotency and decision/audit corrections are verified in
> [PR #35](https://github.com/PetrefiedThunder/sentinel-api/pull/35), but as of
> 2026-08-31 they are **not merged into `main` or deployed**. The PR is approved
> and its required checks pass. Because `main` auto-deploys the sole production
> API environment, release still requires the ingress pause, old-writer drain,
> and legacy idempotency-row check in the
> [production checklist](docs/production-checklist.md).

## What it does

- Creates tenant-scoped approval records and signed, expiring decision links
- Attempts configured email and consent-gated SMS review notifications
- Supports direct and signed-link decisions, status reads, and long-poll waiting
- Sends HMAC-SHA256-signed decision webhooks with bounded, best-effort retries
- Stores approval state and maintains tenant-scoped hash-linked audit events with verification and CSV export
- Provides tenant onboarding, approver-contact management, optional billing scaffolding, and operator endpoints
- Supports test workspaces that suppress real email and SMS delivery

## Trust and responsibility boundary

Sentinel records approval workflow state. It does not execute or mediate the
protected action. Keep the tenant API key in a trusted customer service because
it grants tenant-level request and direct-decision authority. The customer
executor must bind the reviewed arguments to the action it performs and refuse
execution without the expected terminal decision. Giving the tenant key to an
untrusted agent does not create independent human authorization.

A signed approval link proves that a valid bearer token was used. It does not
identify the person who used it. The audit verifier checks consistency among
stored hash links; without an independently retained checkpoint, it does not
prove that the complete history is immutable, identify the reviewer, bind the
exact reviewed arguments, or prove external execution. The audit log is
operational evidence, not a compliance certification.

Email, SMS, PostgreSQL `LISTEN/NOTIFY`, and webhooks depend on configured
providers and deployment health. Webhook delivery is in-process and best effort. Consumers
should verify signatures, handle duplicates, and reconcile final state through
the API. This repository does not establish a production latency or delivery
SLA.

## Architecture

See [ARCHITECTURE.md](ARCHITECTURE.md) for the five-repository system map and
[the ADR index](docs/adr/README.md) for recorded design decisions.

## Run locally

Prerequisites: Python 3.11 or newer, PostgreSQL, and
[`uv`](https://docs.astral.sh/uv/). This repository does not include a Docker
Compose stack, so start PostgreSQL using your preferred local method. Redis is
recommended for shared rate limiting; the service fails open when Redis is
unavailable.

```bash
git clone https://github.com/PetrefiedThunder/sentinel-api
cd sentinel-api

uv venv
source .venv/bin/activate
uv pip install -e ".[dev]"

cp .env.example .env
createdb sentinel
export DATABASE_URL="postgresql+asyncpg://localhost/sentinel"
export REDIS_URL="redis://localhost:6379/0"
export JWT_SECRET="$(openssl rand -hex 32)"

alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

Check the process and open the local API documentation:

```bash
curl http://127.0.0.1:8000/health
open http://127.0.0.1:8000/docs
```

Use `xdg-open` instead of `open` on most Linux desktops.

## Create a local test approval

A test workspace returns an `sk_test_...` key and suppresses real email and SMS
delivery. Signup requires a work-domain email; `example.com` is suitable for
local development.

```bash
curl -sS http://127.0.0.1:8000/v1/tenants/signup \
  -H 'Content-Type: application/json' \
  -d '{"name":"Local Demo","email":"developer@example.com","mode":"test"}'
```

Copy the returned key, then create an approval. Reuse the same
`Idempotency-Key` only when retrying the exact same request.

```bash
export SENTINEL_API_KEY='sk_test_...'

curl -sS http://127.0.0.1:8000/v1/approvals \
  -H "Authorization: Bearer $SENTINEL_API_KEY" \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: readme-demo-001' \
  -d '{
    "function_name":"publish_draft",
    "arguments":{"draft_id":"demo-1"},
    "risk_level":"low",
    "approvers":["reviewer@example.com"],
    "timeout_seconds":300
  }'
```

Copy the returned `action_id` to exercise the direct decision path:

```bash
export ACTION_ID='act_...'

curl -sS "http://127.0.0.1:8000/v1/approvals/$ACTION_ID/decision" \
  -H "Authorization: Bearer $SENTINEL_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"decision":"approved","decided_by":"local-reviewer"}'
```

## Configuration

Settings are read from environment variables and an optional `.env` file.
Provider-backed features remain disabled or become no-ops when their credentials
are absent, as noted below.

| Variable | Requirement | Purpose |
|---|---|---|
| `DATABASE_URL` | required | PostgreSQL connection URL; plain `postgresql://` values are normalized for asyncpg |
| `REDIS_URL` | recommended in production | Redis URL for shared request-rate counters; limiting fails open when unavailable |
| `JWT_SECRET` | required | Strong random secret, at least 32 bytes, for approval and onboarding links |
| `READ_REPLICA_URL` | optional | Replica DSN for code paths that use read sessions |
| `PUBLIC_APP_URL` | required for approval links | Dashboard origin that serves `/approve/{id}` |
| `PUBLIC_API_URL` | required for provider callbacks | Public API origin used in Twilio status callbacks |
| `DEFAULT_APPROVERS` | optional | Comma-separated fallback email or `sms:+1...` approvers |
| `IDEMPOTENCY_INPROGRESS_TTL_SECONDS` | optional | Legacy/in-progress claim threshold; default `30` seconds |
| `RESEND_API_KEY` | required for email | Resend credential; email is skipped when empty |
| `EMAIL_FROM`, `EMAIL_REPLY_TO` | optional | Outbound email identities |
| `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN` | required for SMS | Twilio credentials |
| `TWILIO_FROM_NUMBER` | SMS option | Sender number when a messaging service is not used |
| `TWILIO_MESSAGING_SERVICE_SID` | SMS option | Alternative to `TWILIO_FROM_NUMBER` |
| `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, `STRIPE_PRICE_PRO` | required for billing | Checkout returns `503` when Stripe is disabled |
| `STRIPE_SUCCESS_URL`, `STRIPE_CANCEL_URL` | optional | Checkout redirect URLs |
| `ADMIN_TOKEN` | required for admin routes | Separate operator credential; never use a tenant key |
| `TSA_URL` | optional | RFC 3161 timestamp authority; timestamping is disabled when empty |
| `SENTRY_DSN`, `SENTRY_ENVIRONMENT`, `SENTRY_TRACES_SAMPLE_RATE` | optional | Error and trace reporting |

Never use the checked-in `JWT_SECRET` default in a deployed environment. Keep
tenant keys, provider credentials, webhook secrets, and `ADMIN_TOKEN` in the
deployment secret manager.

## Public API

Interactive documentation is available at `/docs` and the OpenAPI document at
`/openapi.json`. The deployed document is normally available at
<https://api.pauseapi.app/openapi.json>.

Tenant-authenticated routes use `Authorization: Bearer sk_live_...` or a test
workspace's `sk_test_...` key.

| Route group | Purpose |
|---|---|
| `/v1/tenants` | Signup, verification, key recovery, and default approvers |
| `/v1/approvals` | Create, list, read, decide, and long-poll approvals |
| `/v1/approver-contacts` | SMS contact consent lifecycle |
| `/v1/audit-events` | Append, list, and verify stored audit chains |
| `/v1/audit-events.csv` | CSV audit-event export |
| `/v1/webhooks` | Endpoint management and delivery history |
| `/v1/status` | Public service-status history |
| `/v1/billing` | Stripe Checkout, subscription state, and Stripe webhook |
| `/v1/admin` | Operator-only routes gated by `ADMIN_TOKEN` and hidden from OpenAPI |
| `/webhooks/twilio` | Twilio delivery-status and inbound-message callbacks |
| `/health` | Process and decision-listener health |

### Downstream consumer contract

[`agent-middleware-api`](https://github.com/PetrefiedThunder/agent-middleware-api)
depends on idempotency deduplication, approvals having no server-side expiry,
the `timeout_seconds` bounds, and `/wait` response semantics. Those behaviors
are pinned by `tests/test_middleware_contract.py`. CI also compares the OpenAPI
schema with `docs/openapi.baseline.json`; an intentional breaking change must
update the baseline in the same PR and be coordinated with the consumer.

## Tests and checks

```bash
ruff check .
pytest -q
```

Coverage is configured in `pyproject.toml`, and the suite fails below the
current `fail_under` gate. Generate a browsable report with:

```bash
pytest -q --cov-report=html
open htmlcov/index.html
```

Run the migration round-trip test, which provisions a disposable database:

```bash
pytest -q tests/test_migrations_roundtrip.py
```

## Migration policy

- Use a sequential numeric prefix (`001`, `002`, …) and descriptive suffix.
- Keep `revision = "<n>"` and `down_revision = "<n-1>"` consistent with that sequence.
- The container runs `alembic upgrade head` before starting Uvicorn.
- Never test downgrades against production or a database containing data you need.

## Deployment

`main` auto-deploys the sole Railway API environment; there is currently no
staging environment. Treat every merge to `main` as a production release.
The container applies migrations before starting Uvicorn.

Before release, follow the [production checklist](docs/production-checklist.md),
including its decision-writer drain and legacy idempotency reconciliation gates.
The [incident-response runbook](docs/runbooks/incident-response.md) describes
triage and rollback responsibilities.

## Security

See [SECURITY.md](SECURITY.md) for the private vulnerability-reporting process.
Do not file public issues for security vulnerabilities.

## License

MIT — © RegEngine, Inc.
