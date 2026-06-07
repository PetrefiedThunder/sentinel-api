# Sentinel API

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Status](https://img.shields.io/badge/status-public%20beta-blue.svg)](https://pauseapi.app/status)
[![Deploy](https://img.shields.io/badge/host-Railway-blueviolet.svg)](https://railway.app)

**Backend for [Sentinel](https://pauseapi.app)** — human-in-the-loop approval infrastructure for AI agents.

FastAPI + Postgres + Redis. Hosted at `https://api.pauseapi.app` (edge-terminated via Vercel proxy → Railway origin in `us-east`).

## What it does

- Issues per-tenant API keys, magic-link approve/reject tokens, webhook secrets, and admin tokens
- Stores every approval + decision + audit event in Postgres with a hash-chained tamper-evident log
- Fires email via Resend (`approvals@pauseapi.app`) and SMS via Twilio A2P 10DLC
- Pushes decision events to customer-registered webhook URLs (HMAC-SHA256 signed, 3-attempt exponential backoff)
- Long-polls decisions via Postgres LISTEN/NOTIFY — sub-100 ms propagation
- Handles Stripe Checkout + subscription lifecycle for billing

## Architecture

See [`ARCHITECTURE.md`](../ARCHITECTURE.md) at the workspace root for the 5-repo system map.

## Run locally

```bash
git clone https://github.com/PetrefiedThunder/sentinel-api
cd sentinel-api

# Python env
uv venv && source .venv/bin/activate
uv sync

# Postgres + Redis (docker-compose or local install)
createdb sentinel
export DATABASE_URL="postgresql+asyncpg://localhost/sentinel"
export REDIS_URL="redis://localhost:6379/0"
export JWT_SECRET="$(openssl rand -hex 32)"

# Apply migrations
alembic upgrade head

# Boot
uvicorn app.main:app --reload --port 8000
```

## Environment

| Var | Required | Description |
|---|---|---|
| `DATABASE_URL` | yes | Postgres with `+asyncpg` driver |
| `REDIS_URL` | yes | Redis (rate limiting + decision bus) |
| `JWT_SECRET` | yes | 32-byte random — signs approval magic links + verify/recover tokens |
| `RESEND_API_KEY` | for email | Resend API key for approval emails |
| `EMAIL_FROM` | for email | `Sentinel Approvals <approvals@pauseapi.app>` |
| `TWILIO_ACCOUNT_SID` | for SMS | Twilio creds |
| `TWILIO_AUTH_TOKEN` | for SMS | |
| `TWILIO_MESSAGING_SERVICE_SID` | for SMS | |
| `STRIPE_SECRET_KEY` | for billing | Inert if empty — billing endpoints return 503 |
| `STRIPE_WEBHOOK_SECRET` | for billing | |
| `STRIPE_PRICE_PRO` | for billing | Stripe Price ID of the Pro plan |
| `ADMIN_TOKEN` | for admin endpoints | Operator-only |
| `SENTRY_DSN` | optional | Error monitoring |
| `DEFAULT_APPROVERS` | optional | Comma-separated fallback approver list |

## Migration policy

- Sequential numeric prefix (`001`, `002`, …) + descriptive suffix
- `revision = "<n>"` and `down_revision = "<n-1>"` strings must match exactly — see `005_webhooks.py` for the pattern
- Migrations run on container start (`Dockerfile` CMD chains `alembic upgrade head` before uvicorn)
- Test before pushing: `alembic downgrade -1 && alembic upgrade head` should round-trip cleanly

## Public API

OpenAPI lives at <https://api.pauseapi.app/openapi.json> — used to generate clients in `sentinel-sdk-js` and `sentinel-dashboard`.

Endpoint groups:
- `/v1/tenants` — signup, verify, recover, default-approver config
- `/v1/approvals` — create, list, get, decide, long-poll wait
- `/v1/approver-contacts` — SMS contact lifecycle (TCPA consent)
- `/v1/audit-events` — read-only hash-chained log
- `/v1/webhooks` — endpoint CRUD + delivery history
- `/v1/billing` — Stripe Checkout + webhook
- `/v1/admin` — operator-only, gated by `ADMIN_TOKEN`, hidden from OpenAPI schema

## Tests

```bash
pytest -q
```

9 unit/integration files. End-to-end smoke against the live API uses the `realworld_test.py` script in [`sentinel-examples`](https://github.com/PetrefiedThunder/sentinel-examples).

## Deploy

GitHub `main` auto-deploys to Railway. No manual step. Migrations run before the new container goes hot.

## Security

See [`SECURITY.md`](SECURITY.md) for vuln-reporting policy. Do not file public issues for vulnerabilities.

## License

MIT — © RegEngine, Inc.
