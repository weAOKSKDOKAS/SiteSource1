# SOPO (Cap. 652) — Plain-language overview (Layer 3 reference)

> ⚠️ **Reference material, not legal advice.** Plain-language summary written to
> ground drafting and validation. It is **not a substitute for the enacted text**.
> Provenance tiers used below:
> - **SOURCED (CIC FAQ ...)** — grounded in the official CIC SOPO FAQ (cic.hk).
> - **SOURCED (law-firm summary)** — grounded in a secondary law-firm summary.
>   Both are secondary; cross-check against the e-legislation Cap.652 text.
> - **`# UNVERIFIED — confirm with Cap.652 text/QS`** — anything beyond those;
>   not yet confirmed.
>
> Authoritative numbers live in `backend/rules_engine/sopo_config.py` (same tiers).

## What SOPO is

The **Construction Industry Security of Payment Ordinance (Cap. 652)** ("SOPO")
is Hong Kong legislation intended to improve cash flow in the construction supply
chain. Its core idea: a party that has carried out construction work (or supplied
related goods/services) has a statutory right to claim payment, to receive a
timely response, and to refer a payment dispute to **adjudication** — a fast,
interim-binding process — rather than waiting for arbitration or litigation.
SOPO provides three linked mechanisms: **payment → adjudication → enforcement.**

## Scope — when it applies

SOURCED (law-firm summary) — cross-check against Cap.652 text:

- Applies to both **public- and private-sector** construction contracts.
- Applies to qualifying contracts **entered into on or after 28 August 2025**.
- Monetary thresholds (at the relevant contract level):
  - **main contract for construction work: above HK$5,000,000**;
  - **related goods/services: above HK$500,000**.

> **Subcontracts** within a covered contractual chain have **no minimum value** —
> they are covered regardless of their own contract value. SOURCED (CIC FAQ Q5/Q11)
> — cross-check Cap.652 text. (Exactly how the head-contract thresholds otherwise
> interact across a chain: **# UNVERIFIED — confirm with Cap.652 text/QS**.)

## Exclusions

SOURCED (law-firm summary) — cross-check against Cap.652 text:

- Contracts relating to **existing private residential** premises.
- **Minor non-residential** works that **do not require Building Authority
  approval**.

> Any other carve-outs or definitional limits are **# UNVERIFIED — confirm with
> Cap.652 text/QS**.

## Pay-when-paid / pay-if-paid prohibited

SOURCED (law-firm summary) — cross-check against Cap.652 text: **conditional
("pay-when-paid" / "pay-if-paid") payment provisions are prohibited** — a payer
cannot make payment contingent on first being paid by someone else.

## The three mechanisms and their timeline

All periods below are **SOURCED (CIC FAQ / law-firm summary) — cross-check against
Cap.652 text**. **CALENDAR vs WORKING days is legally load-bearing** and is encoded
in `sopo_config.py`; the constant names carry the distinction, and the adjudication
timetable runs in *working* days (CIC FAQ Q36).

### 1. Payment

- A claimant serves a **payment claim**; the respondent serves a **payment
  response**. Response period: **30 days (s.20)** — a statutory maximum; the
  contract may specify a shorter period. *(calendar days)*
- Payment deadline: **up to 60 days**; parties may agree earlier. *(calendar days)*
- A **payment dispute** arises (starting the adjudication clock) on any of three
  triggers (CIC FAQ Q27): no response served by the deadline; the respondent
  disputes the claimed amount; or the respondent admits an amount but fails to pay
  it in full by the payment deadline. Failure to serve a response by the deadline
  also **forfeits the respondent's set-off** in adjudication (CIC FAQ Q25).

### 2. Adjudication

- A payment dispute may be referred to adjudication: initiate within **28 days
  (s.24)** of the dispute arising. *(calendar days)*
- If **no — or more than one — Adjudicator Nominating Body (ANB)** is specified,
  serve on the ANB within **8 working days (s.25(3))**.
- **Adjudicator appointed** within **7 working days (s.26(2))**.
- Adjudication exchange (CIC FAQ Q36, working days): claimant **submission within
  1 working day** of appointment; respondent **response within 20 working days**;
  claimant **reply within 2 working days**.
- **Determination** within **55 working days after appointment (s.42(5) / CIC FAQ
  Q36)**. *(working days — day-type resolved in Phase 0c)*
- The adjudicated amount must be paid within **30 days (s.43 / s.42(7))** where
  the adjudicator has not specified a time. *(calendar days)*
- A party may apply to **set aside** a determination within **14 days (CIC FAQ
  Q50)** of it being served. *(calendar days)*
- The determination is **binding on an interim basis** pending final resolution.

### 3. Enforcement

- An adjudicated amount may be enforced through the courts. Court routing turns
  on value: the **HK$3,000,000** threshold separates the **Court of First
  Instance (above)** from the **District Court (below)** under the Rules
  (**Cap.652A**). SOURCED (law-firm summary) — cross-check against Cap.652A text.
- A claimant may also lawfully **suspend or slow work** after giving **5 working
  days' notice** (CIC FAQ Q54). *(Part 4 working-day definition — Saturdays count,
  unlike the adjudication timetable.)*

## Adjudicable disputes — extension-of-time (EOT) carve-out, phase 1

SOURCED (CIC FAQ Q38) — cross-check Cap.652 text. In the current phase,
**time-related / extension-of-time (EOT) disputes are adjudicable for PUBLIC
contracts only**; **private-contract EOT disputes are NOT yet adjudicable**.
Eligibility logic should later surface this as a **'warning'** when a private
contract raises an EOT dispute (advisory, not a hard block).

## What makes a payment claim valid — s.18 content requirements

SOURCED (CIC FAQ Q17) — cross-check Cap.652 text. A valid payment claim must:

1. **be in writing** (`in_writing`);
2. **identify the construction work / related goods & services** the payment
   relates to (`identifies_work`);
3. **state the claimed amount and how it is calculated** (`states_amount_and_basis`).

These three are encoded in `sopo_config.MANDATORY_CLAIM_PARTICULARS`; Stage 02
treats a missing mandatory particular as a **fatal** defect.

## Reference dates and service of notices

> Beyond the scope of the sourced summary — **# UNVERIFIED — confirm with Cap.652
> text/QS**: how **reference dates** are fixed (and any minimum interval between
> claims), and the **permitted methods of serving** claims/notices (and any
> deemed-receipt rules). Keep proof of service regardless — it anchors every
> downstream deadline.

---

### Maintenance

When a value here is verified against the enacted Ordinance, update its tier here
**and** the matching constant in `backend/rules_engine/sopo_config.py` so Layer 1
and Layer 3 stay in sync.
