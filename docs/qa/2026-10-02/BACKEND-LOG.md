# Backend QA pass log

PR: opened by orchestrator
CI status: pending at time of writing

Scope: FastAPI backend, real authentication dependency, tenant boundaries, recovery and decision token parsers, idempotency, SMS consent and callbacks, webhook egress, and audit exports. Owned additions: `tests/test_qa_backend.py`, this log, and `BACKEND-FINDINGS.md`. No product behavior was changed.

The branch/worktree identity was confirmed at **2026-10-03T01:35:23Z**: `qa/2026-10-02-sweep`, commit `cfe4270`, remote `PetrefiedThunder/sentinel-api`, working directory `/Users/sellers/Projects/qa-sweep-2026-10-02/sentinel-api`. UTC date is October 3 while the requested local sweep date is October 2.

## Methods and rationale

Risk-first order: (1) authentication/recovery and consent authority, (2) cross-tenant access and replay, (3) outbound webhook trust boundaries, (4) audit integrity/export safety, (5) input classes and developer-visible consistency. Impact times likelihood favored these over duplicating the substantial existing decision-atomicity and PostgreSQL race suites.

The test pyramid is predominantly in-process route integration tests with a real auth dependency and in-memory database, supplemented by focused pure signing checks and isolated source-function experiments. No full browser is needed for backend invariants. Boundary/equivalence classes cover foreign, revoked, invalid, absent credentials; valid/invalid/Unicode tokens; private address families; configured/unconfigured callback authentication; explicit/default SMS recipients. Existing unit and contract tests supply timeout/risk bounds and idempotency failure cases. A new property-testing dependency was not warranted after the small malformed-token corpus found a concrete parser failure.

All shell commands use the QA recorder. **The complete per-command UTC start/end time, exact command, exit status, duration and artifact pointer are in [backend-commands.jsonl](backend-commands.jsonl)**, merged into the main [SESSION-LOG.md](SESSION-LOG.md) by the lead. The table below records the charters, test sessions, edits, and dead ends; raw command artifacts retain failures rather than suppressing them.

## Timed exploratory charters

| Charter | UTC start / finish | Timebox | Exploration and outcome |
| --- | --- | --- | --- |
| BE-C1: identity, tenant boundary, recovery and replay | 2026-10-03 01:35:35 / 01:37:51 | 10 minutes, completed early | Read auth/routes/models and existing atomicity/idempotency contracts. Checked timeout hypothesis against README and rejected it as intentional behavior. Built real-key, two-tenant auth matrix and replay isolation test; found reusable recovery token, missing signing guard, and recovery mode-prefix mismatch. Initial focused suite 31 passed / 11 strict xfailed. |
| BE-C2: outbound destinations, callback authenticity and parser/export boundaries | 2026-10-03 01:36:26 / 01:38:57 | 10 minutes, parallel read-only security review | Reviewed webhook registration and delivery, SMS default consent, Twilio verification, and export cells. Fake HTTP/source-function probes confirmed unrestricted destinations and response retention without any actual request. Added Unicode-token, absent-Twilio-config, default-consent and CSV formula regressions. Final focused suite 31 passed / 12 strict xfailed. |

These were bounded local exploratory sessions, not performance/load tests. Security review ran in parallel with implementation, with no overlapping file ownership.

## Session events and outcomes (UTC)

| Time | Event | Outcome / evidence |
| --- | --- | --- |
| 01:35:23 | Checkout identity and backend file inventory | Verified exact branch/remote/worktree; [artifact](artifacts/backend-013523931810-verify-repository-and-inspect-backend-configuration.txt). |
| 01:35:35–01:36:07 | Source and existing-test review | Identified safe in-process test fixtures; rejected timeout false positive; noted settings' automatic dotenv loading and asked lead for safe harness. No environment files were read. Exact reads in command ledger. |
| Approximately 01:35–01:36 | Security worker attempted unsupported wrapper group `backend-security` | Argument validation rejected the command before the inner shell ran. Worker switched to `backend`. This failed wrapper invocation could not append its own normal ledger entry. |
| 01:36:26 | Webhook/consent inspection plus directory instruction search | Source inspection succeeded; final `rg --files` found no directory-level AGENTS files and returned 1. This was a search miss, not a test failure; [artifact](artifacts/backend-013626281103-inspect-webhook-validation-and-existing-boundary-tests.txt). |
| 01:36–01:38 | Read-only security worker source experiments | Confirmed destination acceptance, weak signing guard, absent Twilio guard, mocked response readback and raw CSV formula cell. One attempted read of absent `tests/conftest.py` failed; existing `tests/test_support.py` supplies fixtures. Worker commands and failed-read output are preserved in the shared backend ledger/artifacts. |
| 01:37:29 | Twilio source/tests and safe filename probes | Read callback code and existing signature coverage. Chained existence probes returned 1; no environment-file contents were opened; [artifact](artifacts/backend-013729579558-inspect-twilio-fail-open-and-existing-negative-path-coverage.txt). |
| Before 01:37:49 | Added initial focused QA tests using apply_patch | Runtime-generated synthetic keys, in-memory SQLite, real auth, no application lifespan; all external side effects replaced with no-op test doubles. Known bugs marked strict xfail. |
| 01:37:49–01:37:51 | Initial route suite | **31 passed, 11 xfailed**, exit 0; [artifact](artifacts/backend-013749991299-run-backend-auth-boundary-and-known-defect-regression-suite.txt). |
| 01:38:11–01:38:13 | Negative control with `--runxfail` | **11 failed, 31 passed**, expected exit 1. Confirmed precise 200-vs-rejection, 500-vs-client-error, and missing-signing-guard behaviors; runtime synthetic key redacted; [artifact](artifacts/backend-013811784440-confirm-known-backend-defects-without-expected-failure-masking.txt). |
| Before 01:38:39 | Added harmless arithmetic CSV regression; strengthened state comparisons | BE-008 added. Recovery and Twilio assertions inspect persisted state, not status alone. No spreadsheet formula executed. |
| 01:38:39 | Ruff on added test file | **All checks passed**; [artifact](artifacts/backend-013839758102-lint-the-added-backend-qa-tests.txt). |
| 01:38:55–01:38:57 | Final focused route suite and source-line evidence | **31 passed, 12 xfailed**, exit 0; [artifact](artifacts/backend-013855727535-verify-final-focused-backend-suite-and-expected-failures.txt); [source references](artifacts/backend-013855727548-capture-exact-backend-finding-source-references.txt). |
| Before 01:39:36 | Addressed independent gate feedback | Narrowed route xfails to `AssertionError`; setup failures use `pytest.fail` so they cannot masquerade as expected assertion failures. Weak-signing test specifically expects pytest's missing-exception failure. Prefix check retains only boolean before asserting, avoiding key disclosure. |
| 01:39:36–01:39:38 | Rechecked narrowed xfails and Ruff | **31 passed, 12 xfailed; Ruff passed**; [artifact](artifacts/backend-013936645999-read-backend-utc-ledger-and-inspect-narrowed-xfails.txt). |

The lead owns whole-suite before/after coverage, static scanning, type-checking and dependency audit; see [COVERAGE.md](COVERAGE.md) and main command log for those independent results. Focused checks used `--no-cov` to avoid overwriting shared coverage output.

## Auth/permissions matrix

Five route actions were tested against four caller classes: approval read, approval wait, approval decision, audit append, webhook disable × other tenant, revoked key, invalid key, missing auth. Results: other tenant 404; revoked/invalid 401; missing auth framework 422. Every case retained pending approval, enabled webhook and zero audit mutations. The suite also tests valid owner operations through creation/recovery/export and valid owner/other-tenant idempotency. Admin-role and billing-route tests remain in the existing suite; no claim of exhaustive role coverage is made.

## OWASP API Top 10 review map

This is a code/test checklist using the 2023 category names, not a certification or live penetration test.

| Category | Review/test evidence | Result / remaining gap |
| --- | --- | --- |
| API1 Broken Object Level Authorization | New 20-case auth matrix; audit/webhook/contact ownership review | Tested objects remain isolated. No broad identifier fuzzing or every endpoint combination. |
| API2 Broken Authentication | Recovery replay, weak signing, malformed-token classes, configured/unconfigured Twilio callback tests | BE-001, BE-002, BE-004, BE-007. No deployment secrets inspected. |
| API3 Broken Object Property Level Authorization | Explicit tenant serializers; request schema and decision attribution review | Tenant IDs are derived from auth in exercised mutations. Per-human approver identity/scopes are not a model supplied here; no claim of identity verification beyond API key / signed link. |
| API4 Unrestricted Resource Consumption | Pagination bounds and wait bounds inspected; existing middleware contract tests; token malformed classes | Long polls and unbounded argument payload/body limits not load-tested. Redis/distributed throttling and real provider cost cannot be validated offline. |
| API5 Broken Function Level Authorization | Administrator dependency source review; real-key protected mutation matrix | No concrete admin bypass found. Admin purge child-FK candidate remains unverified, not counted. |
| API6 Unrestricted Access to Sensitive Business Flows | Recovery redemption, decision/idempotency existing suites, SMS consent and callbacks | BE-001, BE-006, BE-007. Human approval workflows use bearer capability links; social/operational abuse not exercised. |
| API7 Server Side Request Forgery | Private-target registration and mocked delivery destination/response proof | BE-003. Real DNS rebinding, network egress and metadata access explicitly not attempted. |
| API8 Security Misconfiguration | Default signing guard comparison; disabled callback behavior; safe harness/network isolation | BE-002 and BE-007 conditional defects. Actual deployment config unverified. |
| API9 Improper Inventory Management | Router inventory plus existing contract/test review; API contract surface assigned to separate frontend/API-consumer pass | No endpoint sunset/versioning production inventory. Static type-check findings tracked by lead. |
| API10 Unsafe Consumption of APIs | Webhook response snippet/retry source review; malformed input and audit CSV paths | BE-003 and BE-008 trust-boundary consequences. Real Twilio/Resend/Stripe/TSA integration, response schemas and delivery durability not validated. |

## Limitations and handoff

- No PostgreSQL service was started or contacted. Existing PostgreSQL concurrency/migration tests are owned by the lead and may skip without disposable local infrastructure. In-memory SQLite cannot establish real row/advisory-lock correctness.
- No provider integration, billing operation, migration command, production URL or real credential was used.
- No added dependency is needed by the backend test module; it uses existing project test dependencies. The lead's QA harness provides socket blocking.
- Findings are in [BACKEND-FINDINGS.md](BACKEND-FINDINGS.md). Counts are eight findings, not twelve failing parameter combinations.
- Focused suite ends green with strict xfails, while all product defects remain present and must be fixed separately.
