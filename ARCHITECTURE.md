# Sentinel — system architecture

Last updated: 2026-05-26

## At a glance

Sentinel pauses execution of risky AI-agent actions until a human approves. The product is a 5-repo system: 2 SDKs, 1 API, 1 dashboard, 1 marketing site, plus a public examples repo.

```
            ┌────────────────────────────────────────────────┐
            │  Agent application (customer-owned)            │
            │  • Python @oversight or TS oversight() wrapper │
            │  • Or LangChain / CrewAI / AutoGen / Anthropic │
            │    / Mastra callback handler                   │
            └──────────────────┬─────────────────────────────┘
                               │ HTTPS, Bearer sk_live_…
                               │ POST /v1/approvals
                               ▼
            ┌────────────────────────────────────────────────┐
            │  Vercel edge (api.pauseapi.app)                │
            │  • TLS termination, geo-distributed            │
            │  • Reverse-proxy to Railway origin             │
            └──────────────────┬─────────────────────────────┘
                               ▼
            ┌────────────────────────────────────────────────┐
            │  sentinel-api (Railway, us-east, FastAPI)      │
            │  ┌──────────────────────────────────────────┐  │
            │  │ Postgres (Railway) — approvals, tenants, │  │
            │  │ audit log (hash-chain), webhooks         │  │
            │  └──────────────────────────────────────────┘  │
            │  ┌──────────────────────────────────────────┐  │
            │  │ Redis (Railway) — rate limit counters,   │  │
            │  │ in-process decision bus                  │  │
            │  └──────────────────────────────────────────┘  │
            │                                                │
            │  notifications.py ──► Resend HTTP (email)      │
            │                  ──► Twilio HTTP (SMS)         │
            │  webhooks.py     ──► customer URL (HMAC POST)  │
            │  billing.py      ──► Stripe HTTP (Checkout)    │
            └─────┬─────────────────────────────────────┬────┘
                  │ LISTEN/NOTIFY                       │
                  │ (sub-100 ms decision propagation)   │
                  │                                     │
       ┌──────────▼──────────┐               ┌──────────▼─────────┐
       │ Agent's blocking    │               │ sentinel-dashboard │
       │ wait_for_decision() │               │ (Vercel, Next.js)  │
       └─────────────────────┘               │ app.pauseapi.app   │
                                             └────────────────────┘
                                                       ▲
                                                       │
                                             ┌─────────┴──────────┐
                                             │ oversight-landing  │
                                             │ (Vercel, Next.js)  │
                                             │ pauseapi.app       │
                                             └────────────────────┘
```

## Repository roles

| Repo | Lang | Role |
|---|---|---|
| **sentinel-sdk** | Python | `@oversight` decorator, `SentinelClient`. Adapters for LangChain, CrewAI, AutoGen, Anthropic Claude. PyPI: `sentinel-oversight`. |
| **sentinel-sdk-js** | TypeScript | `oversight()` wrapper, `SentinelClient`. Adapters for LangChain.js, Mastra. npm: `sentinel-oversight`. |
| **sentinel-api** | Python | FastAPI backend. This repo. Public API at `api.pauseapi.app`. |
| **sentinel-dashboard** | TypeScript | Next.js dashboard at `app.pauseapi.app`. Read/write tenant data using the same API key the SDK uses. |
| **oversight-landing** | TypeScript | Next.js marketing + docs + status at `pauseapi.app`. No tenant data. |
| **sentinel-examples** | Mixed | Runnable code: Python demo, LangChain.js demo, webhook receiver. Public. |

## Approval lifecycle

```
1. Agent calls a function wrapped with @oversight / oversight()
2. SDK POSTs /v1/approvals with function_name + arguments + risk_level + approvers
3. API persists Approval row → status=pending
4. API fires notifications:
   • Resend email with magic-link Approve/Reject buttons
   • Twilio SMS (if any sms:+1… approvers + valid consent contact)
5. SDK long-polls /v1/approvals/{id}/wait
   • API blocks on Postgres LISTEN sentinel_decisions
6. Human clicks Approve/Reject in email → POST /v1/approvals/{id}/token-decision
   • API verifies HMAC-signed token, updates row, NOTIFIES the channel
7. SDK's wait unblocks (sub-100 ms after the click)
8. If approved → SDK returns control to wrapped function which executes
   If rejected → SDK raises ApprovalRejected
   If no decision before timeout → SDK raises ApprovalTimeout
9. API fires webhooks to every customer-registered endpoint:
   • HMAC-SHA256 signed POST, 3-attempt exponential backoff retries
10. Hash-chained audit event appended for every state change
```

## Key invariants

- **Magic-link tokens are scoped to one `action_id`** and expire with the approval's `timeout_seconds`. Cannot approve any other action even if leaked.
- **Audit log is append-only, hash-chained.** `event_hash = sha256(prev_hash + canonical_json(payload))`. Verifiable offline.
- **API keys are stored as hash, never plaintext.** Raw value shown ONCE on signup or via the recover/exchange flow.
- **Webhook secrets are stored plaintext (intentional)** — they're per-tenant, per-endpoint, and only used to sign outbound POSTs. If the DB is compromised, attacker can spoof webhook deliveries to that specific customer; we accept this trade-off vs. the operational pain of derived-key schemes.
- **Per-tenant default approvers** resolve in order: caller's explicit list → `tenant.default_approvers` → global `DEFAULT_APPROVERS` env var → 400 error.
- **Email-verified state is informational, not enforced.** A tenant can use Sentinel before verifying email. We track `email_verified_at` so a future "verified Pro plan only" gate is possible.

## Hosting topology

| Surface | Host | Region | Why |
|---|---|---|---|
| `pauseapi.app` (landing + docs) | Vercel | global edge | static + ISR; low TTFB everywhere |
| `app.pauseapi.app` (dashboard) | Vercel | global edge | Next.js SSR |
| `api.pauseapi.app` (API origin) | Vercel proxy → Railway | us-east | edge TLS in front of single-region origin saves the cross-region round-trip on TLS handshake |
| Postgres | Railway | us-east | colocated with API |
| Redis | Railway | us-east | rate limit counters; tolerable to lose |

## Data flows

### Approval creation (write-heavy path)

```
SDK -POST-> Vercel edge -proxy-> Railway -INSERT-> Postgres
                                      └-async-> Resend HTTP / Twilio HTTP
                                      └-INSERT-> audit_events
```

p50: 53 ms POST → 201
p95: 84 ms

### Decision propagation (latency-critical)

```
Approver clicks Approve  → Browser POST /v1/approvals/.../token-decision
                          → Railway UPDATE Postgres
                          → Postgres NOTIFY sentinel_decisions
                          → Railway LISTEN handler resolves the SDK's wait
                          → SDK returns from wait_for_decision()
```

Click-to-unblock: p99 < 130 ms.

### Webhook fan-out (async, retryable)

```
Decision happens → background task per registered endpoint:
                   attempt 1 → POST customer URL with HMAC sig
                   if 5xx or network error → sleep 1s → attempt 2
                                          → sleep 4s → attempt 3
                                          → record terminal failure
                   if 2xx → record success
                   if 4xx (except 408/429) → record terminal rejection
```

Webhook deliveries never block the decision endpoint return.

## Multi-tenancy model

- One workspace = one `tenants` row
- Per-tenant: API keys, approvals, audit events, webhook endpoints, SMS consent contacts, billing state
- Row-level scoping enforced at the application layer via `tenant: Tenant = Depends(get_current_tenant)` on every authenticated endpoint
- Admin endpoints (`/v1/admin/*`) bypass tenant scoping but require `ADMIN_TOKEN` instead of an API key

## Deploy topology

```
git push origin main
   ├─► sentinel-api    → Railway auto-deploy (build + alembic upgrade + uvicorn)
   ├─► sentinel-dash   → Vercel auto-deploy
   ├─► oversight-land  → Vercel auto-deploy
   └─► sentinel-sdk    → no deploy; on tag v* → GH Actions → PyPI Trusted Publishing
   └─► sentinel-sdk-js → no deploy; on tag v* → GH Actions → npm Trusted Publishing
```

No staging. Single prod environment. (Tier 3 todo: add staging Railway service + branch policy.)

## What we don't have yet (intentional)

- **No SSO** — paste-an-API-key auth. Good enough for design partners.
- **No quota enforcement on the free tier** — column exists, enforcement waits until usage data tells us the right cap.
- **No customer-facing self-serve cancellation portal** — Stripe Customer Portal is 5 min to wire up when a customer asks.
- **No multi-region failover** — single Railway us-east origin. Latency is good enough thanks to the edge proxy.

## Future architectural moves

- Generate JS + TS API clients from `/openapi.json` (eliminate hand-rolled types in dashboard + JS SDK)
- structlog JSON logging with per-request trace id
- Staging Railway environment
- Webhook delivery queue durability (currently in-process `asyncio.create_task`; if the container dies mid-delivery, retries are lost — should move to durable queue, e.g. Postgres-backed)
- ADR series under `docs/adr/` documenting decisions like the 5-repo split, HMAC token format, audit-chain layout
