# Incident Response Runbook

This is the document we follow when something is on fire in production. It is intentionally short — long runbooks don't get read during incidents.

## Severity matrix

| Sev | Definition | Examples | Response time |
|---|---|---|---|
| **Sev1** | Customer impact, sustained | API returning 5xx for > 1 min; data loss; security breach in progress | < 15 min ack |
| **Sev2** | Customer impact, intermittent | Elevated p99 latency; webhook delivery degraded; isolated tenant errors | < 1 h ack |
| **Sev3** | Degraded but not customer-visible | Internal monitoring noise; deploy rollback needed | < 4 h ack |
| **Sev4** | Heads-up | Dependency vendor announced upcoming maintenance | next business day |

## When something looks wrong

1. **Confirm it is real.** Check `https://pauseapi.app/status`. If our status page says green but you're seeing red, your monitoring is right. Trust your monitoring.
2. **Open a Sev label.** Sev1/Sev2 must be communicated externally. Sev3/Sev4 are internal-only.
3. **Acknowledge externally** within the SLA above:
   - Update the status page banner
   - For Sev1 affecting paid customers, send an email to affected accounts within 2 h
4. **Investigate.** See "Common incidents" below for first-pass recipes.
5. **Mitigate** before perfectly diagnosing. Restore service first; root-cause later.
6. **Communicate** updates at minimum every 30 min on Sev1, every 2 h on Sev2.
7. **Resolve** — clear the status page banner, send all-clear email.
8. **Postmortem.** Public postmortem for Sev1, internal for Sev2. Within 5 business days.

## On-call

Currently a one-person rotation (you, the founder). Phone alerts go to **+12133227605**.

Escalation chain:
1. You acknowledge within 15 min
2. If no ack in 15 min, automated paging escalates (NOT YET WIRED — add PagerDuty in Phase 2)
3. After PagerDuty: backup on-call (TBD when team grows)

## Common incidents — first-pass recipes

### API returning 5xx

```bash
# Check Railway logs
cd ~/sentinel-build/sentinel-api && railway logs --deployment | tail -50

# Look for:
#  - "column X does not exist" → migration didn't run; see "migration failed"
#  - "connection reset" / "ECONNREFUSED" → DB or Redis down; see "Postgres down"
#  - "alembic upgrade head" not in startup logs → container didn't run migrations

# Check current /health
curl https://api.pauseapi.app/health

# Roll back to last green deploy
railway rollback
```

### Migration failed during deploy

Symptoms: container starts but fails before uvicorn comes up.

```bash
# Inspect the failing revision
cd ~/sentinel-build/sentinel-api
git log --oneline alembic/versions/

# If the chain is broken (down_revision doesn't match), see ADR-0002
# Fix the chain, push, redeploy
```

### Postgres down

Railway-side outage:
1. Confirm at `https://status.railway.com`
2. Update our status page → "Investigating: vendor outage"
3. Sentinel returns 503 for all writes until DB recovers
4. Long-poll waits on existing approvals fail gracefully → SDK clients see `SentinelAPIError`
5. Approvals already pending will NOT execute their wrapped function (this is by design — fail-closed)

If Railway recovers but our DB schema looks wrong:
- Don't manually edit. Restore from the most recent backup (RTO ≤ 1 h)

### Webhook delivery failing for one customer

```bash
KEY=...   # admin API key
curl -H "Authorization: Bearer $KEY" \
  "https://api.pauseapi.app/v1/admin/stats"

# If the customer's endpoint is returning 5xx, that's their problem.
# Tell them to fix their endpoint; their deliveries are queued for redelivery.

# If our delivery side is broken (5xx FROM us), check sentinel-api logs:
railway logs --deployment | grep -i webhook | tail -20
```

### Magic-link approve URL returns 401

Likely cause: `JWT_SECRET` rotated (which invalidates all outstanding tokens).
Mitigation: explain to the affected approver, ask them to retrigger the approval.

### Resend bounce / SMS undelivered

These don't constitute an outage on our side. Document in postmortem if customer-reported. Long-term: surface delivery failures in the dashboard.

## Communications templates

### Sev1 initial customer email

> Subject: [Sentinel] Service disruption — investigating
>
> Hi <name>,
>
> We're currently investigating a service disruption affecting Sentinel
> approvals. We detected the issue at <UTC time> and are actively working
> on a fix. Updates every 30 minutes at https://pauseapi.app/status
>
> If your workflow is time-sensitive, the recommended workaround is to
> set `fallback="execute"` on `@oversight()` calls for actions below your
> risk threshold during the outage.
>
> — Christopher

### Sev1 resolved email

> Subject: [Sentinel] Service restored
>
> Hi <name>,
>
> The disruption that started at <UTC start> is resolved as of <UTC end>.
> Total impacted window: <duration>.
>
> What happened: <1-2 sentences>
>
> What we're doing about it: <1-2 sentences>
>
> Full public postmortem within 5 business days at https://pauseapi.app/status
>
> If you'd like a credit applied per our SLA (https://pauseapi.app/sla),
> reply to this email with your tenant ID.
>
> — Christopher

### Public postmortem template

Live at `https://pauseapi.app/postmortems/YYYY-MM-DD` (TODO: build that route).

Include:
- Customer impact (who, how, how long)
- Timeline (UTC)
- Root cause (technical)
- What we're changing to prevent recurrence
- What you can do as a customer if you're worried

## Drills

We aim to run an unannounced Sev2 drill quarterly:
- Kill a random Railway container
- Trigger a synthetic 5xx burst
- Restore from a recent backup to a fresh project (validates RTO claim)

Drill results are logged in `docs/runbooks/drills.md` (to be created on first drill).

## What to do BEFORE the next incident

Phase 2 items that will materially improve our incident response:

- [ ] PagerDuty / Better Stack on-call integration
- [ ] Sentry transport from structlog (errors with full trace context)
- [ ] Multi-region failover documented and tested
- [ ] Backup restore drill run, screenshotted, evidence kept
- [ ] On-call escalation chain with a real second person
