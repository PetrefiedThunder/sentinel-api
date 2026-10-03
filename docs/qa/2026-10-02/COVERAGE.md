# Coverage report — 2026-10-02

PR: opened by orchestrator
CI status: pending at time of writing

## Comparable full-suite measurements

Both measurements used CPython 3.13.14, identical resolved dependencies, pytest-cov line coverage of app, and the same safe bootstrap. No product source changed. The baseline explicitly excluded the three new QA files; the after run included them. The 70% configured gate passed in both.

| Measurement | Passed | Skipped | Expected failures | Covered / statements | Line coverage |
|---|---:|---:|---:|---:|---:|
| Before | 208 | 26 | 0 | 1597 / 1911 | 83.57% |
| After | 264 | 26 | 21 | 1603 / 1911 | 83.88% |

Increase: **0.31 percentage points**, six additional statements. New tests add meaningful assertions to code already exercised, so coverage percentage understates the behavioral additions. Lines executed inside strict xfails count as covered; coverage does not mean those defects are fixed.

The full suite also ran on **CPython 3.11.15**, matching the CI major/minor: **264 passed, 26 skipped, 21 xfailed**, without coverage to preserve the comparable 3.13 dataset. Python/dependency/platform differences remain from Ubuntu-hosted CI.

## Added test cases

| File | Passing | Strict xfail | Focus |
|---|---:|---:|---|
| tests/test_qa_backend.py | 31 | 12 | Real authentication/tenant matrix, same-key tenant isolation, recovery and callback security, malformed tokens, safe CSV |
| tests/test_qa_contract.py | 22 | 8 | Baseline routes, response shapes, request boundaries, JSON/cursor errors, CSV encoding/content types |
| tests/test_qa_dx.py | 3 | 1 | README test-mode payloads and nonexistent contributor test command |
| Total | 56 | 21 | 77 added cases; xfails map to 12 findings |

## Per-module line coverage

| Module | Before | After | Statements still missing |
|---|---:|---:|---|
| app/__init__.py | 100.00% | 100.00% | None |
| app/auth.py | 68.97% | 68.97% | 39, 40, 41, 42, 43, 44, 46, 47, 48 |
| app/config.py | 96.88% | 96.88% | 56 |
| app/db.py | 92.00% | 92.00% | 40, 41 |
| app/logging_setup.py | 94.23% | 94.23% | 113, 114, 130 |
| app/main.py | 90.62% | 90.62% | 26, 27, 77 |
| app/models.py | 100.00% | 100.00% | None |
| app/routers/__init__.py | 100.00% | 100.00% | None |
| app/routers/admin.py | 56.25% | 56.25% | 41, 46, 47, 48, 80, 82, 84, 85, 93, 94, 95, 96, 98, 99, 100, 101, 102, 103, 104, 105, 107 |
| app/routers/approvals.py | 79.73% | 79.73% | 35, 75, 81, 118, 119, 120, 123, 141, 142, 143, 144, 146, 147, 149, 150, 151, 152, 153, 154, 155, 156, 162, 163, 173, 174, 175, 196, 200, 243, 273 |
| app/routers/approver_contacts.py | 82.61% | 82.61% | 34, 52, 53, 54 |
| app/routers/audit.py | 68.75% | 68.75% | 49, 55, 56, 57, 58, 59, 82, 85, 108, 110, 111, 112, 114, 116, 121, 122, 123, 124, 125, 126, 128, 151, 154, 156, 190 |
| app/routers/billing.py | 78.69% | 78.69% | 41, 42, 47, 48, 49, 50, 51, 52, 53, 118, 119, 137, 138, 139, 147, 148, 158, 159, 165, 168, 173, 174, 175, 176, 207, 208 |
| app/routers/status_history.py | 72.73% | 72.73% | 43, 61, 62, 63, 64, 65, 66, 67, 69 |
| app/routers/tenants.py | 71.72% | 71.72% | 61, 62, 63, 64, 65, 66, 67, 70, 71, 72, 76, 77, 79, 95, 99, 130, 131, 132, 133, 153, 160, 161, 164, 165, 170, 171, 209, 210 |
| app/routers/twilio_webhooks.py | 83.33% | 83.33% | 25, 40, 48, 49, 56, 67, 79, 80, 87 |
| app/routers/webhooks.py | 80.65% | 82.26% | 90, 91, 116, 117, 118, 119, 120, 121, 139, 146, 151 |
| app/schemas.py | 97.09% | 98.06% | 30, 122 |
| app/services/__init__.py | 100.00% | 100.00% | None |
| app/services/approval_service.py | 56.00% | 68.00% | 17, 18, 19, 20, 50, 52, 61, 62 |
| app/services/approval_tokens.py | 90.38% | 92.31% | 30, 60, 61, 67 |
| app/services/audit_log.py | 95.83% | 95.83% | 26 |
| app/services/contacts.py | 100.00% | 100.00% | None |
| app/services/decision_bus.py | 86.96% | 86.96% | 46, 49, 50, 51, 58, 59, 60, 61, 62 |
| app/services/idempotency.py | 95.24% | 95.24% | 154, 155, 156, 159 |
| app/services/nonce_store.py | 100.00% | 100.00% | None |
| app/services/notification_attempts.py | 72.34% | 72.34% | 84, 85, 86, 87, 92, 93, 94, 95, 96, 97, 98, 99, 100 |
| app/services/notifications.py | 85.19% | 85.19% | 27, 32, 33, 43, 46, 47, 49, 75, 76, 91, 113, 114, 163, 164, 180, 186 |
| app/services/onboarding.py | 91.67% | 91.67% | 67, 68, 75, 112, 113, 115 |
| app/services/pagination.py | 80.49% | 80.49% | 78, 80, 81, 82, 83, 84, 85, 86 |
| app/services/rate_limit.py | 68.09% | 68.09% | 27, 28, 29, 39, 42, 73, 83, 84, 85, 86, 87, 92, 99, 100, 115 |
| app/services/tsa.py | 90.00% | 90.00% | 81, 94, 113, 114, 124, 125, 127, 149 |
| app/services/webhooks.py | 63.33% | 63.33% | 134, 136, 137, 138, 139, 140, 148, 149, 150, 152, 153, 154, 155, 156, 157, 158, 159, 160, 162, 163, 164, 165, 166, 167, 170, 171, 186, 187, 188, 189, 190, 191, 192 |

## Gaps and interpretation

- All 26 existing opt-in PostgreSQL cases skipped because no disposable PostgreSQL URL was provided and existing databases were prohibited. They include real connection races, row locking, cancellation, nonce uniqueness and transactional behavior.
- No real Redis, LISTEN/NOTIFY, read-replica lag, provider delivery, billing, TSA, Sentry, or deployment egress checks. Existing TestClient lifespan attempts were blocked by pytest-socket; their graceful-degradation warnings are retained in the test logs.
- Webhook delivery retry and failure paths, rate-limit outage behavior, streaming/long-poll load, and administrator purge branches remain incompletely covered. No stress, load or production-scale performance claim.
- No property-based engine run was added: selected deterministic malformed-input equivalence classes and boundary tests complement existing race/rollback tests. Hypothesis was installed as optional QA tooling but unused; project dependencies are unchanged.
- Local documentation smoke covered Chromium, Firefox and WebKit. Axe on Chromium covered selected WCAG 2.2 A/AA rules and DOM keyboard/semantic checks, not native screen-reader speech or complete WCAG conformance.
- No product frontend exists in this checkout; UI/component/build/Lighthouse for the separately hosted dashboard are out of scope. Navigation timings on the local docs harness are only a smoke metric.

## Raw evidence

- [Before coverage JSON](artifacts/coverage-before.json) and [before JUnit](artifacts/junit-before.xml).
- [After coverage JSON](artifacts/coverage-after.json) and [after JUnit](artifacts/junit-after.xml).
- [CI-version JUnit](artifacts/junit-python311.xml).
- Full commands and outcomes: [SESSION-LOG.md](SESSION-LOG.md), [BACKEND-LOG.md](BACKEND-LOG.md), [FRONTEND-LOG.md](FRONTEND-LOG.md), [UX-LOG.md](UX-LOG.md).
