# EU AI Act — Limited-Risk Conformance Worksheet

> **⚠️ DRAFT — requires legal/compliance review before use.**
> This is an internal working draft prepared by engineering to support — not
> replace — review by qualified EU counsel. It has **not** been reviewed by a
> lawyer. It is **not** a legal opinion, a conformity assessment, or a
> certification, and it does **not** establish the regulatory classification of
> the Service. The EU AI Act (Regulation (EU) 2024/1689) is being phased in;
> obligations and dates are subject to change and to authoritative guidance.
> **Final risk classification depends on the customer's actual deployment
> context (see Section 5).**

---

## 1. Purpose

This worksheet records our **preliminary, self-assessed** view of where the
Sentinel service sits under the EU AI Act's risk tiers and what transparency
obligations could apply, so counsel can confirm or correct it. It is structured
around the Act's four-tier model: **prohibited**, **high-risk**,
**limited-risk (transparency)**, and **minimal-risk**.

## 2. What the system does (factual basis)

Sentinel pauses an AI agent before a designated action runs, sends the action
to a **human** to approve or reject, and proceeds only on the human's decision.
It stores approval records, a tamper-evident audit trail, and delivers result
webhooks. **Sentinel does not make the substantive decision** — a human does.
Sentinel performs no biometric processing, no emotion recognition, no content
generation, no profiling, and no automated scoring of people.

## 3. Tier screening

### 3.1 Prohibited practices — Article 5 (screen: NOT prohibited)

Article 5 prohibits, among others: subliminal/manipulative techniques;
exploitation of vulnerabilities; social scoring; profiling-only predictive
policing; untargeted facial-image scraping; emotion recognition in
workplace/education; biometric categorization to infer protected
characteristics; and real-time remote biometric identification in public
spaces.

**Assessment:** Sentinel performs none of these. It does the opposite of
manipulation — it **inserts a human decision gate**. Preliminary conclusion:
**not a prohibited practice.** *(Counsel to confirm.)*

### 3.2 High-risk — Article 6 + Annex III (screen: NOT high-risk as supplied)

A system is high-risk if it is (a) a safety component of a product under EU
harmonization legislation requiring third-party conformity assessment (Art.
6(1) / Annex I), **or** (b) it is used in one of the Annex III domains (Art.
6(2)): biometrics; critical infrastructure; education & vocational training;
employment & worker management; access to essential private/public services
(incl. credit, insurance, benefits); law enforcement; migration/border control;
administration of justice and democratic processes.

**Assessment of Sentinel *as supplied*:** Sentinel is a general-purpose
human-approval gateway. It is **not** a safety component of a regulated product
and is **not**, by itself, an Annex III system — it does no biometrics, makes no
eligibility or essential-services decision, and does no profiling.

**Article 6(3) exemption logic (relevant if a customer deploys it in an Annex
III context):** even where an Annex III area is touched, a system is **not**
high-risk if it does not pose a significant risk of harm to health, safety, or
fundamental rights — for example because it (a) performs a **narrow procedural
task**, (b) **improves the result of a previously completed human activity**,
(c) **detects decision patterns without replacing or influencing the human
assessment**, or (d) performs a **preparatory task** to an assessment. Sentinel's
function — requiring and recording an **explicit human decision** rather than
automating one — aligns most closely with limbs (c) and the principle behind
the exemption: the human, not the system, decides.

**Critical caveat (Art. 6(3) final sentence):** the exemption does **not**
apply if the system performs **profiling of natural persons**. Sentinel does
not profile. If a customer were to configure it to do so, this analysis changes.

**Important — provider documentation duty (Art. 6(4)):** a provider who
considers an Annex III system not to be high-risk must **document that
assessment before placing it on the market**. If, after counsel review, any
configuration of Sentinel is deemed to touch Annex III, that documentation
obligation must be met. This worksheet is a starting point for it, not a
substitute.

### 3.3 Limited-risk (transparency) — Article 50 (likely tier)

Article 50 imposes **transparency** obligations on certain systems regardless
of risk tier:

| Art. 50 paragraph | Obligation | Applies to Sentinel? |
|---|---|---|
| **50(1)** | Providers ensure that systems **intended to interact directly with natural persons** inform those persons they are interacting with an AI, unless obvious. | **Plausibly relevant.** Sentinel sends approval requests **to humans** (the approvers). The notifications are AI-triggered. Recommended posture: clearly identify in the approval message that the request originates from an automated/AI agent via Sentinel. *(Counsel to confirm whether the human approver counts as "interacting with" the AI system within the meaning of 50(1).)* |
| **50(2)** | Providers of systems **generating synthetic** audio/image/video/text mark output as artificially generated (machine-readable). | **Not applicable** — Sentinel generates no synthetic media or content. |
| **50(3)** | Deployers of **emotion recognition / biometric categorization** inform exposed persons. | **Not applicable** — no emotion recognition or biometric processing. |
| **50(4)** | Deployers disclose **deepfakes** / AI-generated published text. | **Not applicable.** |
| **50(5)** | Information must be **clear, distinguishable, accessible**, at the latest at first interaction/exposure. | If 50(1) applies, satisfy by labeling the approval notification at first contact. |

**Preliminary conclusion:** Sentinel is best characterized, as supplied, as a
**limited-risk system whose only plausible obligation is the Article 50(1)
transparency duty** (identify the AI to the human approver). All other Article
50 limbs do not apply. *(Counsel to confirm 50(1) applicability and exact
wording.)*

### 3.4 Minimal-risk

If counsel concludes 50(1) does not apply (e.g. because the human approver is
not "interacting with" the AI system in the regulatory sense, but rather acting
as an oversight authority over it), Sentinel would fall to **minimal risk**,
with no mandatory AI-Act obligations — voluntary codes of conduct only.

## 4. Transparency implementation checklist (if Art. 50(1) applies)

- [ ] Approval notifications (email/SMS and dashboard) state that the request
      was **initiated by an automated AI agent** and routed via Sentinel.
- [ ] The disclosure is **clear and distinguishable** and present at **first
      contact** (Art. 50(5)).
- [ ] Disclosure language is reviewed by counsel and localized as needed.
- [ ] Customer-facing docs explain that the **customer is the deployer** and may
      have their own Article 50 / context-specific obligations.

## 5. Customer deployment context governs final classification

**This is the decisive point and must be stated to customers.** Sentinel's
classification *as a tool* is preliminary and favorable (not prohibited; not
high-risk as supplied; at most limited-risk under Art. 50(1)). But the EU AI
Act classifies systems **by use**, and the customer is typically the
**deployer** (and may become a **provider** if they materially modify or
rebrand the system).

A customer who embeds Sentinel into an Annex III workflow — for example gating
**hiring/firing** decisions (employment), **credit or insurance eligibility**
(essential services), **medical** actions, **law-enforcement** actions, or
**migration** decisions — may cause the **surrounding AI system** to be
high-risk, triggering the full Article 8–17 obligations (risk management,
data governance, logging, human oversight, accuracy/robustness, conformity
assessment, registration) on **that customer**. Sentinel's human-gating and
audit-logging features can *support* a customer's human-oversight (Art. 14) and
record-keeping (Art. 12) obligations, but using Sentinel does **not** by itself
make a high-risk deployment compliant.

**Recommended contractual posture (for counsel):** state that (a) Sentinel is
supplied as a limited-risk transparency-obligated tool, (b) the customer is
responsible for classifying and conforming **their** deployment, and (c) the
customer must not deploy Sentinel into a prohibited use.

## 6. Honest gaps and open questions for counsel

1. Does the human approver "interact with" the AI system under Art. 50(1), or
   is the approver an **oversight authority** outside 50(1)? This determines
   limited-risk vs. minimal-risk.
2. Exact required wording, format, and machine-readability (if any) of the
   50(1) disclosure.
3. Whether any standard customer integration could itself pull Sentinel into a
   provider/Annex III posture (triggering Art. 6(4) documentation).
4. Interaction with GDPR transparency duties (see the draft DPA) — overlapping
   but distinct.
5. Phase-in dates applicable to the obligations identified here.

---

## References

- Regulation (EU) 2024/1689 (EU AI Act): **Article 5** (prohibited practices),
  **Article 6** + **Annex III** (high-risk classification, incl. Art. 6(3)
  exemptions and Art. 6(4) documentation duty), **Article 50** (transparency
  obligations, paragraphs 1–5).
- Internal: `docs/threat-model.md`, `ARCHITECTURE.md`,
  `docs/compliance/dpa-template.md`.
