# QA plan — 2026-10-02

PR: opened by orchestrator
CI status: pending at time of writing

## Identity and limits

Repository: PetrefiedThunder/sentinel-api. Worktree: /Users/sellers/Projects/qa-sweep-2026-10-02/sentinel-api. Branch: qa/2026-10-02-sweep. Starting commit: cfe4270. Initial working tree was clean. Work began 2026-10-03 UTC (2026-10-02 America/Los_Angeles). Changes remain uncommitted for orchestrator review. No product changes planned.

No repository AGENTS.md was found; supplied shared instructions and orchestrator override apply. No git commit/push, PR creation, deploy, real provider calls, billing, credential files or environment files. No CI, migration, deploy, or environment-file edits. Existing migration tests may use disposable SQLite files only. No existing databases will be used.

## Repository map

- Python 3.11+ FastAPI app: app/main.py and app/routers/{approvals,tenants,approver_contacts,audit,billing,admin,webhooks,twilio_webhooks,status_history}.py.
- Persistence: SQLAlchemy async app/models.py, app/db.py; Alembic revisions 001–012. PostgreSQL production semantics differ from SQLite.
- Critical services: approval_tokens, nonce_store, approval_service, idempotency, audit_log, decision_bus, notifications, webhooks, rate_limit.
- Tests: pytest unit/service/ASGI routes, migration round trips, explicitly opt-in PostgreSQL race tests. Coverage gate 70 percent in pyproject.toml.
- Consumer contract: docs/openapi.baseline.json, tests/test_middleware_contract.py; integration consumers are outside this checkout.
- Developer interface: README.md, ARCHITECTURE.md, SECURITY.md, CONTRIBUTING.md, generated FastAPI Swagger/ReDoc pages. No frontend source, npm build, components, mobile app, or frontend unit/E2E suite.
- CI: .github/workflows/ci.yml: Ruff, pytest, oasdiff, advisory scan, gitleaks. Remote state deliberately unqueried.

## Risk ranking

Impact and likelihood are each 1–5; score is their product, used to allocate time rather than claim incident probability.

| Rank | Surface | Impact | Likelihood | Score | Primary evidence |
|---|---|---:|---:|---:|---|
| 1 | Authentication, cross-tenant reads/writes, signed recovery/decision links | 5 | 4 | 20 | Negative auth matrix and replay cases |
| 2 | Approval decisions, atomicity, idempotency/concurrency | 5 | 4 | 20 | Existing race/rollback tests plus missing boundary cases |
| 3 | Audit-chain integrity and externally triggered callbacks | 5 | 3 | 15 | Existing evidence/signature tests; bounded adversarial inputs |
| 4 | Notification/webhook dispatch and untrusted destination URLs | 4 | 3 | 12 | Mocked-provider tests and OWASP API review |
| 5 | Published OpenAPI versus runtime behavior | 4 | 3 | 12 | Baseline/current schema and route contract tests |
| 6 | Setup, discoverability, errors, accessibility of developer docs | 3 | 3 | 9 | Quickstart walkthrough, local docs browser, axe and keyboard |
| 7 | Dependency advisories, lint and types | 3 | 3 | 9 | Fresh dev environment, static tools, public package metadata |

## Three independent passes

### Pass 1 — Backend QA

Owner backend, separate BACKEND-LOG.md and backend-commands.jsonl. Auth/permissions matrix, replay, idempotency/rollback, audit integrity, and an OWASP API Top 10 checklist. Start with existing suite and coverage, then add narrow regression and property-style boundary cases. Property tooling is installed only in the QA virtual environment if useful; no runtime dependency changes. Mock provider integrations; use ASGI or in-memory SQLite and reject network sockets. Written timeboxed exploratory charters record assumptions and outcomes. PostgreSQL concurrency is not claimed proven by SQLite. Approval timeout semantics must follow the documented wait-budget contract.

### Pass 2 — Frontend QA (substitute: consumer/API contract)

Owner frontend, separate FRONTEND-LOG.md and frontend-commands.jsonl. No product frontend, so React/unit/build/mobile-app tests and product Lighthouse are not applicable. Review generated OpenAPI against baseline and HTTP behavior, schema validation boundaries, structured errors, content types, CORS and streaming expectations where relevant. This lens directly protects SDK and dashboard consumers. Add ASGI route and schema tests, recording real bugs as strict expected failures with FE IDs.

### Pass 3 — UX QA (substitute: developer experience and API documentation)

Owner ux, separate UX-LOG.md and ux-commands.jsonl. Walk through README setup, local examples and common failure recovery without executing provider/deployment steps. Apply Nielsen's ten heuristics to the developer journey. Exercise locally served generated Swagger documentation with external assets fulfilled from downloaded public packages; all browser external requests blocked. Use the orchestrator's already-running Playwright browser server via connect only, never browser launch/install. Capture screenshots at desktop/mobile widths, automated axe WCAG AA results and keyboard/semantic observations. Try available browser families; distinguish server/browser limitations. Automated checks are not a full screen-reader or WCAG conformance certification.

## Test strategy and evidence

Test pyramid: broad existing unit/service checks, focused negative-path ASGI integration tests, small documentation UI smoke. Baseline full suite is captured before new QA tests; final identical coverage settings allow before/after comparison. Network-blocking pytest harness disables Pydantic environment-file loading before importing app. Existing explicit PostgreSQL opt-ins remain unset. All executions through run.py create UTC start/end, exact command, exit code and sanitized output artifacts. Bootstrap pre-logger commands are backfilled transparently. Commands for QA-doc creation and formatting are logged too. No secret values in artifacts.

Findings require reproducible evidence with file:line, expected/actual and suggested fixes. Security severity follows demonstrated impact; unverified deployment conditions remain gaps. Added failing regressions use strict xfail and the finding ID. Existing failing checks will be reported unchanged. No fixes to product behavior planned.

## Timeboxes and exclusions

Target 60–90 minutes overall, parallel independent passes. Initial map/environment/baseline about 10 minutes; risk exploration and tests 25–35 minutes; browser/DX 20–30 minutes; reconciliation and independent review 10–15 minutes. Charters record actual elapsed time rather than inventing session duration.

Out of scope: production/service health, paid requests, provider delivery, actual Stripe charges, Twilio/Resend/TSA/Sentry connections, deployment secrets/settings, real PostgreSQL/Redis infrastructure, cross-repo dashboard and SDK behavior, external CodeRabbit review (would send code to a third-party API), and remote GitHub checks/PR operations. Public package installation and package advisory metadata are the only external research network allowed. The orchestrator owns secret scan, commit, push and one draft PR.
