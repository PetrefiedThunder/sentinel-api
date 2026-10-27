# QA fix pass — 2026-10-02

Local branch: `qa/2026-10-02-fixes`. Starting commit: `7e03777a960d2a6eb931c8b4e296ef9d2419aeee`.
Validation target: `a330382deddb0d34bc21684bd16a3c1207440fa8`. All changes and commits are local. The orchestrator owns review, publishing, and remote CI.

The required work order was BE-002, BE-001, BE-007, BE-003 (Critical: none; High: four), matching SUMMARY.md. Each High finding was fixed or explicitly deferred before optional work. Four small optional findings were then fixed. The original FINDINGS.md is unchanged.

| Finding ID | Severity | Title | Status | Commit SHA | Proving test (file::name) | Notes or reason deferred |
|---|---|---|---|---|---|---|
| BE-002 | High | Onboarding accepts known weak signing configuration | fixed | `330d21e097e6d486292f95d1da9fbf87794fa063` | `tests/test_qa_backend.py::test_onboarding_rejects_weak_signing_configuration`; `tests/test_coverage_onboarding.py::test_be002_onboarding_rejects_weak_signing_and_verification` | Reuse the existing strong-secret guard for onboarding signing and verification. Reject default, empty, and short configuration. No stored credential or configuration changes. Enforcement is at token operation time, not application startup. |
| BE-001 | High | Recovery link remains usable after key rotation | deferred | — | `tests/test_qa_backend.py::test_recovery_token_is_single_use_and_preserves_first_recovered_key` (strict xfail retained) | The requested fix directly changes key rotation, expressly excluded from this pass. Existing nonce storage requires an approval foreign key and cannot hold tenant recovery nonces. Needs separately authorized durable recovery nonce persistence, atomic consumption with key replacement, and concurrent redemption/rollback proof. |
| BE-007 | High | Missing Twilio authentication configuration accepts unsigned consent mutations | fixed | `bb6fc4ab4b65cd301330adfee806babeb003b5f4` | `tests/test_qa_backend.py::test_unsigned_twilio_callback_cannot_change_multiple_tenants`; `tests/test_qa_backend.py::test_be007_unsigned_status_callback_preserves_attempt_and_audit` | Both callbacks return 503 when authentication is unconfigured; configured callbacks always verify signatures. Tests preserve contact state across tenants, delivery status, and audit records, and retain signed-callback controls. |
| BE-003 | High | Webhooks allow private destinations and retain their response text | fixed | `5f1c79216142584d240089253faeaba359b69553`; formatting-only `23f9092b685be17fc3013de1eb6ca339bd503f94` | `tests/test_qa_backend.py::test_webhook_registration_rejects_private_network_targets`; `tests/test_webhook_destinations.py::test_be003_delivery_pins_dns_ip_preserving_host_and_tls` | Require HTTPS without credentials and reject unsafe literal destinations. Before each delivery/retry, validate every DNS result and connect to a checked IP with original Host/SNI and certificate verification. Disable environment proxies and redirects. Block unsafe stored endpoints without fetching private response content. Hostname registration does not resolve DNS; delivery does. |
| BE-004 | Medium | Non-ASCII token signature causes unauthenticated HTTP 500 | fixed | `146b530c9a157a4da1890340a87293574fb7b4bb` | `tests/test_qa_backend.py::test_unicode_token_signature_is_a_client_error` | Reject non-ASCII tokens through existing invalid-token errors before HMAC/encoding; covers Unicode and lone-surrogate payload/signature cases across three routes with state preservation. |
| BE-008 | Medium | Audit CSV preserves formula cells in untrusted error text | fixed | `f2bce2831a8f07b01ebc1e0f2badf9170b72c1e3`; formatting-only `a330382deddb0d34bc21684bd16a3c1207440fa8` | `tests/test_qa_backend.py::test_audit_csv_neutralizes_spreadsheet_formula_cells`; `tests/test_audit_csv_safety.py::test_be008_csv_error_is_safe_without_mutating_audit_evidence` | Escape formula/control prefixes in CSV error cells only. Stored errors, audit hashes, JSON responses, column order, and execution-result JSON are preserved. |
| FE-003 | Medium | CSV download is documented as JSON | fixed | `a83ad353f20bbf59c5517fcb7c7985d8ac8c8a2a` | `tests/test_qa_contract.py::test_openapi_csv_media_type_matches_runtime` | Declare the actual text/csv string response and update only its OpenAPI baseline entry. Runtime CSV and attachment filename are unchanged; complete runtime schema matches the baseline. |
| UX-002 | Low | Documented single-file test command targets a missing file | fixed | `2bce86594fb89fd7a2bd972c0ae70227b50c59fc` | `tests/test_qa_dx.py::test_contributing_single_file_test_example_exists` | Use the existing middleware contract test file. Add --no-cov only to the focused example so the global coverage threshold does not invalidate a successful single-file run; full-suite coverage policy is unchanged. |

## Counts

FixCounts: fixed=3 partial=0 deferred=1

The machine-readable line counts Critical and High findings only.

| Severity | Fixed | Partial | Deferred | Optional, untouched |
|---|---:|---:|---:|---:|
| Critical | 0 | 0 | 0 | 0 |
| High | 3 | 0 | 1 | 0 |
| Medium | 3 | 0 | 0 | 5 |
| Low | 1 | 0 | 0 | 3 |
| Total | 7 | 0 | 1 | 8 |

Untouched optional findings: FE-001, FE-002, UX-001, UX-003, UX-004, BE-005, BE-006, BE-009. They retain their original findings/tests. Broader schema, accessibility, setup/release, and consent work was not expanded into this pass; BE-005 is also in excluded key-rotation code. BE-009 remains the known static-analysis baseline. No item was deferred for time exhaustion.

## Full-suite comparison

| Measurement | Python | Passed | Failed/errors | Xfailed | Skipped | Line coverage |
|---|---|---:|---:|---:|---:|---:|
| Sweep baseline before added QA tests (COVERAGE.md) | 3.13.14 | 208 | 0 | 0 | 26 | 83.57% |
| Sweep after QA additions / fix-pass starting baseline | 3.13.14 | 264 | 0 | 21 | 26 | 83.88% |
| Fix pass before (rerun at starting commit) | 3.13.14 | 264 | 0 | 21 | 26 | 83.88% |
| Fix pass after | 3.13.14 | 362 | 0 | 10 | 26 | 85.63% |
| Fix pass after, CI Python compatibility | 3.11.15 | 362 | 0 | 10 | 26 | Not measured |

Final Python 3.13 output: **362 passed, 26 skipped, 10 xfailed, 1345 warnings in 14.07s**. Python 3.11: **362 passed, 26 skipped, 10 xfailed, 142 warnings in 10.99s**. The 70% coverage gate passed. Statement coverage changed from 1603/1911 to 1698/1983. Added tests and promoted expected failures explain the changed case counts; expected failures still represent unresolved findings.

Final command (from the repository root, through the sanitized command recorder):

```text
.venv/bin/python docs/qa/2026-10-02/pytest_safe.py -q --tb=short --disable-warnings --junitxml=/private/tmp/sentinel-api-fix-pass/after.xml --cov-report=json:/private/tmp/sentinel-api-fix-pass/after-coverage.json --cov-report=term
/private/tmp/sentinel-qa311/bin/python docs/qa/2026-10-02/pytest_safe.py -q --no-cov --tb=short --disable-warnings --junitxml=/private/tmp/sentinel-api-fix-pass/after311.xml
```

No final regression required a revert. Intermediate failures before final verification were intentional negative controls, test-harness corrections, a temporary strict XPASS during parallel marker promotion, and the exact contributor-example coverage check; all are recorded in FIX-SESSION-LOG.md.

## Build, typecheck, lint, and review

| Check | Result |
|---|---|
| Python wheel build | PASS: `uv build --wheel --out-dir /private/tmp/sentinel-api-fix-pass/dist`; built sentinel_api-0.1.0-py3-none-any.whl. New destination module is present; no environment-file entries. No frontend exists in this repository. |
| Whole-repository Ruff lint | PASS: `.venv/bin/ruff check .` |
| Mypy application check | BASELINE FAILURE: exact same five diagnostics before and after, at app/logging_setup.py:53, :64 and app/routers/admin.py:99, :101, :103. No new diagnostic; BE-009 untouched. |
| Ruff formatter check | BASELINE FAILURE: same 37 pre-existing file paths require formatting, verified against an export of starting commit 7e03777. All three new Python files pass formatting. Existing files were not broadly reformatted. |
| Complete runtime OpenAPI vs baseline | PASS: isolated local check; only intended CSV 200-content schema changed. |
| Independent local code review | PASS: per-finding gates plus whole-range review. CodeRabbit was excluded because it transmits code over the network, prohibited here. |
| Secret scan of local fix commits | PASS: Gitleaks scanned nine local commits, approximately 24.83 KB, zero findings, with Git lazy fetch disabled. Individual staged security changes also passed redacted scans. Historical sweep limitations remain outside this range. |
| Git whitespace/scope | PASS: explicit paths only; no migration, deploy, env, credential, or CI secret-scan configuration changes. |
| Dependency upgrades | None required by the recorded findings; runtime manifest and dependencies unchanged. |
| Remote CI/deployment/provider validation | Not run; prohibited in this task and owned by the orchestrator. |

## Remaining risks

- BE-001 recovery replay remains exploitable until a separately authorized rotation/persistence fix is completed. Its strict expected failure remains visible.
- The same 26 PostgreSQL-only tests remain skipped: no disposable database was supplied. SQLite and inert transports do not establish real PostgreSQL locking, concurrent recovery redemption, real provider delivery, live TLS, or network egress behavior.
- Onboarding signing fails closed when invoked with weak configuration; this pass does not validate deployment configuration or add startup validation. Twilio callbacks intentionally return 503 without configured authentication. No secret values were inspected or changed.
- Webhook security now rejects HTTP, private/local/transition addresses, embedded credentials, and unsafe stored endpoints. Environment proxy routing is disabled. Public hostnames are allowed at registration and checked at delivery. Existing users relying on prohibited destinations need an approved separate development/egress design; no bypass was added.
- CSV escaping is supported by parser-level tests; native spreadsheet execution was not performed. The error field's exported representation changes only when needed for formula safety; original evidence remains available through JSON.
- Untouched schema omissions, documentation accessibility/setup/release guidance, default SMS consent validation, mode prefix, and static type errors remain in FINDINGS.md. No production, remote database, billing, outbound messaging, push, PR, or deployment action occurred.

See FIX-SESSION-LOG.md for UTC commands, decisions, dead ends, test outcomes, and commit records.
