# NIST AI Risk Management Framework — Alignment Statement

> **⚠️ DRAFT — requires legal/compliance review before use.**
> This is an internal working draft prepared by engineering. It has **not**
> been reviewed by counsel or an independent assessor. The NIST AI Risk
> Management Framework (AI RMF 1.0) is a **voluntary** framework; mapping to it
> is **self-attested** and is **not** a certification, audit, or conformity
> assessment. Nothing here claims any third-party validation. Statements that
> are aspirational or only partially implemented are flagged explicitly.

---

## Purpose and scope

This document maps the Sentinel service to the four functions of the **NIST AI
Risk Management Framework 1.0 (NIST AI 100-1, January 2023)**: **GOVERN**,
**MAP**, **MEASURE**, and **MANAGE**.

**What Sentinel is, in AI RMF terms.** Sentinel is not itself a
decision-making AI model. It is an **AI risk-management control**: it pauses an
AI agent before a designated action runs, routes that action to a human for
explicit approval, and proceeds only on approval — producing a tamper-evident
record of who decided what and when. In NIST's vocabulary, Sentinel
operationalizes **human oversight and accountability** for AI systems built by
our customers. The framework's "AI actor" performing the risky task is the
customer's agent; Sentinel is the **oversight and accountability layer** around
it.

This dual role matters for honesty: Sentinel helps our **customers** satisfy
parts of the AI RMF for *their* AI systems, and we separately apply the RMF to
*our own* operation of the Service. Both are addressed below, and gaps in each
are stated plainly.

---

## GOVERN — culture, policies, accountability

*GOVERN establishes the policies, processes, and accountability structures for
managing AI risk.*

| Subcategory (theme) | How Sentinel relates | Status / gap |
|---|---|---|
| **GOVERN 1** (policies & processes for mapping/measuring/managing AI risk) | We maintain a written threat model (STRIDE), architecture decision records, a production checklist, and an incident-response runbook governing the Service. | Implemented for the Service. Formal company-wide AI risk **policy** document: **gap — not yet written.** |
| **GOVERN 2** (accountability structures) | Ownership is assigned (threat model has a named owner and annual review cadence); admin actions require a distinct privileged credential. | Partial — small/solo org; accountability is concentrated, which is itself a documented risk. |
| **GOVERN 3** (diverse, inclusive teams inform decisions) | — | **Gap — not applicable at current org size; disclose, do not overstate.** |
| **GOVERN 4** (organizational commitment to communicating AI risk) | The threat model, architecture, and limitations ("what we don't have yet") are documented candidly and shared. | Partial. |
| **GOVERN 5** (engagement with stakeholders) | Customers receive sub-processor notice and can verify their own audit chain; residual risks are tracked. | Partial. |
| **GOVERN 6** (third-party / supply-chain risk) | Sub-processors are enumerated; vendor risk is acknowledged in the threat model. | Partial — dependency scanning / SBOM are **roadmapped, not complete**; state honestly. |

**Sentinel's contribution to a customer's GOVERN function:** by inserting a
mandatory human approval gate, Sentinel gives the customer an enforceable
accountability mechanism and an audit record — directly supporting *their*
GOVERN 1/2/4 obligations for the agent they operate.

---

## MAP — context and risk identification

*MAP establishes the context to frame and identify risks and impacts.*

| Subcategory (theme) | How Sentinel relates | Status / gap |
|---|---|---|
| **MAP 1** (context, purpose, legal/normative setting understood) | The Service's purpose, trust boundaries, and assets-to-protect are documented in the threat model. | Implemented for the Service. |
| **MAP 2** (tasks, methods, and limits categorized) | Each approval carries a `function_name`, structured `arguments`, and a `risk_level`, so the customer categorizes the action being gated. | Implemented as a customer-facing capability. |
| **MAP 3** (capabilities, benefits, costs vs. benchmarks) | The product's benefit (preventing an unapproved risky action) and its limits are documented. | Partial — no formal benchmark suite. |
| **MAP 4** (component & third-party risk mapped) | STRIDE analysis covers every trust boundary including vendor boundaries; residual risks are ranked. | Implemented for the Service. |
| **MAP 5** (impacts on individuals/groups/society characterized) | The threat model identifies approver PII and TCPA exposure; consent state is tracked per approver contact. | Partial. |

**Sentinel's contribution to a customer's MAP function:** the `risk_level`
field and per-action approval record force the customer to characterize *which*
agent actions are consequential — the core of MAP 2 and MAP 5 for their system.

---

## MEASURE — analysis, assessment, monitoring

*MEASURE uses tools and metrics to analyze, assess, and track AI risks over
time.*

| Subcategory (theme) | How Sentinel relates | Status / gap |
|---|---|---|
| **MEASURE 1** (methods/metrics aligned to mapped risks) | Residual risks in the threat model are individually tracked; each becomes a backlog ticket. | Partial. |
| **MEASURE 2** (systems evaluated for trustworthy characteristics) | The audit chain is independently **verifiable by the customer** (read-only verification endpoint); the codebase has an automated test suite. | Partial — security claims are verified against code on a stated date, not by an external assessor. |
| **MEASURE 3** (mechanisms to track risk over time, incl. emergent) | The hash-chained audit log produces a durable, time-ordered record; uptime probes and error monitoring are in place. | Partial. |
| **MEASURE 4** (feedback validates measurement efficacy) | A 2026-06 incident (audit-chain fork from a concurrent-append race) was detected **by the verification mechanism itself**, then fixed (advisory lock + deterministic head selection). This is documented. | Demonstrated once; not a formalized continuous program. |

**Sentinel's contribution to a customer's MEASURE function:** the tamper-evident,
verifiable audit trail is, in effect, a measurement instrument — it lets a
customer (or their auditor) confirm after the fact that human oversight
actually occurred for each gated action.

---

## MANAGE — prioritize and respond

*MANAGE allocates resources to respond to mapped and measured risks.*

| Subcategory (theme) | How Sentinel relates | Status / gap |
|---|---|---|
| **MANAGE 1** (risks prioritized and responded to) | The threat model ranks its top residual risks and assigns each to a squad backlog. | Implemented for the Service. |
| **MANAGE 2** (strategies to maximize benefit / minimize harm) | The whole product is a harm-minimization control: no approval, no action. Webhook retries, replay guards, and rate limiting bound failure modes. | Implemented (with disclosed gaps, e.g. fail-open rate limiting). |
| **MANAGE 3** (third-party risks monitored & controlled) | Sub-processor list maintained; signed/verified vendor webhooks. | Partial. |
| **MANAGE 4** (response/recovery/communication plans documented) | An incident-response runbook exists; breach-notification commitments appear in the draft DPA. | Partial — recovery (e.g. multi-region failover) is **not implemented**; disclose. |

**Sentinel's contribution to a customer's MANAGE function:** Sentinel is the
*response control itself* for the highest-consequence agent actions — the human
gate is the documented intervention required by MANAGE 1/2 for their AI system.

---

## Honest summary of gaps (do not omit when sharing)

1. **No external assessment or certification.** This is self-attestation only.
2. **Concentrated org / no formal AI governance policy** (GOVERN 1/3 gap).
3. **Supply-chain controls (SBOM, automated dependency scanning) are
   roadmapped, not complete** (GOVERN 6 gap).
4. **RFC 3161 timestamping is implemented but config-gated and not yet
   chain-validating** — do not present audit timestamping as continuously
   active or certified.
5. **Rate limiting fails open** if Redis is down (a disclosed residual risk).
6. **No multi-region failover / formal disaster recovery test** (MANAGE 4 gap).
7. **Approver authenticity is "a valid token was used," not "this specific
   human"** — a known limitation of the magic-link design.

Sentinel's strongest, defensible AI RMF claim is narrow and true: it provides
a **verifiable human-in-the-loop oversight and accountability control** that
helps customers operationalize the GOVERN and MANAGE functions for their own AI
agents, with a tamper-evident record that supports MEASURE. Claims beyond that
should be reviewed before use.

---

## References

- NIST AI Risk Management Framework 1.0 — NIST AI 100-1 (January 2023),
  functions GOVERN / MAP / MEASURE / MANAGE and their categories.
- Internal: `docs/threat-model.md`, `docs/adr/*`, `docs/production-checklist.md`,
  `docs/runbooks/incident-response.md`, `ARCHITECTURE.md`.
