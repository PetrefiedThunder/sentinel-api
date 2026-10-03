# Frontend QA pass — API consumer contract substitute

There is no product frontend in this repository. This pass substitutes the API integration consumer lens: generated clients, machine-readable schemas, HTTP errors, and export semantics. Swagger UI accessibility and screenshots belong to the separate UX pass.

## Charter FE-C1 — 20 minutes

Started 2026-10-03 01:35 UTC. Inspect the generated and committed OpenAPI documents against actual handlers. Exercise boundary/equivalence classes and response shapes for the approval workflow and audit export. Highest risk: downstream approval consumers accept a schema-valid request that runtime rejects, or cannot type/check a response. Follow the test pyramid: focused schema checks and local ASGI integration tests, without provider or database network access.

## Charter FE-C2 — 10 minutes

After FE-C1, probe malformed JSON/query/body errors, empty list/pagination semantics, and export media types. Verify response details can be consumed consistently. Add strict expected-failure regressions for proven contract defects and passing guards for confirmed behavior.

## Safety and isolation

- Checkout verified at `/Users/sellers/Projects/qa-sweep-2026-10-02/sentinel-api`, branch `qa/2026-10-02-sweep`, origin `PetrefiedThunder/sentinel-api`.
- Only this log and `tests/test_qa_contract.py` are owned by this pass. Product code is read only.
- New HTTP tests use `httpx.ASGITransport`, no application lifespan, isolated in-memory SQLite, and notification stubs plus outbound socket guards.
- No environment or credential files are read; no production URLs are contacted.
- Commands and exact outcomes are recorded by `run.py` in `frontend-commands.jsonl`, linked artifacts, and the consolidated session log.

## Session notes

- 2026-10-03 01:35 UTC: scoped instruction/file scan attempted `tests/conftest.py`, which does not exist; located the actual shared harness at `tests/test_support.py`. No pytest fixture discovery file exists in the inspected test inventory.
- 2026-10-03 01:35 UTC: inspected schemas, routes, shared harness, CI contract gate, and existing schema coverage. An inventory search included absent `scripts/`; the remaining read commands completed and the missing path was logged (exit 2).
- 2026-10-03 01:36 UTC: created this charter/log using `apply_patch`; no runtime execution yet while the lead prepares the isolated dependency environment.
- 2026-10-03 01:36 UTC: checked route metadata annotations; `rg` found no `response_model`, `response_class`, or explicit `responses` annotation in the router inventory (expected no-match exit 1). The application settings type enables automatic `.env` reads, so runtime tests waited for the lead's bootstrap that disables this before imports.
- 2026-10-03 01:37 UTC: added `tests/test_qa_contract.py` via `apply_patch`, preserving product behavior. The lead's isolated dependency environment became available; ran the targeted pass through `pytest_safe.py` with no network sockets or `.env` loading. **22 passed, 3 xfailed** in 0.69 seconds. The 25 warnings concern existing SQLAlchemy defaults calling deprecated `datetime.utcnow`.
- 2026-10-03 01:37 UTC: disabled expected-failure markers for the three reproductions only. **3 failed, 22 deselected**, each at the specific contract assertion. This is intentional defect confirmation; the committed tests retain strict expected-failure markers. Added-test Ruff check passed.
- 2026-10-03 01:38 UTC: compared runtime schema with committed baseline: **24 paths, 29 operations, zero added/removed operations, zero differing JSON pointers**. **28 success responses have the unconstrained schema `{}`**. This proves the missing information already exists in the baseline; the sweep did not introduce schema drift.
- 2026-10-03 01:39 UTC: FE-C1 and FE-C2 completed inside their maximum timeboxes. Ordinary malformed payload/query handling, empty pagination, response aliases, and CSV quoting worked for the exercised cases. No frontend assets/build/component suite exist to exercise. Browser accessibility/performance/screenshots are covered by the UX owner's separate pass.
- 2026-10-03 01:39 UTC: independent gate review suggested exposing every known missing schema independently and narrowing xfails. Applied test-only refinements: four parameterized approval responses, three request-constraint cases, `raises=AssertionError` on all xfails, and a non-xfail CSV status precondition. Final targeted run: **22 passed, 8 xfailed** in 0.68 seconds; Ruff passed. With `--runxfail`, **8 failed, 22 deselected**, each at its intended gap. These are still three findings, not eight separate defects.

## Findings handoff

All three findings are **Medium**, group **Frontend (API consumer substitute)**. No product fixes were applied. Run reproduction commands from the repository root through the QA command recorder; `pytest_safe.py` disables environment-file reads and all TCP sockets. Commands below only address local ASGI/in-memory fixtures.

| ID | Title | Exact reproduction | Expected vs actual | Evidence | Suggested fix |
| --- | --- | --- | --- | --- | --- |
| FE-001 | OpenAPI omits the approval response contract | `.venv/bin/python docs/qa/2026-10-02/pytest_safe.py tests/test_qa_contract.py::test_openapi_types_primary_approval_responses --no-cov --runxfail -q` | Expected typed success bodies including `action_id`/`status` and the list-or-page envelope. Actual POST/list/get/wait advertise `{}`, allowing any JSON value and providing no field protection to the schema breaking-change gate. Runtime approval aliases do exist and passed a separate smoke test. | `app/routers/approvals.py:59`, `:98`, `:130`; `tests/test_qa_contract.py::test_openapi_types_primary_approval_responses`; [contract audit](artifacts/frontend-contract-audit.json); [unmasked reproductions](artifacts/frontend-013957506871-confirm-every-documented-contract-gap-independently.txt). Audit quantifies 28 unconstrained success schemas across 29 operations. | Define and attach accurate response models, retaining **both** legacy `id`/`decision` and consumer `action_id`/`status` fields. Type the array-or-page union for list endpoints. Regenerate the baseline in a coordinated product-fix PR; the existing unused `ApprovalResponse` lacks aliases and must not be attached unchanged. |
| FE-002 | Runtime bounds and enum choices are absent from the request schema | `.venv/bin/python docs/qa/2026-10-02/pytest_safe.py tests/test_qa_contract.py::test_openapi_declares_runtime_request_constraints --no-cov --runxfail -q`; inspect `ApprovalCreate` and `TenantSignup` in the audit artifact | Expected timeout minimum 1/maximum 86400, risk enum low/medium/high/critical, and workspace mode live/test in machine-readable schemas. Actual properties are only integer/string; clients can validate invalid inputs against OpenAPI and still receive 422. New invalid risk cases returned the expected runtime 422. | `app/schemas.py:24`, `:42`, `:44`, `:57`, `:64`; `tests/test_qa_contract.py::test_openapi_declares_runtime_request_constraints`; [contract audit](artifacts/frontend-contract-audit.json). Existing timeout behavior is independently pinned by `tests/test_middleware_contract.py::test_timeout_seconds_bounds_are_1_to_86400`. | Publish equivalent constraints using Pydantic `Field(ge=1, le=86400)` and `Literal`/enum types, or explicit JSON-schema metadata if preserving exact validation messages. Preserve current accepted values and coordinated baseline updates. |
| FE-003 | CSV download is documented as JSON | `.venv/bin/python docs/qa/2026-10-02/pytest_safe.py tests/test_qa_contract.py::test_openapi_csv_media_type_matches_runtime --no-cov --runxfail -q` | Expected the successful response to declare `text/csv`; actual runtime returns `text/csv; charset=utf-8` with CSV text while OpenAPI declares only `application/json`. A client generated from this contract can choose a JSON decoder for a CSV body. | `app/routers/audit.py:136`, `:190`; `tests/test_qa_contract.py::test_openapi_csv_media_type_matches_runtime`; [unmasked reproductions](artifacts/frontend-013957506871-confirm-every-documented-contract-gap-independently.txt). | Declare the CSV response class/media type and a string/binary response schema in route metadata. Keep the current runtime CSV contract and attachment filename intact. |

## Coverage and limitations

- Added 30 cases: **22 passing and 8 strict xfails across three findings**. The lead owns full-suite before/after coverage; this pass deliberately used `--no-cov` to avoid concurrent coverage-file collisions.
- Passing checks cover all baseline route/method registrations, creation/get aliases, empty page envelope, four invalid timeout scalar classes, four invalid risk strings, five malformed cursor classes against both list APIs, malformed JSON, and CSV comma/quote/newline/Unicode round-tripping.
- New tests use overridden authentication to isolate the integration contract; they do **not** establish authentication/tenant security. The Backend pass owns that matrix.
- PostgreSQL LISTEN/NOTIFY, provider callbacks, real generated SDK execution, and full streaming memory/performance are untested in this pass. SQLite and ASGI cannot prove those production behaviors.
- The JSON equality audit is a complete baseline/current document comparison, not an execution of the external `oasdiff` binary. It establishes no schema drift under the installed dependency versions; it cannot detect fields absent from both documents.

## Evidence

- [Final passing contract suite and Ruff check](artifacts/frontend-013957506648-verify-gate-refined-parametrized-contracts-and-lint.txt)
- [Final independent failing reproductions for all eight gaps](artifacts/frontend-013957506871-confirm-every-documented-contract-gap-independently.txt)
- [Runtime/baseline comparison output](artifacts/frontend-013819780300-compare-runtime-openapi-contract-to-committed-baseline-without-network.txt)
- [Machine-readable schema audit](artifacts/frontend-contract-audit.json)
- [Every frontend command, UTC start/end, exit status, and artifact](frontend-commands.jsonl)

PR: opened by orchestrator

CI status: pending at time of writing
