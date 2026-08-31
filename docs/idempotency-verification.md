# PostgreSQL idempotency verification

`tests/test_idempotency_postgres.py` exercises the production approvals route
function and `create_approval` service using independent asyncpg connections.
It covers same-key contention and replay, different-body rejection, rollback
releasing a blocked claimant, serialization/precommit/cancellation rollback,
tenant key isolation, and rejection of oversized keys.

The concurrency tests wait until PostgreSQL reports the loser blocked by the
winner (`pg_blocking_pids`) before releasing the winner. They do not rely on
arbitrary sleeps. Test-only timeouts bound database operations and task
coordination. A real conflicting INSERT waits in PostgreSQL before the
application poll loop; these tests do not establish a production latency bound.

Use an explicitly provisioned **disposable local database** whose name starts
with `sentinel_idempotency_test_`. These tests require both
`SENTINEL_IDEMPOTENCY_TEST_DATABASE_URL` and
`SENTINEL_IDEMPOTENCY_TEST_ALLOW_SCHEMA_CREATE=1`. They skip if the dedicated
URL is absent and refuse unsafe destinations or a missing schema opt-in.
They never derive a connection from `DATABASE_URL` or `.env`. Loopback TCP or
a private Unix socket beneath `/tmp/sentinel-qms-pg-*` is accepted.

Each test creates a uniquely named schema containing only the production
Tenant, Approval, and IdempotencyKey tables, then drops that schema. Existing
tables are not reset. Use a database role scoped to the disposable database.
No production migration is applied or modified.

Run from a fresh temporary working directory so application settings do not
load the repository `.env`; use the repository's existing Python environment:

```sh
# Set REPO, PYTHON and the dedicated test DSN explicitly for your checkout.
RUN_DIR=$(mktemp -d)
cd "$RUN_DIR"
export SENTINEL_IDEMPOTENCY_TEST_DATABASE_URL='postgresql+asyncpg://test_user@127.0.0.1:55439/sentinel_idempotency_test_local'
env -i PATH='/usr/bin:/bin' PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$REPO:$REPO/tests" \
  SENTINEL_IDEMPOTENCY_TEST_ALLOW_SCHEMA_CREATE=1 \
  SENTINEL_IDEMPOTENCY_TEST_DATABASE_URL="$SENTINEL_IDEMPOTENCY_TEST_DATABASE_URL" \
  DATABASE_URL='sqlite+aiosqlite:///:memory:' READ_REPLICA_URL='' \
  SENTRY_DSN='' TSA_URL='' REDIS_URL='' RESEND_API_KEY='' \
  TWILIO_ACCOUNT_SID='' TWILIO_AUTH_TOKEN='' STRIPE_SECRET_KEY='' \
  "$PYTHON" -m pytest --no-cov -o cache_dir="$RUN_DIR/pytest-cache" \
  "$REPO/tests/test_idempotency_postgres.py" -q
```

The decisive negative control is
`test_response_serialization_failure_rolls_back_real_approval`: an injected
encoding failure occurs **after production approval creation and background
task scheduling**. A separate connection must observe zero approvals and
zero claims while the failed session is still open; a new session can retry.
Run this exact test against the candidate and an unchanged archived baseline.
The original internal `create_approval` commit leaves a durable approval and
claim, so that baseline must fail the zero-row assertion. Do not interpret
an import, fixture, or database-connection failure as a valid negative control.

Limits: route functions receive test tenants directly; this does not exercise
HTTP authentication, deployment configuration, migrations, or tenant RLS.
Background tasks are queued but never run, so notification delivery, retries,
or exactly-once delivery are not proven. Precommit failure is injected before
COMMIT is sent; ambiguous commit acknowledgements, process termination, and
repeated cancellation during rollback remain untested. Fresh PostgreSQL
schema creation tests model constraints, not production migration history.
