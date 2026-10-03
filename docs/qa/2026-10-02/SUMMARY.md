# QA sweep summary — 2026-10-02

PR: opened by orchestrator
CI status: pending at time of writing

The required wording above records workflow ownership. No PR has been created by this agent and no URL is available yet. Changes are uncommitted on qa/2026-10-02-sweep for the orchestrator to review, scan, commit, push and open as one draft PR.

Counts: Critical=0 High=4 Medium=8 Low=4

| Group | Critical | High | Medium | Low | Total |
|---|---:|---:|---:|---:|---:|
| Backend | 0 | 4 | 2 | 3 | 9 |
| Frontend substitute: API consumer contract | 0 | 0 | 3 | 0 | 3 |
| UX substitute: developer experience / generated docs | 0 | 0 | 3 | 1 | 4 |
| Total | 0 | 4 | 8 | 4 | 16 |

## Top five risks and next-fix order

1. **BE-002 — Weak default signing can undermine recovery authentication.** Onboarding accepts the known default signing configuration; fail closed as the decision-token code already does. Deployment configuration was not inspected.
2. **BE-001 — A recovery link can rotate keys repeatedly.** A second redemption succeeds and revokes the first recovered key; consume recovery nonces atomically and test concurrent redemption.
3. **BE-007 — Missing Twilio authentication allows unsigned contact changes.** The unconfigured route accepts a callback that revokes matching contacts across tenants; return disabled-service 503 until signature authentication is configured.
4. **BE-003 — Customer webhooks accept private-network destinations.** Registration accepts loopback/private addresses and delivery passes them directly to HTTP with response-text readback; enforce destination validation and egress restrictions. Real network reachability was not tested.
5. **FE-001 — The schema check cannot protect undocumented response fields.** 28 successful response schemas are unconstrained, including approval contracts; publish accurate models and update the baseline in a coordinated fix.

Then address BE-004 malformed-token 500s, BE-008 spreadsheet-formula handling, FE-002/003 schema constraints/media types, UX-001/003 developer/release instructions, UX-004 documentation accessibility, and the low-severity mode/consent/type-check/test-path issues. Full exact reproductions and suggested fixes are in [FINDINGS.md](FINDINGS.md). No product fixes were applied in this QA sweep.

## What changed

Three new test files add **77 cases: 56 passing and 21 strict expected failures**, mapped to finding IDs. The only other changes are documentation, reports, screenshots and QA-only harnesses under docs/qa/2026-10-02/. Product source, runtime dependency declarations, existing tests, migrations, CI, deployment files and environment files are unchanged.

Each group has its own pass log and UTC command ledger. [PLAN.md](PLAN.md) explains the risk scoring, test pyramid, timed charters and substitutions. [SESSION-LOG.md](SESSION-LOG.md) includes command failures and false starts. [GATE-LOG.md](GATE-LOG.md) contains an independent review, including unmasked bug reproductions and narrowed xfail checks.

## Verification evidence

| Check | Result |
|---|---|
| Existing suite, Python 3.13.14 | 208 passed, 26 skipped; line coverage 83.57% |
| Complete suite after QA additions, Python 3.13.14 | 264 passed, 26 skipped, 21 xfailed; line coverage 83.88% |
| CI-version local compatibility, Python 3.11.15 | 264 passed, 26 skipped, 21 xfailed |
| Whole-repository Ruff | Passed after QA-only harness lint correction |
| Mypy | 5 existing diagnostics; BE-009 |
| Bandit | 0 issues, 0 scanner errors |
| pip-audit public package metadata | 0 known vulnerabilities in 89 auditable resolved distributions; local sentinel-api package skipped |
| Runtime OpenAPI vs committed baseline | Identical: 24 paths, 29 operations; contract omissions recorded separately |
| Browser docs smoke | Chromium 153.0.8010.12, Firefox 155.0, WebKit 26.6: HTTP 200, 29 operations, no uncaught JavaScript errors |
| Keyboard / responsive / states | Enter expansion and visible focus passed; 375px mobile width without page overflow; synthetic empty/error/loading screenshots saved |
| Axe | Four confirmed WCAG-related rule families; UX-004. One rule incomplete; no full WCAG conformance claim |
| Secret review | Added-content scan: 144 text files / 2.29 MB, zero findings; existing synthetic fixture triaged; full history scan blocked by missing partial-clone objects |
| Remote CI | Pending; hosted CI status was not queried and no PR operations were performed |

Coverage increased by 0.31 percentage points, from 1597/1911 to 1603/1911 executable statements. Existing high coverage did not establish recovery-token or response-contract correctness. Expected-failure execution contributes to coverage; no defect is fixed merely because its lines are covered. Details: [COVERAGE.md](COVERAGE.md).

Screenshots: [desktop](artifacts/ux-chromium-desktop.png), [mobile viewport](artifacts/ux-chromium-mobile-viewport.png), [expanded operation](artifacts/ux-chromium-approval-expanded.png), [empty](artifacts/ux-chromium-empty-schema.png), [error](artifacts/ux-chromium-schema-error.png), [loading](artifacts/ux-chromium-loading.png). Compact [browser evidence](artifacts/ux-browser-summary.json) and [full axe output](artifacts/ux-browser-report.json) include versions and selectors.

## What remains untested and why

- **26 PostgreSQL-only tests:** no disposable PostgreSQL target was provided; using existing databases was prohibited. SQLite does not prove PostgreSQL locking, race, replica or notification behavior.
- **Real providers and production:** Twilio, Resend, Stripe, TSA, Sentry, production egress, billing and deployment configuration were outside scope. Provider behavior was stubbed; configuration-dependent findings do not assert deployed exposure.
- **Separate product frontend/SDK:** absent from this repository. No dashboard build/component/E2E/Lighthouse claim; consumer-contract and generated-documentation passes substituted.
- **Native screen readers and performance at scale:** keyboard/DOM/axe and local navigation timing were feasible; VoiceOver/NVDA, exhaustive WCAG conformance, load/stress and real-user performance were not tested.
- **Complete secret history:** scanner scanned zero commits after a partial-clone lazy-fetch/object-store failure; exit zero was not accepted as evidence. No secret-scan ignore list or baseline was edited. Orchestrator review remains required.
- **Hosted CI and draft PR:** explicitly delegated to the orchestrator. Local results do not establish remote check status.

No commits, pushes, merges, deploys or product behavior changes were made. No environment/credential files were read and no production systems were exercised. An attempted read-only Git history scan triggered automatic missing-object retrieval and failed; that dead end is explicitly recorded rather than treated as a completed scan.

Final artifact validation: all local Markdown evidence links resolve; FINDINGS.md has 16 rows with all eight required columns; all five mandatory docs exist. [Added-content secret scan](artifacts/gitleaks-added-content.json) is clean. The orchestrator still owns its independent scan and publishing steps.
