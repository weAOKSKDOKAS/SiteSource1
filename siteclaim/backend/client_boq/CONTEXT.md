# CONTEXT.md — client_boq module (dev map)

> Read this to orient inside the module. It is the local map; the stage files are the
> work. Reference docs live in `siteclaim/docs/client_boq/`.

## What this module is

A **client→BOQ** capability that sits *beside* the procurement pipeline, not inside it.
The client (main contractor) hands over a tender/contract document set; the module runs
three **sequential** workflows over it:

0. **INGEST** — turn the uploaded binder into addressable parts: read its structure,
   propose a split, take a human's approval of that split, cut the pages, and write an
   interpreted context card for each part.
1. **REVIEW** — read the parts, check them against a criteria library, and produce a
   departure register a human approves.
2. **ESTIMATE** — *after review approval*, build up the cost from the same document
   context and support a profitability read.

They are sequential and share one parsed-document store, with a human gate between each:
ingest runs first and stops at the **manifest gate**; review runs over the approved parts
and stops at the **review→estimate gate**; estimate then runs behind its own scope gate.

Ingest exists because the review could not survive a real tender. A binder arrives as one
400-page PDF; the pre-ingest path concatenated every uploaded document into a single
prompt against an 8,000-token output ceiling, while `extract_document` silently stops
reading at page 200. Splitting first turns one impossible call into a dozen ordinary ones,
and gives every clause a part and a page range to cite.

## The one principle (carried from the main app)

The LLM **reads, structures, proposes, and drafts** — it never writes a decision value.
Every price, verdict, confirmed match, and route comes from deterministic math, a rule,
or a human gate. See `siteclaim/docs/client_boq/client_boq_layer_mapping.md` — it is the
authoritative task→bucket mapping; do not re-derive it.

## The ten locked v1 decisions

1. **Quantities are given** (from a BOQ or manual entry). No drawing take-off in v1.
2. **Rates from a hand-editable CSV** behind `rates.py` — the seam that later swaps to a
   company DB. No DB-backed rates in v1.
3. **Criteria breach:** the rule layer pre-flags *only* the numeric criteria in the
   threshold table of `review_criteria.md`; everything else is an AI-proposed candidate.
   The verdict on every departure is a **human gate**. The AI never writes breach/no-breach.
4. **Review gates estimate:** the estimate endpoints refuse to run until the review
   register for that document set is human-approved.
5. **The split is proposed, never assumed.** Deterministic inspection reads the document's
   own structure and the AI refines it, but the cut is performed by code against a
   validated manifest, and a human approves that manifest first. A document whose
   structure cannot be read is **not** a failure: it degrades down a four-rung confidence
   ladder to "one part, split it by hand" and still ingests.
6. **Nothing is ever destroyed.** A correction or an addendum APPENDS a revision to a part;
   Rev 0 survives Rev 1 and stays readable. The operative revision is derived (the highest
   `rev`), never a stored flag. A superseded revision can be opened and compared but is never
   priced — you bid the current documents. An addendum's own change table is **advisory**:
   the real ND/2025/04 addendum states its remarks are "neither exhaustive nor guaranteed to
   be accurate", so the replacement pages are the authority and the gate shows both.
7. **A revision reopens the verdicts that depended on it.** When an addendum rewrites a
   clause the register already has a verdict on, that verdict is cleared and flagged for
   re-review. An approval of wording that no longer exists is how a stale departure schedule
   reaches a client.
8. **An open query does not block pricing.** `query` is the third human verdict; a queried line
   stays open and the estimate still runs. The submission deadline does not move because the
   client has not replied — the reference tender's TC1 alone carried 17 questions answered in
   stages. The forcing function is the **freeze** gate, where every unanswered query must become
   an answer or a stated priced assumption. Because nothing blocks, the open-query count is
   carried on the gate state and must stay visible.
9. **Qualifying a tender is a risk, so the outputs are internal by default.** Both reference
   tenders state that any qualification "may cause the tender to be disqualified" (ND/2025/04
   GCT 4; CIC 4.26). The Departure Schedule and Letter of Qualifications are therefore working
   documents first; a submission version is opt-in and quotes that clause as a warning. Ingest
   detects the rule and flags it on the set, because knowing on day one means routing problem
   clauses to RFIs before the cut-off instead of accumulating departures you cannot safely send.

10. **The freeze gate refuses on an unowned guess, never on an open question.** The scope of record
    is built line by line: each carries where it came from, whose words it is in (`ai` / `user`), and
    — for a line standing in for an answer the client never gave — whether a person accepted it.
    Editing a line always stamps it `user`; you edited it, you own it. Approving the scope is refused
    while any pre-filled fallback is unaccepted, because that would put a model's suggestion behind a
    price with nothing recording that anyone agreed to it. What does **not** block is the open query
    itself (decision 8) — it stays open, counted, and visible after the freeze. The UI disables the
    button and names the lines, so the 409 is a backstop rather than the normal path.
    Scope *sources* are derived on every read from the register, the RFI store and the change log —
    never stored, or they would go stale behind a changed verdict.

(Note: the original "temperature 0" idea was dropped — `llm_client` exposes no
temperature and is chassis. Consistency comes from fixed prompts, strict Pydantic
schemas, the corrective-JSON retry, and DEMO fixtures.)

## A rule for every AI stage: measure first, then decide whether the fixture applies

**A DEMO fixture must never be returned for input the stage could not actually read.**

This bit us once, in `ingest/s02_interpret.py`. The stage short-circuited to its fixture at the
top of the function, before checking whether the part had a text layer — so a scanned part came
back with a confident, plausible summary claiming it had been read. In DEMO every scan looked
readable, the honest-degradation path was never exercised, and the offline demo quietly
fabricated content for pages nobody had seen. That is the single failure mode the interpret
stage exists to prevent.

The shape to follow when writing a new AI stage:

```python
text = <deterministic read of the input>      # measure FIRST, in every mode

if demo_mode():
    if not text.strip():
        return <honest "not read" result>      # the fixture does not apply here
    return client.complete_json(..., demo_fixture=DEMO_FIXTURE, ...)
```

The general principle: **a measurement outranks a fixture, and it outranks a model proposal.**
The same rule is why `pdfops.mark_scanned` is re-applied after the planning call and after a
human edits the manifest — the planner may rename, merge and split parts, but it may not decide
whether a page has a text layer.

## Stages and their buckets

Bucket key: **Det** = deterministic · **Rule** = rule-based · **AI** = AI-judgment (draft
only) · **Gate** = human approval.

### INGEST (`ingest/`) — the front door
| Stage | File | Bucket |
| --- | --- | --- |
| Inspect structure | `pdfops.py` | Det (outline, text coverage, confidence ladder) |
| Plan the split | `s01_plan_split.py` | AI propose → Det validate (bounds/gaps/overlaps) |
| — | | **Gate**: `/ingest/manifest/approve` |
| Cut the pages | `run.py` | Det (zero model calls, so re-splitting is free) |
| Interpret each part | `s02_interpret.py` | AI (per part; a failure is a flagged card) |
| Receive an addendum/correction | `s03_map_changes.py` | AI propose (which parts it supersedes) |
| — | | **Gate**: `/ingest/changes/approve` |
| Apply revisions | `run.py` | Det (append a revision; nothing is overwritten) |
| Revision history (.xlsx) | `history_workbook.py` | Det |

### REVIEW (`review/`)
| Stage | File | Bucket |
| --- | --- | --- |
| Ingest document set | `s01_ingest.py` | Det (extract) + AI (structure), per part when split |
| Context summary | `s02_context_summary.py` | AI |
| Criteria match | `s03_criteria_match.py` | AI propose → Rule pre-flag → **Gate** verdict |
| Scope alignment | `s04_scope_align.py` | AI propose → Rule (precedence) |
| Program check | `s05_program_check.py` | AI propose → Det (recompute) |
| Cash-flow | `s06_cashflow.py` | Det |
| Register assemble | `s07_register.py` | Det (template fill) |
| Citation verify | `s08_citation_verify.py` | Det (parse lookup + physical locate) |

### RFI (`rfi/`) — the conversation with the client, running alongside
| Stage | File | Bucket |
| --- | --- | --- |
| Raise a query | `router.py` | **Gate** (a human asks; `query` is the third verdict) |
| Batch into a letter | `rfi/letter.py` | Det (questions verbatim) + AI (covering prose only) |
| Record the answer | `router.py` | Det |
| Overtake on amendment | `store.overtake_rfis_for_parts` | Det |

### ESTIMATE (`estimate/`) — gated on review approval
| Stage | File | Bucket |
| --- | --- | --- |
| Scope review | `s01_scope_review.py` | AI |
| Pricing schedule | `s02_schedule.py` | AI propose → Det (structure) |
| Cost build-up | `s03_cost_buildup.py` | Det (qty × rate) |
| Indirects | `s04_indirects.py` | Det |
| Validate | `s05_validate.py` | Rule |
| Letter of offer | `s06_offer.py` | AI (price injected from s03/s04) |

## Module layout

| Path | What it is |
| --- | --- |
| `router.py` | The `/client-boq` APIRouter — the module's only footprint in `api.py` (one `include_router`). Human-gate endpoints + the review→estimate gate check. |
| `models.py` | Pydantic handoffs **and** the module's own `client_boq_*` tables (lazy `CREATE TABLE IF NOT EXISTS`, via `store.get_connection`). |
| `criteria_loader.py` | Loads `siteclaim/docs/client_boq/review_criteria.md` → structured criteria + threshold rules. |
| `rates.py` | Loads `data/rates.csv` → `RateRow`s. The DB-swap seam. |
| `data/rates.csv` | Hand-editable v1 rate source. |
| `jobs.py` | In-package background-job store + pool (replicates the procurement ingest pattern). |
| `ingest/` | The front door: `pdfops.py` (pure PDF structure ops), `s01_plan_split.py`, `s02_interpret.py`, `run.py`. |
| `review/`, `estimate/` | The stage stubs. |
| `tests/` | Scaffold tests (imports, router mounts, loaders parse, stubs raise). |

DEMO fixtures for the AI stages live under `backend/fixtures/cases/client_boq/` (so
`llm_client.complete_json(demo_fixture=...)` resolves them unchanged).

## What this module deliberately does NOT touch

The Gmail path (`pipeline/gmail_client.py`, the token file, `/contacts`,
`/dispatch/drafts`, the reply poller), the procurement pipeline stages
(`stage_01`…`stage_05`, `routing/`, `rules_engine/`), the existing DB tables (only new
`client_boq_*` tables are added), and the existing procurement estimator
(`pipeline/estimate/`, `db/estimate.py`, `schemas/estimate.py`) — the client_boq estimate
is fully independent (CSV rates only). See `siteclaim/docs/client_boq/how_it_fits.md`.

## Status

**The UI exists** (backlog U1–U5, 2026-07-30). `siteclaim/frontend` at `#/tender`: Documents,
Register and Scope, three panes each, with a document pane that renders pages server-side and
overlays the measured highlight rectangles. Price and Offer are not designed yet, so they open and
say what they are waiting for. Full write-up: `siteclaim/docs/client_boq/ui_build.md`.

**REVIEW workflow complete** (slices 1–2): s01→…→s08 fold into one register, gated by the
human approve endpoint.

**ESTIMATE workflow — complete, two gated steps.** Step 1: `/estimate/scope` runs **s01** (AI
scope draft + deterministic register→estimate wiring — confirmed departures injected as
register-sourced assumptions, dismissed items never carried); `/estimate/scope/approve` is its
human gate (optional `amended_summary` becomes the scope of record). Step 2: `/estimate/run`
runs the deterministic spine **s02→s05** + totals/margin, then **s06** (offer-letter draft),
gated on BOTH the review register AND the scope being approved (distinct 409s).

Deliverables: `/estimate/{set_id}/workbook` — a deterministic openpyxl .xlsx (WBS · Resources ·
one sheet per activity · Indirect Costs · Flags), figures equal to the persisted estimate;
`/estimate/{set_id}/letter` — the offer-letter **draft** (markdown), following the committed
template (`docs/client_boq/templates/`) section for section. In the letter, **code injects**
the price ("excluding GST"), the project/client/date/REF/validity fields, the pricing-schedule
table, and the confirmed-departure Appendix-A bullets (verbatim, source `register`); **the AI
drafts** only the intro and the inclusion/exclusion bullets + additional conditions, seeded from
the approved scope. It is a draft — nothing sends it.

The whole client_boq workflow (review + estimate) is now implemented — no stubs remain.

In DEMO the module writes a gitignored scratch DB, so an offline run never touches the
committed `sitesource.db`.
