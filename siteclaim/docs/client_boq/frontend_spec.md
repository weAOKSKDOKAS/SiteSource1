# client_boq — what the backend gives you, and what each screen must therefore do

A wireframing brief. Everything here is read off the code in `backend/client_boq/` and verified
against a real DEMO run of the Harbour Crest Residences set, so the volumes at the end are actual
counts, not estimates. It describes what *is*.

---

## 1. The shape, in one paragraph

One **document set** goes in. Two workflows run over it, strictly in order, separated by two
**human gates**: REVIEW produces a *departure register* (the contract terms we will not accept as
written — a document that goes back to the client), and ESTIMATE produces a *priced offer* (cost
build-up, margin, workbook, letter). The register gate must be closed before anything is scoped;
the scope gate must be closed before anything is priced. The backend enforces both with 409s — the
UI does not get to be lax about this.

The architectural rule underneath every screen: **the AI reads, structures, proposes and drafts.
Deterministic code computes and checks. A human writes every decision value.** This is enforced in
the type system — the model's stage-03 output type (`DepartureProposalSet`) has no status field at
all, so a model *cannot* write a verdict. The frontend's central job is to make that legible: for
every value on screen, who put it there.

---

## 2. The state machine

```
                    ┌──────────────────┐
   files ──────────▶│  set_id created  │  POST /review/run
   project_name     │  register built  │  (s01→s08, one call)
                    └────────┬─────────┘
                             │  register: 35 lines, 17 needing a verdict
                             ▼
                    ┌──────────────────┐
                    │  REGISTER GATE   │  POST /review/approve
                    │  human verdicts  │  {decisions:{item→confirmed|dismissed}, approved}
                    └────────┬─────────┘
                             │  review_approved = true
             409 ◀───────────┤  ("Estimate is gated: the review register … is not approved yet")
                             ▼
                    ┌──────────────────┐
                    │  scope draft     │  POST /estimate/scope
                    │  (AI + injected  │
                    │   confirmations) │
                    └────────┬─────────┘
                             ▼
                    ┌──────────────────┐
                    │   SCOPE GATE     │  POST /estimate/scope/approve
                    │ human statement  │  {amended_summary, approved}
                    └────────┬─────────┘
                             │  scope_approved = true
             409 ◀───────────┤  ("Estimate is gated: the estimate scope … is not approved yet")
                             ▼
                    ┌──────────────────┐
                    │  priced estimate │  POST /estimate/run
                    │  + offer letter  │  {margin_pct, schedule, letter}
                    └────────┬─────────┘
                             ▼
                    workbook .xlsx  ·  letter draft (markdown)
```

Three refusals the UI has to have an answer for:

| Refusal | When | What the screen should already have prevented |
| --- | --- | --- |
| `409` register not approved | `/estimate/scope`, `/estimate/run` | Scope step unreachable until the gate closes |
| `409` scope not approved | `/estimate/run` | Price step unreachable until the scope gate closes |
| `409` citation failed | `/review/approve` when a `citation_failed` line is sent as `confirmed` | Confirm control disabled on that line, with the reason visible |
| `422` | live `/estimate/run` without `margin_pct` + `schedule` | Run control disabled until both are set |

**Reopening.** Both gates take `approved: false`, so both are reversible. The backend does *not*
cascade — reopening the register leaves a stored scope and estimate intact. The UI must therefore
own the invalidation rule: reopening the register drops the scope, estimate and letter downstream
of it, or you get an offer standing on a register nobody has closed.

---

## 3. Two run modes — this affects every long action

`demo_mode()` (env `DEMO_MODE`) changes the *shape of the response*, not just the data:

| | DEMO | Live |
| --- | --- | --- |
| `/review/run` | Runs inline on fixtures, returns `{status:"done", result}` | Returns `{job_id, status:"queued"}`, poll `/review/status/{job_id}` |
| `/estimate/scope` | Inline | Background job |
| `/estimate/run` | Inline, **ignores your schedule and margin** and prices the fixture at 15% | Requires `margin_pct` + `schedule`, background job |
| Uploaded files | Accepted and ignored | Actually parsed |
| Database | Gitignored scratch DB | The real one |

The job envelope is identical for all three (`{job_id, kind, status, stage, error, result, warnings}`),
and `stage` is a human-readable string the backend emits as it goes:

```
review:    ingesting → summarising → matching → scope → program → cashflow → assembling → verifying
scope:     scoping
estimate:  costing → persisting → drafting letter
```

**Design consequence:** a live review is a real wait (it reads every document end to end). Those
eight stage names are the only progress signal that exists — there is no percentage. Whatever the
wireframe does for waiting has to work with a named-step sequence, and the screen must not lie in
DEMO by implying uploaded files were read.

---

## 4. REVIEW, stage by stage — and what each one puts on screen

| Stage | Who decides | What it produces | What that means for the UI |
| --- | --- | --- | --- |
| **s01 ingest** | code extracts, AI structures | `ParsedDocumentSet`: filenames + `clauses[]` each with `clause_id`, `ref`, `heading`, `text`, `source_doc`, `page` | The set identity (`set_id` is a slug of the project name). **The clause bodies are stored but not served** — see §9. |
| **s02 context summary** | AI (draft) | `ContextSummary`: `summary`, `scope_responsibilities`, `obligations`, `client_assumptions`, `interfaces`, `clarifications` | A genuine commercial-risk brief — *and it is never returned by any endpoint*. See §9. |
| **s03 criteria match** | AI proposes → **rule pre-flags** → human verdicts | Departure lines with `criterion_id`, `extracted_value`, `cited_text`, `amendment_proposal`, `rationale`, `proposed_position` | The core of the register. See the rule layer below. |
| **s04 scope alignment** | AI proposes → **rule** decides precedence | Lines tagged `source=scope_alignment`, `kind` ∈ gap / inconsistency / silent_assumption / responsibility_creep / precedence / input_missing | These lines often have **no clause, no extracted value, no proposed position** — only a `rationale`. The row design must degrade to "a sentence and a verdict". |
| **s05 program check** | AI proposes → **code recomputes** | Lines `source=program`, `kind` ∈ duration / sequencing / access / mobilisation / milestone / ld_exposure / program_not_provided | Same shape. `program_not_provided` is a rule-flagged line with no clause at all — a finding about an *absence*. |
| **s06 cash flow** | **pure deterministic, no AI** | `CashflowSection`: `points[]` (period, inflow, outflow, net, cumulative), `negative_periods[]`, `working_capital_peak`, `findings[]`, `assumptions[]` | Not line items — its own section. Plus one `source=cashflow` line when the position is sustained-negative. |
| **s07 register assemble** | code | The one `DepartureRegister` | Everything above folds into a single numbered list. Item numbers are stable and are what `/review/approve` references. |
| **s08 citation verify** | **deterministic lookup** | Mutates lines in place | The anti-hallucination guard. See below. |

### The rule layer (s03) — why some lines are red and others are blue

Exactly **8** of the 28 criteria are numerically checkable, and only those are machine pre-flagged
(`backend/client_boq/rules.py`). The AI supplies an extracted *string*; the rule parses it and
decides. The AI never runs these.

```
TP-03  notice period      < 5 business days
TP-04  LD cap             absent, OR > 10%
PS-01  payment assessment > 20 business days
PS-04  retention          > 5%, OR not released at Practical Completion
PS-05  notice before call on security  < 5 days, OR none
LR-01  liability cap      absent   (adequacy of a present cap is human-judged)
LR-05  cure period        < 7 days, OR none
SQD-05 DLP                > 12 months
```

So a register line's status tells you **who authored it**:

| status | author | meaning |
| --- | --- | --- |
| `rule_flagged` | rules engine | a stated numeric threshold is breached — deterministic, reproducible |
| `candidate` | Claude | a proposed qualitative match; carries drafts, no verdict |
| `uncovered` | criteria match | a clause matching no criterion — surfaced so it isn't lost |
| `unresolved` | criteria match | a criterion no clause answers — an *absence*, not a finding |
| `citation_failed` | citation check | the quote could not be found in the documents |
| `confirmed` / `dismissed` | **the human** | written only by `/review/approve` |

**This mapping is the single most important thing for the wireframe to encode.** Everything else is
layout; this is the product.

### s08 — the citation guard

For every line that cites a clause: does `clause_id` exist in the parsed set, and is `cited_text`
literally contained in that clause (whitespace/case-normalised — string containment, not semantics)?
Either failure sets `status = citation_failed` and writes `citation_note`. Such a line **cannot be
confirmed** until re-reviewed; `/review/approve` returns 409. Unresolved lines carry no clause and
are skipped.

The reason this matters commercially: a register that departs against a clause that does not exist
is one of the worst things you can send a client. The UI should treat this status as categorically
different from "risky" — it is "do not rely on this".

---

## 5. The register payload, exactly as it arrives

`GET /client-boq/review/register/{set_id}` (and the run result) return:

```
ReviewResult
├─ set_id, slice, review_approved
├─ status_counts            {rule_flagged:7, candidate:8, citation_failed:1, uncovered:1, unresolved:18}
└─ register
   ├─ project, package
   ├─ line_items[17]        the ACTIONABLE lines, pre-sorted:
   │                        rule_flagged → citation_failed → candidate → uncovered → confirmed → dismissed
   ├─ unresolved            {count:18, criteria:[{item, criterion_id, clause_area}]}   ← id + area ONLY
   ├─ aligned[2]            criteria the rule checked and PASSED {criterion_id, clause_area, clause,
   │                        extracted_value, why}
   ├─ cashflow              the section, or null
   └─ items[35]             the full canonical list — the item numbers /approve references
```

One `line_items` entry, fully populated (item 1 of the demo set):

```
item              1
clause            "8.3"                    ← may be ""
criterion_id      "TP-04"                  ← may be ""
category          "Time & Progress"        ← may be ""
clause_area       "Liquidated Damages"     ← may be "" (then `kind` is the label)
extracted_value   "Aggregate liquidated damages: uncapped (no aggregate cap)"   ← often ""
cited_text        "no cap on the aggregate amount"                              ← often ""
amendment_proposal "Cap aggregate liquidated damages at 10% of the Subcontract value."
rationale         "Uncapped LDs expose the Subcontractor to unlimited delay damages…"  ← ALWAYS present
proposed_position "Liquidated damages capped at 10% of the Subcontract value."   ← often ""
status            "rule_flagged"
source            "criteria"               ← criteria | scope_alignment | program | cashflow
kind              ""                       ← the finding sub-type for s04/s05/s06 lines
rule_ref          "TP-04"
citation_note     ""
client_response   ""    ← negotiation columns, always empty today (nothing writes them)
contractor_response ""
register_status   "open"                   ← "closed" once a verdict lands
```

**The row design has to survive sparsity.** Of the 17 actionable lines in the demo set:

- 12 cite a clause · 5 do not
- 12 carry a quote · 5 do not
- 9 carry a proposed position · 8 do not
- **17 carry a rationale** — the only field you can always rely on

So the row's spine is `rationale` + `status` + `verdict`. Clause, quote, value and proposed position
are enrichments that appear when present. A design that leads with the clause reference will have
five broken-looking rows.

---

## 6. The register gate

```
POST /client-boq/review/approve
  { set_id, decisions: { 1:"confirmed", 2:"dismissed", … }, approved: true }
```

- `decisions` is sparse — omitted items are left untouched. So partial approval is *possible* at the
  API level. Whether the UI permits closing with lines still undecided is a product decision, not a
  backend one.
- Each verdict also sets that line's `register_status` to `"closed"`.
- A `citation_failed` line sent as `confirmed` → **409**, naming the item.
- The response is only `{set_id, review_approved}` — to see the new line statuses you must re-read
  the register.

**What confirming actually does downstream:** each confirmed departure's `proposed_position` is
injected verbatim into the estimate scope as an assumption, and then verbatim into Appendix A of the
offer letter. Confirming is not bookkeeping — it changes the price and the document you send. The
wireframe should carry that weight at the moment of the click.

---

## 7. ESTIMATE, stage by stage

### Step 1 — scope (`POST /estimate/scope`, then `/estimate/scope/approve`)

`ScopeReviewResult`: `summary`, `notes[]`, `clarifying_questions[]`. Each note is
`{kind, text, source}` where `kind` ∈ inclusion / exclusion / ambiguity / conflict / assumption, and
**`source` is the tell**:

- `source: "draft"` — Claude wrote it from the documents
- `source: "register"` — **code** injected it, verbatim, one per confirmed departure. Dismissed
  departures are never carried.

In the demo set: 22 notes = 7 drafted + 15 register-injected. The register-sourced ones dominate by
count, so a design that mixes them into one list buries the drafted scope reading.

The gate takes an optional `amended_summary`. If non-empty it **becomes the scope of record** and
wins over Claude's draft (which is retained). `summary_of_record()` returns the amendment or the
draft. So the gate is an edit box, not a checkbox — the human either accepts Claude's sentence or
writes their own.

### Step 2 — price (`POST /estimate/run`)

Deterministic spine, no AI: `s02 normalise → s03 cost build-up → s04 indirects → s05 validate → totals`.

**Direct items** price from resource lines. Each line resolves a rate from `rates.csv` by
`resource_ref`, or an `inline_rate` override, or nothing:

```
qty ÷ productivity = hours ;  hours × rate = amount     (when productivity is given)
qty × rate = amount                                      (otherwise)
rate_source ∈ "csv" | "inline" | "missing"               ← "missing" costs the line at ZERO
```

Every `CostLine` carries `qty, unit, productivity, hours, rate, rate_source, amount` — i.e. the
backend deliberately returns the full working, not just the total. That is an invitation the UI
should accept: an estimator can check the machine by hand.

**Indirect items** price from a basis, and the backend returns a hand-checkable `detail` string:

```
lump           → "lump sum = 120000.0"
per_week       → "8000.0 per week × 20.0 weeks = 160000.0"
pct_of_direct  → "2.5% × direct 5652600.0 = 141315.0"
```

**Validation flags** (`s05_validate.py`) — surfaced, never blocking, never a verdict:

| kind | trigger |
| --- | --- |
| `missing_rate` | no rate on file for a `resource_ref` → costed as 0, price understated |
| `zero_or_negative_qty` | a line contributes nothing |
| `empty_activity` | a direct activity with no resource lines |
| `rate_outlier` | an inline rate deviates >50% from the CSV rate (benchmark only) |
| `unclassified_item` | `category` is neither `direct` nor `indirect` → **never costed, never guessed** |

**Totals.** `price = cost × (1 + margin_pct/100)`, `margin_amount = price − cost`. There is
deliberately **no profitable/not-profitable verdict and no threshold on margin** — it is a readout.
The human states `margin_pct`; nothing suggests it.

### Step 3 — deliverables

- `GET /estimate/{set_id}/workbook` → `.xlsx`, regenerated from the persisted estimate every time
  (WBS · Resources · one sheet per activity · Indirect Costs · Flags). Every figure equals the
  estimate exactly.
- `GET /estimate/{set_id}/letter` → the offer letter **draft**, as `markdown` plus its structured
  pieces. The authorship split is explicit in the data:

| Injected by code | Drafted by Claude |
| --- | --- |
| `price` / `price_str` | `intro` |
| `pricing_schedule[]` (one row per direct activity) | `inclusions[]`, `exclusions[]` |
| `meta` — project, client, ref, date, validity | `appendix[]` entries with `source: "draft"` |
| `appendix[]` entries with `source: "register"` — confirmed departures, verbatim | |

Demo set: 18 appendix items = 15 from the register + 3 drafted. Nothing sends the letter.

---

## 8. The five screens — data in, decision out

### 1 · Documents
**Has:** nothing yet — a project name and a file list.
**Wants:** `set_id` back, and a way to reopen a set reviewed earlier (registers persist; screen
state does not).
**Must say honestly:** in DEMO, that the uploaded files are not what gets read.
**Waiting state:** the eight named review stages, no percentage, potentially minutes.

### 2 · Register — *the screen the section exists for*
**Has:** 17 lines needing a verdict, 18 unresolved criteria, 2 aligned, a 9-period cash-flow curve.
**Wants:** a verdict on every actionable line, then the gate.
**Non-negotiable:** authorship legible per line (rule / Claude / citation check / you); a failed
citation visibly different and non-confirmable; no verdict pre-filled — a register that opens with
answers already in it is the exact failure this module exists to prevent.
**Open questions for you:** does the source clause text sit next to the finding (needs §9)? Do the
18 unresolved criteria get equal weight or a footnote? Is the cash-flow curve on this screen or its
own?

### 3 · Scope
**Has:** one editable statement, 22 notes across 5 kinds and 2 authorships, 3 questions for the client.
**Wants:** the statement approved — amended or as drafted.
**Non-negotiable:** register-injected notes distinguishable from drafted ones, and the fact that
what you approve is what the price and the letter are built on.

### 4 · Price
**Has:** the rate book (21 rows), and after a run: 5 activities / 9 cost lines with full traces,
3 indirects with their arithmetic, 5 flags, 1 unclassified item, totals.
**Wants:** a schedule and a margin, then a run.
**Non-negotiable:** the screen must not compute. Backend arithmetic is the only arithmetic — a
figure the UI invented is a figure nobody can defend. Show the trace, not just the total.
**Open question:** the schedule editor is the heaviest input surface in the section. Full editor, or
upload/paste a schedule, or defer it?

### 5 · Offer
**Has:** a 4,148-character markdown letter, an 18-item appendix split by authorship, a 5-row pricing
schedule, an `.xlsx` link.
**Wants:** nothing — it is the end. Read, copy, download.
**Non-negotiable:** the letter is a draft under the company's name; which sentences a model wrote
must not be a guess.

---

## 9. What the backend holds but does not serve

Each of these is stored today and would need a small read endpoint. Worth knowing before you
wireframe, because two of them unlock whole layouts:

| Data | Where it lives | Cost to expose | What it would unlock |
| --- | --- | --- | --- |
| **Full clause text** | `client_boq_document_sets.parsed_json` → `clauses[].text` (+ `heading`, `source_doc`, `page`); `store.load_parsed()` exists | ~8 lines | Reading a finding *against the clause it cites* — the contract on one side, the finding on the other |
| **Context summary (s02)** | `client_boq_document_sets.summary_json`; `store.load_summary()` exists | ~8 lines | A real "what you are dealing with" brief before the register: responsibilities, obligations, client assumptions, trade interfaces, things to clarify. Computed on every run and currently invisible. |
| **Per-line citation checks** | Computed in s08, applied to status, then **discarded** | Needs persisting first | A citation audit view. Today only `citation_note` survives on the failed line. |
| **List of document sets** | Rows exist in `client_boq_document_sets`; no query | ~10 lines | A "recent sets" landing screen instead of typing a `set_id` |
| **Criteria library** | `docs/client_boq/review_criteria.md`, parsed at runtime | ~8 lines | Showing what the 28 criteria *are* — currently the 18 unresolved arrive as bare ids |

---

## 10. Real volumes — wireframe against these

From the Harbour Crest Residences set (DEMO), which is representative:

```
DOCUMENT SET
  criteria library      28 criteria (+1 placeholder), 8 numerically checkable
  criteria categories   Time & Progress 6 · Payment & Security 6 · Scope/Quality/Design 6
                        Liability & Risk 6 · Site & General Admin 4

REGISTER              35 items total
  needing a verdict    17     rule_flagged 7 · candidate 8 · citation_failed 1 · uncovered 1
  by check             criteria 9 · scope_alignment 5 · programme 2 · cash flow 1
  unresolved criteria  18     (id + clause area only)
  aligned / passed      2
  field coverage       12/17 cite a clause · 12/17 quote · 9/17 propose a position · 17/17 rationale

CASH FLOW              9 periods · 7 cash-negative · peak funding HK$300,000 · 2 findings · 2 assumptions

SCOPE                 22 notes (7 drafted + 15 injected from the register) · 3 client questions

ESTIMATE               5 activities · 9 cost lines · 3 indirects · 1 unclassified · 5 flags
  direct               HK$5,652,600
  indirect             HK$421,315
  cost                 HK$6,073,915
  margin @ 15%         HK$911,087.25
  price                HK$6,985,002.25

RATE BOOK             21 rows · labour / plant / material / subcontract / productivity

LETTER                 4,148 chars markdown · 18 appendix items (15 register + 3 draft)
                       5 pricing rows · 4 inclusions · 5 exclusions
```

Density notes for layout: the register is the only screen with real length (17 rows of 3–6 lines
each, plus a 18-chip block and a chart). Scope is medium. Price is long only *after* a run. Offer is
one long document in a scroll container. Nothing here is a hundred-row table — this is a
reading-and-deciding tool, not a spreadsheet.

---

## 11. Endpoint reference

```
REVIEW
  POST /client-boq/review/run            multipart: files[], project_name → JobState<ReviewResult>
  GET  /client-boq/review/status/{job}                                   → JobState
  GET  /client-boq/review/register/{set}                                 → ReviewResult
  POST /client-boq/review/approve        {set_id, decisions, approved}   → {set_id, review_approved}
  GET  /client-boq/gate/{set}                                            → {set_id, review_approved}

ESTIMATE
  POST /client-boq/estimate/scope         {set_id}                        → JobState<ScopeResult>   409
  POST /client-boq/estimate/scope/approve {set_id, amended_summary, approved} → ScopeGateState
  GET  /client-boq/estimate/scope/{set}                                   → ScopeResult
  POST /client-boq/estimate/run           {set_id, margin_pct, schedule, letter} → JobState<EstimateResult>  409 409 422
  GET  /client-boq/estimate/status/{job}                                  → JobState
  GET  /client-boq/estimate/{set}                                         → EstimateResult
  GET  /client-boq/estimate/{set}/workbook                                → .xlsx
  GET  /client-boq/estimate/{set}/letter                                  → LetterResult

RATE BOOK
  GET  /client-boq/rates                                                  → RateRow[]
```

TypeScript mirrors of every shape above are already written and unchanged by the redesign:
`frontend/src/clientboq/types.ts`, with the transport in `frontend/src/clientboq/api.ts`.
