# 0002. HMAC-signed magic-link approval tokens

* **Status:** accepted
* **Date:** 2026-05-26
* **Deciders:** @petrefiedthunder

## Context and problem statement

When Sentinel creates an approval and emails the human approver, the email contains "Approve" and "Reject" buttons. Clicking either of those buttons needs to:

1. Identify which approval it's deciding (an `action_id`)
2. Identify which decision (approved / rejected)
3. Prove the click came from a holder of the original email — without making the approver log in

A stranger who guesses an `action_id` must not be able to approve.

## Decision drivers

* **Zero-friction approver UX.** Approver clicks a link, decision recorded. No login, no app to install, no password.
* **Self-contained tokens.** The decision endpoint must validate without a separate DB lookup for the token.
* **Forgery resistance.** No way to compute a valid token without the server's secret.
* **Replay containment.** Tokens must expire, both because emails get forwarded and because we want bounded liability windows.
* **No PII in the URL.** Tokens land in HTTP server logs, CDN edge logs, and email client referrer headers — must not contain email addresses or function arguments.
* **Standard library only.** No new dependency for a 30-line cryptographic primitive.

## Considered options

* **A. HMAC-SHA256 over a JSON payload, scoped to one `action_id` + decision + expiry (chosen)**
* **B. JWT (signed with HS256 — same crypto, more spec, more libraries)**
* **C. Random opaque token stored in DB, looked up on click**
* **D. Encrypted token (AES-GCM) with `action_id` + decision in ciphertext**

## Decision outcome

**Chosen option: A. HMAC-SHA256 over a base64-url-encoded JSON payload**, scoped to a single `(action_id, decision, exp)` triple, signed with `settings.JWT_SECRET`.

Format: `base64url(json(payload)).hex(hmac_sha256(secret, base64url(json(payload))))`

Example payload:
```json
{"action_id": "act_abc123", "decision": "approved", "exp": 1748192400}
```

Verification rejects on: missing dot separator, signature mismatch, JSON parse error, action_id mismatch, expired `exp`, unknown decision value.

### Positive consequences

* No DB round-trip on the click path — verification is pure crypto
* Token is self-expiring; no janitor required
* `JWT_SECRET` rotation invalidates all outstanding tokens (a feature, not a bug)
* Implementation is 30 lines of stdlib — no `pyjwt` / `jose` / etc.
* Forwarded emails still let the recipient approve, as long as the token hasn't expired

### Negative consequences (the trade-off we accepted)

* Token revocation requires either rotating `JWT_SECRET` (nuclear option) or adding a DB-backed deny list (we don't yet)
* Anyone with the email can approve — there's no second factor for the approver
* `JWT_SECRET` must be a strong random value; we enforce this at signing time (`WEAK_SIGNING_SECRETS` set with known dev values)

## Pros and cons of the options

### B. JWT
* ➕ Familiar format
* ➖ Additional dependency (`pyjwt`)
* ➖ JWT has many footguns — `alg=none`, header injection, library confusion. Most libraries have had CVEs.
* ➖ The standard adds fields we don't need (iss, aud, etc.)

### C. Random opaque token + DB lookup
* ➕ Easy revocation (delete the row)
* ➖ Adds DB load on every click
* ➖ Requires a janitor cron to expire old tokens
* ➖ More moving parts

### D. AES-GCM encrypted token
* ➕ Confidentiality on top of integrity
* ➖ We don't need confidentiality — action_id is already opaque
* ➖ Larger tokens
* ➖ Nonce management

## Links

* Implementation: `app/services/approval_tokens.py`
* Onboarding equivalent (verify + recover links): `app/services/onboarding.py` — uses same primitive, scoped to `purpose` instead of `decision`
* Webhook signing uses the same HMAC primitive over the raw body — see ADR-0003
