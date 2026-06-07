# 0003. Webhook retry policy: 3 attempts, exponential backoff

* **Status:** accepted
* **Date:** 2026-05-26
* **Deciders:** @petrefiedthunder

## Context and problem statement

When an approval is decided, Sentinel POSTs to every registered customer webhook URL. Customer endpoints will sometimes be:

- Briefly unreachable (deploy in progress, network blip)
- Overloaded (5xx from the customer's app)
- Behaving correctly but slow
- Permanently broken (URL changed, 404)
- Deliberately rejecting (signature check failure, 401)

We need a retry policy that distinguishes "give it another shot" from "the customer told us no, stop bothering them."

## Decision drivers

* **Customer ergonomics.** Their deploy shouldn't lose webhooks.
* **Cost containment.** Endless retries against a permanently-broken URL waste compute and clog the work queue.
* **Stripe parity.** Customers familiar with Stripe will expect similar semantics — Stripe retries for 3 days with exponential backoff. We should be close enough to feel familiar but simpler.
* **Don't block the decision endpoint.** The decision API must return immediately. Retries happen in background tasks.
* **Idempotency on the receiver side.** We give every delivery a stable `X-Sentinel-Delivery` id so customers can dedupe.

## Considered options

* **A. 3 attempts, exponential backoff (1s, 4s, 16s), 5xx/network retried, 4xx terminal (chosen)**
* **B. Stripe-like: 70+ attempts over 3 days with exponential backoff**
* **C. Fixed-interval retries (every 5 min for an hour)**
* **D. No retries — customer must implement their own resilience**

## Decision outcome

**Chosen option: A**. Maximum 3 attempts. Sleep 1s then 4s then 16s between them.

Retry on:
- Network error (connection refused, DNS fail, timeout, etc.)
- 5xx responses
- 408 Request Timeout
- 429 Too Many Requests

Don't retry on:
- 4xx responses (except 408/429) — the customer's app actively rejected us
- 2xx — done

Total wall-clock for a failing delivery: at most 21 s. After the 3rd failure we record terminal failure in `webhook_deliveries` and stop.

### Positive consequences

* Tight liveness — webhook fan-out completes within ~21 s worst-case per endpoint
* Customer 4xx (signature failure, bad URL parser, business-logic reject) doesn't get hammered
* Simple to reason about, simple to test
* Easy for the customer to implement a re-drive mechanism — they query `GET /v1/webhooks/deliveries?status_code=null` to find unhandled ones

### Negative consequences (the trade-off we accepted)

* If a customer's app is down for >21 s, the delivery is lost
* No automatic redrive after the customer's app comes back up (manual via the API)
* Background tasks use `asyncio.create_task` — if the API container dies mid-retry, the retry is lost (no durable queue). Acceptable for now; revisit at scale (see [ARCHITECTURE.md](../../ARCHITECTURE.md) "future moves")

## Future moves to consider

When we have enough volume to justify it:

- Persist `webhook_deliveries.next_attempt_at` so a background job can re-drive failed deliveries beyond the 3-attempt window
- Surface a "redeliver" button in the dashboard
- Auto-disable endpoints that fail N consecutive deliveries (Stripe disables after 3 days of failures)
- Move to a durable queue (Postgres-based `pg_queue` table, or Cloudflare Queues, or AWS SQS) so retries survive a container restart

## Links

* Implementation: `app/services/webhooks.py`
* Receiver example: `webhooks-receiver/` in `sentinel-examples`
* Stripe's policy for reference: https://stripe.com/docs/webhooks#retries
