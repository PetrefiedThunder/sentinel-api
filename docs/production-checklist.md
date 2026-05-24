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

