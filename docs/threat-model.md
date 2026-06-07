# Sentinel — Threat Model (STRIDE)

Last updated: 2026-06-07 · Owner: @petrefiedthunder · Review cadence: annually + after any architecture change

## 1. System overview

Sentinel pauses an AI agent before a risky action runs, asks a human to approve, and only proceeds on approval. Flow:

```
Agent app ──POST /v1/approvals──► Sentinel API (Railway/FastAPI)
                                      │  persists approval, audit event
                                      ├─► Resend (email magic link)
                                      ├─► Twilio (SMS magic link)
                                      │
Human ◄── email/SMS with HMAC link ──┘
   │
   └─POST /v1/approvals/{id}/token-decision (signed token)──► API
                                      │  records decision, NOTIFY
                                      ├─► webhook fan-out (HMAC-signed)
                                      └─► SDK long-poll /wait unblocks
Agent app resumes (runs the function or raises ApprovalRejected)
```

## 2. Assets we protect

| Asset | Why it matters |
|---|---|
| Approval decision authenticity | A forged "approved" lets an agent do the dangerous thing |
| API keys | Full tenant control; create/decide approvals |
| Audit log integrity | The compliance product *is* the tamper-evidence |
| Approval content (function name, arguments) | May contain sensitive business data |
| Approver contact info (email/phone) | PII; TCPA obligations on phone |
| Customer data residency | Contractual (us-east only today) |
| Billing / Stripe state | Financial |

## 3. Trust boundaries

1. **SDK ↔ API** — authenticated by Bearer API key over TLS
2. **Approver's inbox/phone ↔ API** — magic-link token, no login
3. **API ↔ Postgres / Redis** — internal Railway network
4. **API ↔ Resend / Twilio / Stripe** — outbound HTTPS with vendor keys
5. **Vercel edge ↔ Railway origin** — TLS; edge terminates public TLS
6. **Customer endpoint ↔ API (webhooks)** — outbound HMAC-signed POST

## 4. STRIDE analysis

### Boundary 1 — SDK ↔ API

| Category | Threat | Mitigation | Residual |
|---|---|---|---|
| Spoofing | Attacker uses a stolen API key | Keys are `sk_live_…`/`sk_test_…` 32-byte random, stored as SHA-256 hash only (`app/auth.py`). Rotate via `/recover`. | Key theft on the customer side is out of our control; mitigated by recommending env-var storage |
| Tampering | Modify request in transit | TLS 1.2+ enforced everywhere | none material |
| Repudiation | Customer denies creating an approval | Every create writes a hash-chained audit event | low |
| Information disclosure | Sniff approval payloads | TLS; payloads never logged (structlog omits bodies) | low |
| DoS | Flood `POST /v1/approvals` | Redis rate limiter (`app/services/rate_limit.py`), per-IP + per-domain | medium — see residual risk #2 |
| Elevation | Use one tenant's key to read another's data | Every authed endpoint scopes by `tenant_id` via `get_current_tenant` | low |

### Boundary 2 — Approver inbox/phone ↔ API (the magic link)

| Category | Threat | Mitigation | Residual |
|---|---|---|---|
| Spoofing | Stranger guesses an approve URL | Token is HMAC-SHA256 over `(action_id, decision, exp)` signed with `JWT_SECRET` (`app/services/approval_tokens.py`). Cannot forge without the secret. | low |
| Tampering | Change `decision=approved` in the URL | Decision is inside the signed payload; tampering breaks the signature | none material |
| Repudiation | Approver denies clicking | Audit event records `decided_by="signed_link"` + timestamp | medium — we record "a valid token was used", not "this specific human clicked". See residual #1 |
| Information disclosure | Token in email leaks via referer/proxy logs | Token carries no PII — only an opaque action_id + decision. | low |
| DoS | Replay an old approve link | **Already mitigated**: the decision endpoint checks `approval.decision != "pending"` and returns 400 on any already-decided approval. A replayed token is inert. | low — a dedicated one-use nonce would add marginal value but the decision-state guard already makes replays no-ops |
| Elevation | Use one approval's token on another approval | Token's `action_id` is bound + checked server-side (`verify_decision_token(token, action_id)`) | none material |

### Boundary 3 — API ↔ Postgres / Redis

| Category | Threat | Mitigation | Residual |
|---|---|---|---|
| Tampering | Direct DB write forges an "approved" | Railway private network; no public DB exposure | medium — a DB compromise is full compromise. See residual #3 |
| Repudiation | Edit the audit log to hide an action | Hash chain: `event_hash = sha256(prev_hash + payload)`. Editing one row breaks every subsequent hash. | medium — chain is verifiable but we don't yet publish the root externally (RFC 3161 timestamping is roadmapped) |
| Information disclosure | Dump the DB | Encrypted at rest (AES-256, AWS-managed via Railway) | low |

### Boundary 4 — API ↔ Resend / Twilio / Stripe

| Category | Threat | Mitigation | Residual |
|---|---|---|---|
| Spoofing | Fake Stripe webhook flips a tenant to Pro | Stripe signature verified (`app/routers/billing.py` `_verify_stripe_signature`, HMAC over `t.payload`, 5-min replay window) | low |
| Information disclosure | Vendor breach leaks approver emails/phones | Subprocessor DPAs; minimal data shared; documented at /subprocessors | medium — vendor risk inherent |

### Boundary 5 — Vercel edge ↔ Railway origin

| Category | Threat | Mitigation | Residual |
|---|---|---|---|
| Spoofing | Bypass the edge, hit origin directly | Origin accepts any caller today (no edge-shared-secret). See residual #4 | medium |
| Tampering | MITM between edge and origin | TLS on the origin leg | low |

### Boundary 6 — API ↔ customer webhook endpoint

| Category | Threat | Mitigation | Residual |
|---|---|---|---|
| Spoofing | Attacker POSTs fake events to customer's URL pretending to be us | We sign every delivery `X-Sentinel-Signature` = HMAC-SHA256(secret, raw_body). Customers verify. | low — depends on customer verifying (we document it heavily) |
| Tampering | Modify delivery in transit | TLS + signature over raw body | none material |
| DoS | We hammer a customer's down endpoint | 3-attempt cap, exponential backoff, 4xx is terminal (ADR-0003) | low |

## 5. Top 5 residual risks (prioritized)

1. **Approver authenticity is "valid token" not "this human".** Anyone with access to the approver's inbox/phone can approve. *Close it:* optional second factor on high-risk approvals (e.g. require the approver to be a logged-in dashboard user for `risk_level=critical`). Roadmapped.
2. **Rate limiting is fail-open.** If Redis is unreachable, the limiter allows all traffic (`app/services/rate_limit.py`). A Redis outage = an abuse window. *Close it:* add a conservative in-process fallback counter when Redis is down.
3. **DB compromise = full compromise.** An attacker with Postgres write access can forge approvals and decisions. The hash chain detects audit tampering but not a forged-from-the-start approval. *Close it:* RFC 3161 external timestamping (roadmapped, migration 009 already stages the column) + Merkle root publication so forgeries are externally detectable.
4. **Origin has no edge-shared-secret.** Someone who discovers the Railway origin URL can bypass the Vercel edge (and its protections). *Close it:* require a shared secret header injected by the edge proxy, rejected if absent at origin.
5. **JWT_SECRET rotation is all-or-nothing.** Rotating invalidates every outstanding approval link with no grace period. *Close it:* support two active signing secrets (current + previous) during a rotation window.

## 6. Out of scope (v1)

- Quantum-resistant signatures
- Side-channel/timing attacks on HMAC comparison (we use `hmac.compare_digest`, which is constant-time — so this is actually covered, but we don't formally test it)
- Physical security of vendor data centers (delegated to Railway/Vercel/AWS)
- Social engineering of the founder
- Supply-chain attack on a transitive dependency (partially mitigated: Dependabot + SBOM + pip-audit roadmapped)

## 7. Review cadence

- Re-review this document annually
- Re-review after any change to: auth, token format, audit chain, a new trust boundary (new vendor), or a new public endpoint
- Each residual risk above becomes a tracked ticket in the appropriate squad backlog

## 8. Verification notes

Claims in this document were checked against code on 2026-06-07:
- ✅ API keys hashed: `app/auth.py:hash_key`
- ✅ Token HMAC: `app/services/approval_tokens.py`
- ✅ Decision-state replay guard: `app/routers/approvals.py` `decide_with_token` → `if approval.decision != "pending": raise 400`
- ✅ Stripe signature verify: `app/routers/billing.py:_verify_stripe_signature`
- ✅ Webhook signing: `app/services/webhooks.py:sign_body`
- ✅ Hash-chained audit: `app/services/audit_log.py`
- ⚠️ Origin edge-secret: NOT implemented (residual #4)
- ⚠️ RFC 3161 timestamping: column staged (migration 009), integration roadmapped (residual #3)
