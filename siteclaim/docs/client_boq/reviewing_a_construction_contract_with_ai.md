# Reviewing a Construction Contract with AI

A step-by-step workflow for turning a construction contract plus its project documents into a defensible departure register, using AI in a way that reduces hallucinations and stays consistent. This covers contract review only — not estimating the works.

This is a general workflow assembled from the source material, combined with the workflow slides. It is tool-agnostic — any capable AI chat interface with project/file support and a citation-checking tool can run it.

---

## Premise

Reviewing a construction contract does not require a law degree. At its core it is a large pattern-matching exercise: take a 70-page document and map every clause against a known set of acceptable positions. That kind of repetitive matching is something AI does well.

The parts AI does not replace are the human parts of contracting — negotiating, reading relationships, judging business risk, and holding a commercial position. Those still sit with a person. What AI handles is the mechanical review that most smaller contractors skip because they cannot justify a lawyer's time.

Intended use case: smaller or cash-strapped contractors who would otherwise sign contracts without reviewing them properly. If the project is large enough to justify a contract lawyer, use one. This workflow is the affordable middle ground, not a replacement for an experienced commercial manager.

---

## Why not just dump the contract into ChatGPT

Uploading a contract into a chatbot and asking it to flag risky clauses does work reasonably well, and adding a short project-specific prompt makes it better. The workflow below exists because that naive approach carries several failure modes.

- Missing project context. The contract's scope is defined by more than the contract document — scope of works, drawings, addendums, meeting minutes, emails, and other correspondence all shape it. A bare contract upload sees none of that.
- Context rot. As the volume of context grows, the model becomes less reliable and more likely to hallucinate. Dumping a contract plus dozens of drawings into one chat makes this worse (and some chat tools cap uploads, e.g. around 10 drawings at once).
- Variability and inconsistency. The same contract run through the same chatbot returns a slightly different answer each time, and not in a fixed format you can work with.
- No sense of your risk appetite. Some contractors accept a 5% liquidated-damages cap; others accept 15–20%. It depends on margin and market. A generic review does not know your acceptable positions.
- Unreliable workflow. There is no way to confirm the scope of works was actually checked, or that documents were read rather than skimmed or hallucinated.
- Hallucinated clause references. The output might attribute a term to "clause 34.4" when 34.4 is actually something else. Submitting departures against clauses that do not exist is a serious credibility problem with a client.
- Weak output structure. Loose dot points still have to be translated into a usable departure register by hand.

The takeaway framing from the slides: prompting gives you answers; a system gives you confidence. The goal of everything below is to turn one-off prompting into a repeatable system.

---

## The goal: a departure register

Every check in this workflow feeds one output — a departure register you can be confident in, where the contract terms are correctly identified and the proposed departures are ones you actually accept.

Departure register structure (from the worked example):

Header fields:
- Project
- Contract Type
- Package
- Subcontract Reference
- Subcontractor Name
- Submission Date

Line-item columns:
- Item
- Clause
- Subcontractor / Supplier Amendment Proposal
- Rationale / Reason for Amendment
- Client Response
- Contractor Response
- Status (Open / Closed)

Example row (illustrative, from the sample register):

| Item | Clause | Amendment Proposal | Rationale | Client Response | Contractor Response | Status |
|------|--------|--------------------|-----------|-----------------|---------------------|--------|
| 1 | 4.8.6 | 14-day payment term in place of the standard 30 days | Improves cash flow to support subcontractor payments | Open to revised terms with early-payment discount | 14-day terms approved with 2% early-payment discount | Agreed |
| 2 | 9.9 | Cap liquidated damages at 5% of contract value | Keeps commercial risk proportionate to project size | Agrees to cap LDs at 7.5% | LDs capped at 7.5% | Agreed |

---

## Tooling notes

- Run the review inside a Claude project. Claude Opus tends to be noticeably stronger for this task than the ChatGPT models. A single project holds the set of chats; tender documents and the acceptable-terms library are uploaded once as project files and reused across prompts.
- The context summary is done as a separate step from the contract review — the two are not combined into one prompt.
- A second tool, Google's NotebookLM, is used at the end to verify citations (see the hallucination-reduction section).

---

## Setup phase (Steps 1–3): build the project context

These three steps are done once per project and stored as project context. They give every later check something structured to work from.

### Step 1 — Establish Context

Goal: make sure the AI understands what is being built and what drives commercial risk, in the most succinct form possible.

Inputs:
- Drawings
- Specifications
- Scope of Works
- Addendums & clarifications
- Meeting minutes
- Emails / correspondence

Method: use a summarising prompt to condense the full project document set into a structured requirements summary. If you have drawings and other bulky material that cannot fit in one prompt, run a sequence of summarising prompts and condense them down first. The output is a compact commercial-risk summary the contract review can be based on, rather than forcing the model to read raw documents during the review itself.

Prompt (example):

> You are an expert construction contract manager.
>
> I am a general contractor tendering to deliver a major apartment complex.
>
> I am providing you with a full set of project documents including drawings, specifications, scope of works, addendums, meeting minutes and correspondence.
>
> Task: Review these documents and generate a structured project summary focused only on contractual and commercial risk (price + terms).
>
> Specifically identify:
> - Scope responsibilities that impact price
> - Any testing, inspection, certification or permit obligations
> - Client assumptions or constraints that affect risk
> - Interfaces with other trades
> - Items that could reasonably require clarification or exclusion
>
> Ignore generic descriptions. Focus only on information that would affect pricing, program, or contractual exposure.
>
> Return a structured summary with references to key documents and terms.

### Step 2 — Define Acceptable Terms

Goal: tell the AI what is acceptable for your business.

Inputs:
- Your standard commercial positions, or
- Your previous departures

Store this in the project context. Every contracting business should have such a library. If you can afford it, having a construction contract lawyer help build this set once is worth it. The set below is an example acceptable-terms library, grouped by area, with each row giving the acceptable position, why it matters, and the red flag to watch for.

#### Time & Progress

How project duration impacts profitability and risk.

| Clause Area | Acceptable Commercial Position | Why It Matters | Red Flag |
|-------------|-------------------------------|----------------|----------|
| Program & Float | Contractor owns the float; dates are achievable. | You need buffer for your own delays, not the client's. | "Principal owns all float" or "Time is of the essence." |
| EOT Entitlement | Broad causes (neutral events, weather, acts of God). | Without EOTs, you pay LDs for things you cannot control. | "At sole discretion of the Superintendent." |
| Time Bars | Minimum 5–10 business days for notices. | Administrative gotchas that strip your right to claim. | 24–48 hour notice periods. |
| Liquidated Damages | Capped at 5–10% of contract; genuine pre-estimate. | Prevents unlimited financial bleeding for delays. | Uncapped LDs, or LDs that act as a penalty. |
| Delay Costs | Recovery of prolongation costs for client delays. | Staying on site longer costs money (overhead/rentals). | "Time-only EOT" with no cost recovery. |
| Suspension | Entitlement to time + cost for client-ordered stops. | Idle labour and plant are margin killers. | Suspension without cost relief. |

#### Payment & Security

Focus on cash-flow projections.

| Clause Area | Acceptable Commercial Position | Why It Matters | Red Flag |
|-------------|-------------------------------|----------------|----------|
| Payment Claims | Monthly claims; alignment with SOPA legislation. | Cash flow is the lifeblood of construction. | Long assessment periods (>20 business days). |
| Set-Off Rights | Only for quantified and notified debts. | Prevents the client holding your cash without cause. | "Unilateral right to set off any amount." |
| Pay-When-Paid | Strictly prohibited (per SOPA). | You should not bear the risk of the Principal's insolvency. | Any clause linking your payment to a third party. |
| Security (Retention) | 5% cap; 2.5% released at Practical Completion. | Ties up your working capital for 12+ months. | >5% retention, or no release at PC. |
| Recourse to Security | Notice required (e.g. 5 days) before calling BGs. | Protects against ambushes on your bank guarantee. | "Right to call security at any time without notice." |
| Final Certificate | Clear process to finalise the account after DLP. | Provides financial closure and certainty. | No mechanism to issue a Final Certificate. |

#### Scope, Quality & Design

Focus on avoiding scope creep and building what you priced.

| Clause Area | Acceptable Commercial Position | Why It Matters | Red Flag |
|-------------|-------------------------------|----------------|----------|
| Document Priority | Contract → Scope → Drawings → Specs. | Resolves contradictions in documents (general vs specific). | "Contractor to provide everything necessary" (silent scope). |
| Design Risk | No "fitness for purpose" unless specifically priced. | Fitness for purpose is often excluded by professional indemnity. | Silent performance warranties in trade packages. |
| Variations | Valuation by agreed rates or cost + margin. | Ensures you are not forced to work at a loss on changes. | "Principal sets rates unilaterally." |
| Latent Conditions | Cost + time relief for unknown site conditions. | You cannot price what you cannot see (e.g. rock/asbestos). | "Contractor bears all risk of site conditions." |
| Defects Liability | 12 months max; rectification only of repaired items. | Long DLPs are effectively an unpriced maintenance period. | DLP restarts for the whole works after a minor repair. |
| Warranties | Match manufacturer warranties; avoid "life of building." | Over-warranting creates a liability that outlives your business. | "Fitness for purpose" as a blanket warranty. |

#### Liability & Risk Allocation

Focus on the catastrophic risks that could end a company.

| Clause Area | Acceptable Commercial Position | Why It Matters | Red Flag |
|-------------|-------------------------------|----------------|----------|
| Liability Cap | Capped at contract value or insurance limit. | Protects your business from company-ending claims. | Uncapped liability. |
| Indemnities | Proportionate (only for your negligence). | Standard insurance will not cover you for others' fault. | "Indemnify the Principal regardless of cause." |
| Consequential Loss | Expressly excluded (loss of profit, revenue, data). | These losses are unpredictable and impossible to price. | "Including but not limited to economic loss." |
| Proportionate Liability | Legislation must apply; do not contract out. | Prevents you being 100% liable for a 5% mistake. | "Parties agree to contract out of Part IV of the Civil Liability Act." |
| Termination | Cure period required (e.g. 7–14 days) for default. | Prevents being kicked off site for minor, fixable issues. | "Immediate termination" for minor breaches. |
| Termination for Convenience | Must include loss of profit on uncompleted work. | Compels the client to think twice before walking away. | "No compensation" for termination for convenience. |

#### Site & General Admin

Focus on day-to-day site operations and statutory compliance.

| Clause Area | Acceptable Commercial Position | Why It Matters | Red Flag |
|-------------|-------------------------------|----------------|----------|
| Access & Possession | Defined dates; exclusive or co-ordinated access. | Lack of access = delay. You cannot work if you cannot get in. | "Access at the Principal's convenience." |
| WHS / Principal Contractor | Clear designation; power to control the site. | You bear the safety risk, so you must have the authority. | Named "PC" but denied control of site access. |
| Dispute Resolution | Mandatory mediation/conference before litigation. | Keeps lawyers out of the room for as long as possible. | "Arbitration only," or no interim dispute path. |
| IP Rights | Contractor retains background IP (your systems). | Prevents the client owning your proprietary methods. | "Blanket assignment of all IP to the Principal." |

The slides also flag an "Other Key Terms" grouping beyond the five above, which you would extend with any terms specific to your business.

### Step 3 — Specify the Output Template

Goal: fix the structure of the output and give an example.

Inputs:
- The departure register / output template
- An example of a completed review

Use an Excel departure register as the template. Giving a worked example is treated as best practice because it teaches the model your negotiation style and phrasing, though it is not strictly required. Store the template and example in the project files, and update the system instructions so any departures are always returned in this format.

---

## Review phase (Steps 4–7): run the checks

With context, acceptable terms, and output template in place, run these checks. Each one outputs into the departure register.

### Step 4 — Scope Alignment Check

Goal: confirm the contract scope matches what you priced. Getting the scope of works right resolves roughly 90% of contract problems, so this runs first.

Inputs:
- Contract scope (the key documents that define scope)
- Scope summary
- Letter of offer
- Tender clarifications
- Estimate

If the scope documents are too large or too many, run the Step 1 summarising prompt to break them down first.

Prompt (example):

> Review the contract scope of works against:
> - The letter of offer
> - Tender clarifications
> - My construction estimate
> - Project scope summary
>
> Task: Identify any scope gaps, inconsistencies, silent assumptions, or responsibility creep. Confirm whether the order of precedence correctly protects the priced scope — e.g. if I specified relying on information provided by the client, does that match the contract order of precedence?
>
> Output all issues in the scope departure register.

The intent is to catch scope that appears in the contract but is not in your estimate or letter of offer. Anything not priced in the estimate and not excluded in the letter of offer should be flagged so the contract scope aligns with what you actually priced.

### Step 5 — Program & Constructability Alignment

Goal: check whether the contract timing is actually achievable.

Inputs:
- Program
- Scope requirements
- Milestones

Prompt (example):

> Review the project program in the context of the defined scope.
>
> Task: Identify:
> - Unrealistic durations or sequencing
> - Access or dependency risks
> - Number of mobilisations implied by the scope
> - Whether client milestones sit on the critical path
>
> Highlight any program risks that materially increase LD exposure or delay risk.

Watch particularly for milestones that depend on the client but are not stated in the contract, and for a mobilisation count that does not match the scope — both are common sources of unrecovered cost from a poorly written program. Confirm the liquidated-damages exposure implied by the program is correct.

### Step 6 — Cash-Flow & Commercial Reliability

Goal: avoid projects that are profitable on paper but cash-negative in practice.

Inputs:
- Payment terms
- Retention
- Program logic
- Estimate / subcontractor quotes (supply-chain payment terms)

Prompt (example):

> Using the contract payment terms and the project program, create a high-level cash-flow profile for the project.
>
> Task: Identify periods of negative cash flow, working-capital risk, or delayed recovery. Suggest commercial adjustments (terms or pricing allowances) required to manage cash-flow exposure.

Also feed in operational detail like how frequently you pay labour and your payment terms on materials. With that, the model produces a workable cash-flow forecast showing where you go cash-positive or cash-negative, and you can adjust the payment schedule and terms to push toward cash-neutral or, ideally, cash-positive. This is an easy way to see what is actually driving the cash position on a project that would otherwise be tedious to model by hand.

### Step 7 — Contract Terms Comparison & Redrafting

Goal: systematically compare the contract against your standards. This is the main pattern-matching exercise.

Inputs:
- Draft contract
- Acceptable terms library

Prompt (example):

> Compare the draft contract against my acceptable contract terms library.
>
> Task: For each clause that deviates:
> - Cite the exact clause reference
> - Explain the commercial risk
> - Propose either:
>   - Revised wording, or
>   - A required pricing / risk response
>
> Present all findings in a departure register format.

Beyond matching against your standard terms, this step also flags terms in the contract that are not covered by your standard library at all, so nothing unfamiliar slips through. The sample project's tender package was small (~700 KB), so the whole file could be uploaded and checked in one pass. For a large tender package, run the summarising step first — more documents and more context in a single prompt raise the chance of a bad or hallucinated result.

The finished register lists each clause, its reference, the contract's current position, and the requested departure. For example: liquidated damages currently at $1,000/day with no cap, with a requested cap of 10% of contract value; a time bar currently at 5 business days, with a request to extend it to 10 days.

---

## Reducing hallucinations

Two techniques run alongside the prompts to keep the output trustworthy.

### Convert files to markdown first

The more work a single prompt has to do — extracting from Excel, reading a PDF, reasoning, and drafting all at once — the higher the chance of a hallucination. When the review runs, you can see it executing scripts just to extract information from the Excel files, which is work that competes with the actual review.

To reduce that load, do the conversions as separate upfront steps: convert the PDF contract to markdown in one prompt, convert your Excel departure-register template to markdown in another, then run the review against the clean markdown. Each conversion strips out work the review prompt would otherwise carry, lowering the hallucination risk.

### Verify citations with NotebookLM

NotebookLM is a Google AI tool built for studying, but it works well for contract managers because every answer it gives is returned with a citation back to the source document. Upload the tender documents, and any question is answered with a pointer to the exact place in the document — for example, asking for the tender submission date returns a citation to the closing date (23 April) rather than a free-text guess.

The verification workflow after the register is generated:
1. Download the generated departure register and open it.
2. Copy it into NotebookLM alongside the contract/tender documents.
3. Ask it to check that the cited clauses are correct against the documents.

Done this way, NotebookLM goes through each clause in the register, confirms the references match the tender documents, and reports whether the departure table is factually accurate with correctly pinpointed clauses. Submitting a register with departures against clauses that do not exist is one of the worst outcomes with a client, so this citation check is the safeguard against it. You should still spot-check yourself; this is a fast double-check, not a substitute for your own review.

---

## Limitations

- This will not match an experienced commercial manager, especially for the negotiation itself.
- AI handles the review and pattern-matching; it does not replace judgement on relationships, business risk, or how hard to push a commercial position.
- The strong use case is smaller contractors who otherwise would not review contracts at all for lack of budget or time. For large or high-stakes contracts, a contract lawyer is still the right call.
