# Review Criteria — Acceptable Terms Library

The input to the document-review workflow's matching stage (SiteSource `client_boq/review/03_criteria_match`). It holds the contractor's standard acceptable positions. The pipeline reads each contract clause, proposes which criterion it corresponds to, and flags where the contract departs from the acceptable position. The AI proposes the match and drafts the rationale; the breach verdict is never AI — it is a deterministic threshold where the criterion is numeric, and a human gate everywhere else.

## How this file is used

- Structure per row: Clause Area → Acceptable Commercial Position → Why It Matters → Red Flag.
- Pluggable: a contractor edits rows here without any code change. The loader (`criteria_loader.py`) reads by category and clause-area ID.
- ID scheme: `<category-prefix>-<n>`, e.g. `TP-01`. Prefixes — TP (Time & Progress), PS (Payment & Security), SQD (Scope, Quality & Design), LR (Liability & Risk Allocation), SGA (Site & General Admin), OK (Other Key Terms).
- Editing rule carried from the main app: no referenced criterion is silently dropped. If a criterion cannot be resolved against the contract, the review flags it as unresolved rather than skipping it.

---

## 1. Time & Progress

How project duration impacts profitability and risk.

| ID | Clause Area | Acceptable Commercial Position | Why It Matters | Red Flag |
|----|-------------|-------------------------------|----------------|----------|
| TP-01 | Program & Float | Contractor owns the float; dates are achievable. | You need buffer for your own delays, not the client's. | "Principal owns all float" or "Time is of the essence." |
| TP-02 | EOT Entitlement | Broad causes (neutral events, weather, acts of God). | Without EOTs, you pay LDs for things you cannot control. | "At sole discretion of the Superintendent." |
| TP-03 | Time Bars | Minimum 5–10 business days for notices. | Administrative gotchas that strip your right to claim. | 24–48 hour notice periods. |
| TP-04 | Liquidated Damages | Capped at 5–10% of contract; genuine pre-estimate. | Prevents unlimited financial bleeding for delays. | Uncapped LDs, or LDs that act as a penalty. |
| TP-05 | Delay Costs | Recovery of prolongation costs for client delays. | Staying on site longer costs money (overhead/rentals). | "Time-only EOT" with no cost recovery. |
| TP-06 | Suspension | Entitlement to time + cost for client-ordered stops. | Idle labour and plant are margin killers. | Suspension without cost relief. |

## 2. Payment & Security

Focus on cash-flow projections.

| ID | Clause Area | Acceptable Commercial Position | Why It Matters | Red Flag |
|----|-------------|-------------------------------|----------------|----------|
| PS-01 | Payment Claims | Monthly claims; alignment with SOPA legislation. | Cash flow is the lifeblood of construction. | Long assessment periods (>20 business days). |
| PS-02 | Set-Off Rights | Only for quantified and notified debts. | Prevents the client holding your cash without cause. | "Unilateral right to set off any amount." |
| PS-03 | Pay-When-Paid | Strictly prohibited (per SOPA). | You should not bear the risk of the Principal's insolvency. | Any clause linking your payment to a third party. |
| PS-04 | Security (Retention) | 5% cap; 2.5% released at Practical Completion. | Ties up your working capital for 12+ months. | >5% retention, or no release at PC. |
| PS-05 | Recourse to Security | Notice required (e.g. 5 days) before calling BGs. | Protects against ambushes on your bank guarantee. | "Right to call security at any time without notice." |
| PS-06 | Final Certificate | Clear process to finalise the account after DLP. | Provides financial closure and certainty. | No mechanism to issue a Final Certificate. |

## 3. Scope, Quality & Design

Focuses on avoiding scope creep and building what you priced.

| ID | Clause Area | Acceptable Commercial Position | Why It Matters | Red Flag |
|----|-------------|-------------------------------|----------------|----------|
| SQD-01 | Document Priority | Contract → Scope → Drawings → Specs. | Resolves contradictions in documents (general vs specific). | "Contractor to provide everything necessary" (silent scope). |
| SQD-02 | Design Risk | No "fitness for purpose" unless specifically priced. | Fitness for purpose is often excluded by professional indemnity. | Silent performance warranties in trade packages. |
| SQD-03 | Variations | Valuation by agreed rates or cost + margin. | Ensures you are not forced to work at a loss on changes. | "Principal sets rates unilaterally." |
| SQD-04 | Latent Conditions | Cost + time relief for unknown site conditions. | You cannot price what you cannot see (e.g. rock/asbestos). | "Contractor bears all risk of site conditions." |
| SQD-05 | Defects Liability | 12 months max; rectification only of repaired items. | Long DLPs are effectively an unpriced maintenance period. | DLP restarts for the whole works after a minor repair. |
| SQD-06 | Warranties | Match manufacturer warranties; avoid "life of building." | Over-warranting creates a liability that outlives your business. | "Fitness for purpose" as a blanket warranty. |

## 4. Liability & Risk Allocation

Focuses on the catastrophic risks that could end a company.

| ID | Clause Area | Acceptable Commercial Position | Why It Matters | Red Flag |
|----|-------------|-------------------------------|----------------|----------|
| LR-01 | Liability Cap | Capped at contract value or insurance limit. | Protects your business from company-ending claims. | Uncapped liability. |
| LR-02 | Indemnities | Proportionate (only for your negligence). | Standard insurance will not cover you for others' fault. | "Indemnify the Principal regardless of cause." |
| LR-03 | Consequential Loss | Expressly excluded (loss of profit, revenue, data). | These losses are unpredictable and impossible to price. | "Including but not limited to economic loss." |
| LR-04 | Proportionate Liability | Legislation must apply; do not contract out. | Prevents you being 100% liable for a 5% mistake. | "Parties agree to contract out of Part IV of the Civil Liability Act." |
| LR-05 | Termination | Cure period required (e.g. 7–14 days) for default. | Prevents being kicked off site for minor, fixable issues. | "Immediate termination" for minor breaches. |
| LR-06 | Termination for Convenience | Must include loss of profit on uncompleted work. | Compels the client to think twice before walking away. | "No compensation" for termination for convenience. |

## 5. Site & General Admin

Focuses on day-to-day site operations and statutory compliance.

| ID | Clause Area | Acceptable Commercial Position | Why It Matters | Red Flag |
|----|-------------|-------------------------------|----------------|----------|
| SGA-01 | Access & Possession | Defined dates; exclusive or co-ordinated access. | Lack of access = delay. You cannot work if you cannot get in. | "Access at the Principal's convenience." |
| SGA-02 | WHS / Principal Contractor | Clear designation; power to control the site. | You bear the safety risk, so you must have the authority. | Named "PC" but denied control of site access. |
| SGA-03 | Dispute Resolution | Mandatory mediation/conference before litigation. | Keeps lawyers out of the room for as long as possible. | "Arbitration only," or no interim dispute path. |
| SGA-04 | IP Rights | Contractor retains background IP (your systems). | Prevents the client owning your proprietary methods. | "Blanket assignment of all IP to the Principal." |

## 6. Other Key Terms

Extension category. Empty in the source set — reserved for terms specific to a given contractor's business (e.g. insurance levels, subcontractor flow-down, novation, confidentiality). Add rows with the `OK-` prefix as they are defined.

| ID | Clause Area | Acceptable Commercial Position | Why It Matters | Red Flag |
|----|-------------|-------------------------------|----------------|----------|
| OK-01 | (to be defined) | | | |

---

## Deterministic threshold checks (rule-based subset)

The entries below have a numerically checkable red flag, so stage 03 can pre-flag them by rule before the human gate — this is the "rule for numeric criteria" half of the locked decision. Everything not in this table is qualitative: the AI flags a candidate, the human decides. Even for the rows below, the rule only raises the flag; the human still confirms the departure.

| ID | Rule (flag when true) | Field the AI must extract from the contract |
|----|----------------------|--------------------------------------------|
| TP-03 | notice period < 5 business days | time-bar notice period |
| TP-04 | LD cap absent, or LD cap > 10% of contract | liquidated-damages cap |
| PS-01 | payment assessment period > 20 business days | assessment/certification period |
| PS-04 | retention > 5%, or no release at Practical Completion | retention % and release trigger |
| PS-05 | notice before calling security < 5 days, or none | recourse-to-security notice period |
| LR-01 | no liability cap present (adequacy of the cap still human-judged) | liability cap presence/value |
| LR-05 | cure period < 7 days, or none | termination cure period |
| SQD-05 | DLP > 12 months (restart-on-repair is judged qualitatively) | defects-liability period |

---

## Notes for the pipeline

- Verdict is always human-gated (locked v1 decision). The AI never writes "breach / no breach."
- The AI's job at this stage: propose which criterion each contract clause maps to, extract the fields above, and draft the departure rationale and proposed position. All draft, all reviewed.
- This fixed library doubles as a consistency anchor. Feeding the AI the same structured criteria every run is itself what steadies the matching output — the prompt/schema/temperature settings for that live in the stage code, not here.
- Output of the stage lands in the departure register (see `reviewing_a_construction_contract_with_ai.md` for the register structure).
