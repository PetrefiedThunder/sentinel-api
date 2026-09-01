# Decision and audit transaction verification

`tests/test_decision_postgres.py` exercises both production decision route
functions and the real audit helper against separate PostgreSQL connections.
It extends the [idempotency test fixture](idempotency-verification.md), adding
AuditEvent and ConsumedDecisionNonce tables only inside each test's unique
schema. The existing guarded database-name/local-host checks and explicit
schema opt-in still apply. No existing tables are reset.

The 18 cases cover:

- Opposing API, signed-token, and mixed decisions; identical-token replay.
  PostgreSQL must report a distinct losing backend blocked by the winner
  before the test releases it. One terminal decision and matching audit
  persist; only a token winner consumes a nonce. Same-token replay remains
  409, while other decisions against a terminal approval return 400.
- Cached pending ORM objects, cross-tenant rejection, separate actions
  contending on one tenant's audit chain, and verification of that chain.
- Standalone audit append holding the tenant advisory lock while a decision
  holds its approval lock. `FOR NO KEY UPDATE` permits the audit foreign-key
  check; plain `FOR UPDATE` creates a lock cycle. A temporary negative control
  that forces the stronger lock must fail with PostgreSQL deadlock detection.
- Audit hash errors, real audit NOT NULL violations, and cancellation after
  audit flush. An independent connection must see pending/no audit/no nonce;
  a fresh request must be able to retry. Audit constraint failures must not
  be misreported as a consumed-token conflict.
- An injected application error after a known successful commit. The complete
  decision/audit/applicable nonce remain durable, and retry cannot append a
  second decision event. This does not simulate loss of a network commit ACK.

Notification and webhook functions are replaced by local recording stubs.
They independently check durable state before recording invocation. Counts
prove only those local calls, not provider delivery or durable dispatch.
The postcommit error cases deliberately demonstrate that dispatch can be lost.

To rerun independently, provision a disposable local PostgreSQL database and
role, then set absolute checkout/interpreter paths and its dedicated DSN. Run
from a fresh temporary directory so application settings cannot load the
checkout's `.env`. This command clears inherited settings, disables Redis,
blanks provider keys, and keeps generated files temporary:

```sh
REPO=/absolute/path/to/sentinel-api
PYTHON=/absolute/path/to/existing/venv/bin/python
TEST_DSN='postgresql+asyncpg://test_user@127.0.0.1:55440/sentinel_idempotency_test_local'
RUN_DIR=$(mktemp -d)
cd "$RUN_DIR"
env -i PATH=/usr/bin:/bin PYTHONDONTWRITEBYTECODE=1 \
  PYTHONPATH="$REPO:$REPO/tests" \
  DATABASE_URL='sqlite+aiosqlite:///:memory:' READ_REPLICA_URL='' \
  REDIS_URL='disabled://' JWT_SECRET='local-decision-verification-only-key' \
  SENTRY_DSN='' TSA_URL='' RESEND_API_KEY='' \
  TWILIO_ACCOUNT_SID='' TWILIO_AUTH_TOKEN='' TWILIO_FROM_NUMBER='' \
  TWILIO_MESSAGING_SERVICE_SID='' STRIPE_SECRET_KEY='' \
  STRIPE_WEBHOOK_SECRET='' ADMIN_TOKEN='' \
  SENTINEL_IDEMPOTENCY_TEST_DATABASE_URL="$TEST_DSN" \
  SENTINEL_IDEMPOTENCY_TEST_ALLOW_SCHEMA_CREATE=1 \
  "$PYTHON" -m pytest -c "$REPO/pyproject.toml" --no-cov \
  -o "cache_dir=$RUN_DIR/pytest-cache" --basetemp="$RUN_DIR/pytest-work" \
  "$REPO/tests/test_decision_postgres.py" -q
```

The recorded local verification additionally used a temporary network guard
allowing only its private PostgreSQL Unix socket. That session-specific runner
is evidence tooling, not a dependency of the checked-in tests.

Negative controls use the unchanged **Cycle 2 starting snapshot**, which
already contains the preceding idempotency draft. Copy only the new decision
test file into that snapshot. All API/token fault variants of
`test_audit_failure_rolls_back_decision_nonce_and_allows_retry` must fail at
the durable pending-state assertion on the snapshot and pass on the candidate.
Import/setup/connection failures are not valid negative controls.

The tests call route functions with seeded tenants, so real HTTP authentication,
production migrations/RLS, provider delivery, PostgreSQL server failure, and
repeated cancellation during rollback remain untested. Test SQL timeouts do
not establish production latency bounds. Existing audit ordering and hash
semantics are unchanged; backward clocks and timestamp ties remain separate
risks. Python-version and full-suite results belong in the operating record.

Before rollout, drain old decision requests/workers: **all decision writers
must use the locking and state-check path**. An old in-flight request can read
pending before rollout and overwrite a newer decision after its lock releases.
No mixed-version safety claim is made. The separate legacy-idempotency
reconciliation prerequisite still applies. These are release conditions, not
authorization to inspect production or change deployment configuration.
