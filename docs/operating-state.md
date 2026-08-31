# Sentinel operating state

Session: 2026-08-31. This is an evidence and ownership record, not a new
orchestration service or a claim that agents run after this task ends.

Current cycle: **3 — integration and release gate**, authorized by the user's
request to commit, push, and merge. Cycles 1 and 2 below are preserved as
historical evidence. See [cycle 3](#cycle-3-integration-and-release-gate) for
the current external checks and remaining production gate.

## Mission and boundaries

Advance verified safety of Sentinel's existing human-approval workflow. The
first operating cycle prepares the existing idempotency atomicity draft for
review, without disturbing its owner's checkout or expanding product scope.
The mission follows [the approval lifecycle](../ARCHITECTURE.md#approval-lifecycle).
Customer demand, activation, production state, and documented latency are not
verified by this cycle.

- Original checkout: `sentinel-api`, `main` at `ac01fe1`.
- Locally recorded `origin/main`: `aea61c1`, ten commits ahead; remote freshness
  is not verified and no fetch was performed.
- Candidate: sibling `sentinel-api-qms-verification`, branch
  `codex/quantum-idempotency-verification-20260831-qxr9m09l`, based on `aea61c1`.
- Five existing modified files were copied together: `app/config.py`,
  `app/services/approval_service.py`, `app/services/idempotency.py`,
  `docs/production-checklist.md`, and `tests/test_idempotency_ttl.py`.
  Their committed blobs match at both bases. These edits predate this cycle;
  they are not newly authored implementation work.
- No runtime code expansion, dependencies, schemas, auth, billing, deployment
  configuration, commits, pushes, production credentials, or outreach authorized
  in this cycle. The copied draft intentionally changes legacy stale-claim
  behavior to fail-closed HTTP 409; API shape remains unchanged.

## Executive ownership

| Role | Agent | Decision responsibility | Current disposition |
| --- | --- | --- | --- |
| Chief Executive — Mission | `/root` | Objective, priorities, scarce-resource decisions, final integration | Local cycle complete; candidate accepted for review |
| Chief Operating — Execution | `/root/coo_execution` | Dependencies, work ownership, critical path | Inspection complete; reserve |
| Chief Technical — Architecture | `/root/cto_architecture` | Transaction boundaries and integration invariants | Review complete; reserve |
| Chief Scientific — Truth | `/root/truth_verification` | Baseline evidence, falsification, limits of inference | Baseline complete |
| Chief Risk — Failure | `/root/risk_adversarial` | Adversarial challenge and release objections | Audit-gap replication complete; release objection retained |
| Chief Product — Utility | `/root/product_utility` | User value and scope control | Review complete; reserve |

Roles are decision owners, not permanent departments. The session permits nine
concurrent agents; completed agents receive no further work without a concrete
decision to resolve. No unattended continuation or paid service was configured.

## Competing hypotheses and allocation

Confidence labels are judgments, not calibrated probabilities. Evidence, not
agent agreement, determines acceptance.

| Hypothesis | Initial confidence | Cheapest distinguishing evidence | Allocation decision |
| --- | --- | --- | --- |
| A: the existing atomicity draft prevents duplicate persisted approvals across pre-commit failure and retry | Initially high from code; supported for tested boundaries | Independent PostgreSQL connections; injected failure; original-code negative control | Completed: regression suite and independent replication agree; original-code controls fail as intended |
| B: the current green suite suffices to establish production retry correctness | Low | Inspect fixtures and run real database contention | Rejected: SQLite branch simulation does not establish PostgreSQL behavior |
| C: broad feature work is the next product bottleneck | Low; demand unknown | One observed operator workflow | Defer features; no orchestration platform, adapters, or analytics build |
| D: decisions can persist without their audit evidence | Confirmed in fault-injection experiment | Inject audit failure and inspect a fresh session plus retry | Four diagnostic cases distinguish defect from healthy controls; no runtime edits |

The product executive favors an observed activation session as the next product
experiment. Technical and risk executives prioritize correctness evidence for
the existing draft. The CEO selects local safety verification first because it
is reversible, uses existing tools, and prevents an integration session from
being mistaken for failure-safety evidence.

## Temporary management cell

| Required field | Integration and independent verification |
| --- | --- |
| OBJECTIVE | Produce one isolated candidate with falsifiable PostgreSQL idempotency evidence |
| CURRENT STATE | Complete: candidate verified locally; disposable PostgreSQL stopped |
| OWNED TASKS | Preserve source snapshot; transplant existing draft; add focused tests; run negative control and candidate verification; stop disposable database |
| ACTIVE AGENTS | Work complete; `/root/verification_manager`, its test writer, and independent replicator released to reserve |
| DEPENDENCIES | Existing Python environment, installed PostgreSQL, copied five-file draft, incoming middleware contract tests |
| BLOCKERS | None for local validation; production legacy-claim state unknown |
| RISKS | False confidence from mocks, shared test databases, lock waits, Python 3.14 versus CI 3.11 |
| EVIDENCE | Source manifest and patch; baseline logs; PostgreSQL and full-suite results below; cleanup receipt |
| NEXT DECISION | Narrow candidate accepted for review; next correctness cell should own decision/nonce/audit atomicity and conflicting decisions |
| DEFINITION OF DONE | Candidate/full checks assessed; independent results reconciled; source unchanged; disposable PostgreSQL stopped; reviewable artifacts retained |

The manager owns its disposable database lifecycle and setup. One specialist
writes only the new PostgreSQL tests and their usage document; the replicator
writes only temporary evidence. Root alone writes this operating record.
Everyone may read; no agent may silently expand shared-file ownership. Return
capacity to reserve when evidence is complete. Recreate a cell only when a new
dependency or material uncertainty warrants it.

## Evidence and acceptance

Original working-tree baseline: **171 tests passed**, **87.89% statement
coverage** against a 70% gate, and Ruff lint passed. Formatting check reported
35 pre-existing files. Baseline files remained unchanged. Raw local evidence:
`/tmp/sentinel-qms-truth-0b6u2if0/manifest.json` and adjacent logs. Coverage is not
branch coverage; test fixtures override authentication, so this does not prove
end-to-end authorization. Python is 3.14 locally; CI specifies 3.11.

Final candidate suite: **184 tests passed**, **89.03% statement coverage**,
357 warnings. The eight new PostgreSQL cases passed independently and in the
full suite. Ruff lint and new-test formatting passed; whole-repo formatting
still reports the same 35 pre-existing files. No configured type-checker was
found. Python 3.11 validation was attempted offline, but its dependency cache
lacks `twilio>=9.0`; no download was performed. CI itself remains unverified.

An independent ASGI/PostgreSQL probe observed five blocked contenders, six
identical HTTP 200 responses, and one durable approval/completed claim. The
original archived `aea61c1` failed both intended negative controls: one approval
and an incomplete claim remained after real service creation followed by an
injected error. The candidate left neither row and a fresh retry created one.

The independent probe also terminated a child Python process after approval
creation with `os._exit(73)`, waited for its PostgreSQL backend to close, and
observed zero durable rows followed by a successful retry. A separate injected
error after successful commit retained one approval/claim but lost its local
notification task. This establishes a notification-loss case, not ambiguous
network acknowledgement behavior or delivery to external providers.

Generated OpenAPI is structurally and byte-for-byte identical to the committed
baseline (SHA256 `a45b2148840c3f8ddec8efe8028be401d75c0ceb711b9ad7dbd3c287116d446c`).
The checked-in tests and safe invocation are described in
[PostgreSQL verification](idempotency-verification.md).

An initial independent full-suite run omitted `REDIS_URL`, so application
defaults connected to the existing local Redis and one recovery test returned
429. It may have incremented local test rate-limit counters. This was an
execution-boundary deviation, not an idempotency regression; no counters were
inspected or reset. That run is excluded from acceptance. The replacement run
explicitly disabled Redis and allowed socket connections only to disposable
PostgreSQL: 69 permitted private-socket connections and zero other connection
attempts. The failed run is retained in the evidence record.

Raw verification artifacts are local temporary files under
`/var/folders/jq/nbt0s6qs6njf4yfc0w30wmxh0000gn/T/sentinel-qms-verification-qxr9m09l/`:

- `verifier/verification-results.md`: independent conclusions and artifact hashes.
- `verifier/full-suite-candidate-isolated.log`: accepted guarded full-suite run.
- `verifier/independent_pg.py` and `independent-candidate-final.log`: separate
  concurrency, cancellation, child-exit, and postcommit-error experiments.
- `verifier/copied-baseline-negative.log` and `independent-baseline-negative.log`:
  failures at the intended durable-row assertions, not setup failures.
- `manager-checks.json`, `openapi-comparison.json`, and `source-final.json`:
  independent manager rerun, schema comparison, and preservation evidence.
- `pg-cleanup.json`: no remaining test schemas or clients; server stopped,
  socket and postmaster PID file absent.

Original HEAD, status, and all five modified-file hashes are unchanged. The
candidate's copied five-file patch is byte-identical to the saved source patch.
Only the PostgreSQL test file and two documents were newly authored. Raw temp
evidence may be cleaned by the operating system; the tests and this report
remain in the uncommitted candidate worktree.

Required invariants: one durable approval and completed claim for a successful
keyed create; neither row after failure before commit; consistent replay;
different body conflicts; tenant separation; legacy indeterminate claims never
auto-execute. Notification delivery remains a separate guarantee. An injected
exception alone is not process-death evidence; the separate child-exit
experiment covers one pre-commit termination boundary only. The checked-in
suite does not contain that temporary process-exit probe.

Adversarial diagnostic: both decision routes retained one durable approved row
and zero audit rows after injected audit failure. The token route also retained
its consumed nonce. With the healthy audit helper restored, retries returned
400 or 409 and did not repair the missing audit. Both healthy controls created
one audit row. Four scenarios/eight requests passed their diagnostic assertions;
zero network attempts were observed. Raw probe, report, and results:
`/tmp/sentinel-audit-crash-V5OpKt/`. This is SQLite fault injection, not a
concurrent PostgreSQL decision test or actual process termination.

## Risk register and next decisions

| Risk | Evidence and implication | Owner / disposition |
| --- | --- | --- |
| Opposing terminal decisions | Both routes read `pending` before unconditional update; distinct token nonces do not serialize approve versus reject. [Routes](../app/routers/approvals.py) | Risk + Architecture; pre-existing code mechanism, concurrent outcome not reproduced here; separate next correctness workstream |
| Decision/audit split commit | Decision commits before `append_audit_event`, which commits separately. [Routes](../app/routers/approvals.py), [audit helper](../app/services/audit_log.py) | Risk; reproduced for both routes with controls; withhold broad approval-safety signoff |
| Notification loss after commit | In-process background task can be lost; replay does not redeliver. [Service](../app/services/approval_service.py) | Architecture; reproduced with postcommit error/local stub; no exactly-once delivery claim; outbox outside scope |
| Claim insertion lock wait | PostgreSQL conflict waits inside `flush` before bounded polling. [Idempotency](../app/services/idempotency.py) | Truth; lock-manager observation confirms contention; no production request-latency bound established |
| Legacy committed incomplete claims | Outcome cannot be determined from key row alone | Operations; [rollout reconciliation gate](production-checklist.md#idempotency-atomicity-rollout) remains mandatory |

CEO decision: accept the narrow candidate for review on the tested local
invariants; keep the broader approval-safety release objection. The next
correctness workstream should persist decision, applicable nonce, and audit
together while serializing conflicting decisions, with fault and concurrency
regressions. Do not enlarge the completed idempotency patch to hide those
separate changes.

Before integration/release, confirm remote state and CI and apply the documented
legacy-claim gate under authorized production access. Real authentication,
production migration behavior, provider delivery, server failure, and network
commit-acknowledgement loss remain untested. No commits, pushes, deployments,
outreach, or recurring jobs occurred. The local operating cycle is complete;
the temporary cells have no ongoing assignment.

## Cycle 2: decision/audit correction

Objective: one terminal decision per approval, atomically persisted with its
applicable consumed token nonce and audit event. Original checkout and the five
copied idempotency files remain unchanged. No database schema, external API
shape, auth mechanism, billing, or deployment changes are authorized.

The existing verification manager coordinates two non-overlapping specialists:
one owns the decision routes, audit helper, and unit/fault regressions; the other
owns new PostgreSQL decision tests and verification instructions. Root owns this
record. Architecture reviewed the design; Truth owns a temporary Python 3.11
environment and independent validation. Other executive roles remain in reserve.

Selected design: tenant-scoped `FOR NO KEY UPDATE` with ORM refresh semantics;
token nonce recheck after locking and before terminal-state validation; staged
audit append with `commit=False`; one route-owned commit and explicit rollback.
Existing standalone audit calls keep their default commit behavior. The weaker
row-lock mode still serializes terminal decisions while allowing the foreign-key
`KEY SHARE` locks needed by concurrent standalone audit inserts. Plain
`FOR UPDATE` was rejected because it can invert the row/advisory-lock order.

Preserve same-token replay 409 versus different-token/already-decided 400.
Audit/storage errors must not be mislabeled replay conflicts. Notifications and
webhooks remain postcommit and best effort. Timestamp monotonicity changes,
durable dispatch, and unrelated formatting are deferred.

### Completed management cell

| Required field | Decision correction and independent verification |
| --- | --- |
| OBJECTIVE | One terminal decision, applicable nonce, and audit event persisted together |
| CURRENT STATE | Complete: reviewed candidate passes both local Python full suites; private database stopped |
| OWNED TASKS | Capture immutable baseline; implement bounded correction; prove failures on baseline; verify concurrency, rollback, auth boundaries, and API compatibility; preserve source and clean up |
| ACTIVE AGENTS | Manager and both specialists complete and released to reserve; no ongoing assignment |
| DEPENDENCIES | Preserved cycle-1 candidate, local PostgreSQL 16.14, existing Python 3.14 environment, temporary Python 3.11 environment |
| BLOCKERS | None for local acceptance; Linux CI and production rollout remain separate |
| RISKS | Best-effort dispatch, historical missing audit evidence, old or external decision writers, clock ordering, production failure boundaries |
| EVIDENCE | Immutable snapshot, baseline failures, deadlock negative control, 227-test full-suite logs, API comparisons, hash manifests, and cleanup receipt below |
| NEXT DECISION | Accept the local correction for integration review; run Linux CI and satisfy documented rollout conditions before release |
| DEFINITION OF DONE | Minimal reviewed diff; intended baseline failures; passing current regression/full suites; unchanged API and original tracked bytes; stopped database; explicit limitations — satisfied |

Architecture and Risk reviewed the final runtime diff. Truth independently
validated Python 3.11. The CEO accepts their evidence for the tested invariants;
this is not a production deployment approval or a guarantee of provider delivery.

### Competing designs and decisive evidence

| Hypothesis | Distinguishing experiment | Decision |
| --- | --- | --- |
| Existing decision/audit commits are sufficiently safe | Inject audit failure, inspect fresh durable state, then retry | Rejected: two unit controls and four PostgreSQL controls fail the intended pending-state assertions on the unchanged cycle-2 baseline |
| Plain `FOR UPDATE` is a safe serialization choice | Hold the tenant advisory lock in a standalone audit append while a decision holds the approval row lock | Rejected: temporary stronger-lock mutation produces an actual PostgreSQL `DeadlockDetectedError` |
| `FOR NO KEY UPDATE` plus one commit preserves both serialization and audit compatibility | Observe blocked competing backends, release the winner, then inspect state through separate connections | Supported for tested cases: selected mode passes all 18 PostgreSQL decision cases, including standalone audit contention |
| Green SQLite tests alone establish concurrent decision safety | Repeat opposing API/API, token/token, and API/token requests on PostgreSQL | Rejected as a validation shortcut; real database contention is retained in regression tests |

The stronger-lock experiment was temporary evidence work, not a retained source
change. Runtime and test hashes were frozen before independent full-suite runs.
Final documentation edits did not change those verified files.

### Files changed in this cycle

- [Decision routes](../app/routers/approvals.py): lock and refresh the approval,
  validate its terminal state, stage the audit and any nonce, then commit once.
  Explicit rollback includes cancellation and failed validation after locking.
  Exact nonce verification distinguishes replay from unrelated constraint errors.
- [Audit helper](../app/services/audit_log.py): optional keyword-only `commit`
  retains standalone behavior and permits the route to own the transaction.
- [Atomicity and HTTP tests](../tests/test_decision_atomicity.py): 25 cases.
- [PostgreSQL decision tests](../tests/test_decision_postgres.py): 18 cases.
- [Existing signed-link test](../tests/test_signed_decision_links.py): adapt its
  database and audit fakes to the new transaction ownership; preserve assertions.
- [Portable verification instructions](decision-verification.md) and this record.

There are two changed runtime files, three changed or new test files, and two
documents. No schema, dependency declaration, external API shape, auth mechanism,
billing, or deployment configuration changed. The preceding five-file
idempotency draft remains distinct and unchanged.

### Verification and acceptance

| Environment / check | Result |
| --- | --- |
| Independent Python 3.11.15 full suite | **227 passed**, no skipped/failed/error cases; **84.15% statement coverage**, 70% gate enforced; 38 warnings |
| Independent Python 3.14.5 full suite | **227 passed**, including all PostgreSQL cases; **91.16% statement coverage**, 70% gate enforced; 585 warnings |
| Manager's independent targeted rerun | **51 passed**: 25 atomicity/HTTP, 18 decision PostgreSQL, and 8 existing idempotency PostgreSQL cases |
| Whole-repository Ruff lint | Passed under both installed verifier versions |
| Changed Python file formatting | Four pass; `app/routers/approvals.py` retains only the pre-existing create/SMS-consent block formatting issue |
| Whitespace and API contract | `git diff --check` passed; OpenAPI unchanged |

The coverage percentages use different Python/dependency/coverage environments;
they are not a controlled comparison or evidence of a performance improvement.
These are local macOS runs, not execution of the Linux GitHub CI workflow.
No configured type checker was found. Whole-repository formatting debt was not
expanded or repaired by this correction.

PostgreSQL tests observe actual blocked contenders and verify a single terminal
winner with one matching decision audit event. They cover API/token mixes,
same-token replay, stale ORM state, different approvals sharing one audit chain,
hash and actual database constraint failures, cancellation after audit flush,
successful retry after rollback, and a known successful commit followed by an
application error. Dispatch stubs inspect durable state before recording calls.

The added HTTP tests use the real authentication dependency with synthetic keys,
covering missing, malformed, unknown, revoked, and wrong-tenant credentials;
invalid decisions and absent actions; invalid, expired, and wrong-action tokens;
and authenticated success. Only their database dependency is replaced. These
tests do not establish all production authorization or infrastructure behavior.

OpenAPI matches the committed baseline byte-for-byte under Python 3.14 (SHA256
`a45b2148840c3f8ddec8efe8028be401d75c0ceb711b9ad7dbd3c287116d446c`).
Root independently generated it under the fresh Python 3.11 environment and
confirmed structural equality, with 24 paths in both documents.

All cycle-2 test runs used scrubbed settings, disabled Redis/provider settings,
and a guard allowing only the assigned private PostgreSQL Unix socket. Each
full suite recorded 265 permitted PostgreSQL connections and zero other network
operations. The cycle-1 Redis boundary deviation did not recur. The separate
temporary Python 3.11 environment downloaded only existing declared requirements
from standard PyPI; no repository dependency or deployment files changed.

Raw evidence is under `/tmp/sentinel-decision-cycle2-q1wjjuvw/`:

- `baseline/`, `cycle2-start.json`: immutable starting candidate and source hashes.
- `builder/baseline-audit-loss.log`: two intended unit negative-control failures.
- `verifier/cycle2-baseline-negative-final.log`: four intended PostgreSQL failures.
- `verifier/for-update-deadlock-negative.log`: stronger-lock deadlock evidence.
- `verifier/full-suite-python314-final.log`, `verifier/coverage-final.json`, and
  `verifier/final-receipt.json`: independent 3.14 result and verified hashes.
- `manager/checks.json`, `manager/targeted-command.json`, and
  `manager/openapi-comparison.json`: independent manager checks.
- `cycle2-final.json`: final scope, source preservation, and cell-owned hashes.
- `pg-cleanup.json`: no test schemas or other clients in any of the three private
  test databases; successful shutdown; server, socket, and PID file absent.

Python 3.11 evidence is under `/tmp/sentinel-qms-truth-py311-clkcnodc/`:
`validation-manifest.json`, `pytest-full.log`, `coverage.json`, `junit.xml`,
`versions.json`, and environment provisioning logs. Temporary evidence may be
removed by operating-system cleanup; checked-in test sources and the portable
invocation remain in this uncommitted candidate.

### Preservation, remaining risks, and next step

All 101 originally tracked source files and original HEAD are unchanged. During
this cycle, unrelated untracked research documents appeared in the original
checkout; this cell did not read, modify, remove, or move them. The candidate's
five copied idempotency files, cycle-1 PostgreSQL tests, and cycle-1 verification
document are byte-identical to their starting versions. Only this operating
record intentionally updates the preceding cycle's documentation.

The prior decision/audit-loss and conflicting-terminal-decision objections are
resolved for the tested route paths. Risk review found no material regression
in the final runtime diff. Remaining limitations are explicit:

- Notifications and webhooks are still best effort after commit; the injected
  postcommit failure demonstrates that dispatch can be lost. No outbox or
  exactly-once delivery guarantee was added.
- Already missing historical audit events are not repaired. Audit timestamp
  ties/backward clocks and existing chain-ordering behavior are unchanged.
- Every decision writer must use this locking/state-check path. Drain old
  decision requests and workers before rollout; mixed old/new writers or direct
  external database writes are not covered by the guarantee.
- Real commit-acknowledgement loss, database server failure, decision-process
  termination, and repeated cancellation during rollback were not exercised.
  Cycle 1's creation-process exit probe does not prove decision-process safety.
- Linux CI, production migrations/RLS, live providers, remote branch freshness,
  and production legacy-claim reconciliation remain unverified. Test lock
  timeouts do not establish production latency bounds.

Recommended next step: review and integrate the isolated candidate through
Linux CI, then satisfy the old-worker drain and documented legacy-idempotency
reconciliation gates before a controlled rollout. Production inspection or
release requires its own authorization. No commits, pushes, deployments,
production credentials, outreach, or recurring jobs were used. The local
cycle is complete and its temporary agents have no ongoing assignment.

## Cycle 3: integration and release gate

The verified candidate was committed as `d3bf960` and pushed to
`codex/quantum-idempotency-verification-20260831-qxr9m09l`. Pull request
[#35](https://github.com/PetrefiedThunder/sentinel-api/pull/35) targets `main`.
GitHub's authoritative Linux jobs passed at that revision: Python 3.11 tests,
OpenAPI compatibility, and security. The generated contract remained unchanged.

External review produced two valid bounded findings. Commit `077e80a` preserves
the original database `IntegrityError` if its nonce-classification query or
ordinary rollback cleanup fails, while cancellation remains transparent. It
also removes the unsafe inline-notification fallback: the only production
caller must provide request-scoped `BackgroundTasks`, whose work runs only after
the route transaction succeeds. New negative tests cover lookup, rollback, and
cancellation failures, missing background-task scope, and postcommit dispatch.
The production checklist now makes the old-writer drain a blocking merge gate.

The review request for new per-tenant metrics is deferred. The repository has
no metrics subsystem; adding one would introduce dependency and privacy/cardinality
decisions unrelated to transaction correctness. Existing PostgreSQL contention
tests and the explicit rollout limitation remain the current evidence boundary.
Mass docstring and formatting changes are also outside this correction.

A concurrent task wrote an alternate decision implementation and a 22-file
market-lab package into the original checkout. That implementation differs from
the independently verified candidate, lacks the real PostgreSQL regression set,
and fails existing test and Ruff checks. It is excluded from integration.
Independent product and truth review also exclude the market-lab package: its
economics and queue results are synthetic, it contains no customer adoption or
payment evidence, 141 links are machine-specific, and two probes fail against
the corrected decision code because their snapshot is stale. The files remain
preserved and untracked in the original checkout; this cycle did not delete or
publish them. The incidental untracked `uv.lock` is likewise excluded.

Railway read-only status confirms a single production API deployment at
`aea61c1`, sourced from GitHub `main`; the repository documents automatic
deployment on a main merge and no staging environment. Therefore merge is a
production action. It remains blocked until an authorized operator:

1. pauses ingress to both decision routes and approval creation;
2. drains every old-revision decision writer and verifies no old request remains;
3. runs the documented production-primary query for
   `idempotency_keys.response_status = 0` and reconciles any rows;
4. holds ingress closed through deployment, verifies all live instances run the
   new revision, then reopens traffic.

Current completion boundary: candidate commits and branch push are complete;
Linux CI at `d3bf960` is complete; review fixes are locally committed and require
their fresh remote checks. The frozen post-review Python 3.11 suite passes all
**233 tests**, including the 18 decision and 8 idempotency PostgreSQL cases,
with **84.56% statement coverage** against the 70% gate. Its network audit
records 265 connections to the assigned private PostgreSQL Unix socket and zero
denied operations. All three test databases had zero residual test schemas and
other clients before the disposable PostgreSQL server was stopped; its socket
and PID file are absent. `main` has not been merged or pushed and Railway has
not been deployed by this cycle. The single highest-value remaining action is
the controlled production gate followed by merge and deployment verification.
