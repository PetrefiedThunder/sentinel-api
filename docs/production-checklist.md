# Sentinel API Production Checklist

Use this before enabling text-message approvals for real users.

## Required Secrets

- `JWT_SECRET`: set to a unique random value with at least 32 bytes of entropy. Do not use `change-me`, `dev-only-replace`, or any copied example value.
- `TWILIO_ACCOUNT_SID`: Twilio account SID for outbound approval texts.
- `TWILIO_AUTH_TOKEN`: Twilio auth token. Store it only in the deployment secret manager.
- `TWILIO_FROM_NUMBER`: SMS-capable sender number owned by the Twilio account.
- `RESEND_API_KEY`: optional fallback for `mailto:` approvers.

## Approval Links

- Approval links are signed with `JWT_SECRET`.
- Links are bound to one approval action and one decision.
- Link expiration uses the approval request `timeout_seconds`.
- Links are single-use in practice because `/v1/approvals/{action_id}/token-decision` only accepts pending approvals.

## Preflight Checks

- Confirm `PUBLIC_APP_URL` points to the deployed dashboard URL that serves `/approve/{id}`.
- Confirm CORS allows the deployed dashboard origin in `app/main.py`.
- Send a test approval to an internal phone number and verify approve/reject both record an audit event.
- Rotate `JWT_SECRET` only during a maintenance window; outstanding approval links signed with the old secret will stop working.

## Idempotency Atomicity Rollout

Before deploying the atomic idempotency change, pause approval writes and run
this read-only query against the production primary:

```sql
SELECT tenant_id, idempotency_key, method, path, request_hash, created_at
FROM idempotency_keys
WHERE response_status = 0
ORDER BY created_at;
```

- Zero rows: proceed with the deploy.
- Any row: stop. Its outcome is indeterminate because an older process may have
  committed the approval before storing the response. Do not retry its handler,
  delete the row, or change its status automatically. Preserve a database
  backup and reconcile the request against approval records and deployment logs
  under an incident record before deciding its disposition.
- Do not roll back to code that automatically takes over stale claims while any
  `response_status = 0` row exists; that path can create a duplicate approval.

After deploy and after one real internal approval, run the query again. There
must be no aged in-progress rows. A row younger than the configured
`IDEMPOTENCY_INPROGRESS_TTL_SECONDS` may be an active request; wait past the
threshold and recheck before treating it as an incident.
