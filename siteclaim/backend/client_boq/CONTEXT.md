# CONTEXT.md — client_boq module (dev map)

> Read this to orient inside the module. It is the local map; the stage files are the
> work. Reference docs live in `siteclaim/docs/client_boq/`.

## What this module is

A **client→BOQ** capability that sits *beside* the procurement pipeline, not inside it.
The client (main contractor) hands over a tender/contract document set; the module runs
two **sequential** workflows over it:

1. **REVIEW** — ingest the set, check it against a criteria library, and produce a
   departure register a human approves.
2. **ESTIMATE** — *after review approval*, build up the cost from the same document
   context and support a profitability read.

They are sequential and share one parsed-document store: review runs first, a human
approves the register (the **review→estimate gate**), and only then does estimate run.

## The one principle (carried from the main app)

The LLM **reads, structures, proposes, and drafts** — it never writes a decision value.
Every price, verdict, confirmed match, and route comes from deterministic math, a rule,
or a human gate. See `siteclaim/docs/client_boq/client_boq_layer_mapping.md` — it is the
authoritative task→bucket mapping; do not re-derive it.

## The four locked v1 decisions

1. **Quantities are given** (from a BOQ or manual entry). No drawing take-off in v1.
2. **Rates from a hand-editable CSV** behind `rates.py` — the seam that later swaps to a
   company DB. No DB-backed rates in v1.
3. **Criteria breach:** the rule layer pre-flags *only* the numeric criteria in the
   threshold table of `review_criteria.md`; everything else is an AI-proposed candidate.
   The verdict on every departure is a **human gate**. The AI never writes breach/no-breach.
4. **Review gates estimate:** the estimate endpoints refuse to run until the review
   register for that document set is human-approved.

(Note: the original "temperature 0" idea was dropped — `llm_client` exposes no
temperature and is chassis. Consistency comes from fixed prompts, strict Pydantic
schemas, the corrective-JSON retry, and DEMO fixtures.)

## Stages and their buckets

Bucket key: **Det** = deterministic · **Rule** = rule-based · **AI** = AI-judgment (draft
only) · **Gate** = human approval.

### REVIEW (`review/`)
| Stage | File | Bucket |
| --- | --- | --- |
| Ingest document set | `s01_ingest.py` | Det (extract) + AI (structure) |
| Context summary | `s02_context_summary.py` | AI |
| Criteria match | `s03_criteria_match.py` | AI propose → Rule pre-flag → **Gate** verdict |
| Scope alignment | `s04_scope_align.py` | AI propose → Rule (precedence) |
| Program check | `s05_program_check.py` | AI propose → Det (recompute) |
| Cash-flow | `s06_cashflow.py` | Det |
| Register assemble | `s07_register.py` | Det (template fill) |
| Citation verify | `s08_citation_verify.py` | Det (lookup guard) |

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

**REVIEW workflow complete** (slices 1–2): s01→…→s08 fold into one register, gated by the
human approve endpoint.

**ESTIMATE workflow — two gated steps.** Step 1: `/estimate/scope` runs **s01** (AI scope
draft + deterministic register→estimate wiring — confirmed departures injected as
register-sourced assumptions, dismissed items never carried); `/estimate/scope/approve` is
its human gate (optional `amended_summary` becomes the scope of record). Step 2:
`/estimate/run` runs the deterministic spine **s02→s05** + totals/margin, gated on BOTH the
review register AND the scope being approved (distinct 409s). Deliverable:
`/estimate/{set_id}/workbook` — a deterministic openpyxl .xlsx (WBS · Resources · one sheet
per activity · Indirect Costs · Flags) whose figures equal the persisted estimate exactly.

**Deferred (pending committed letter templates):** s06 offer-letter draft and the
`/estimate/{set_id}/letter` endpoint. s06 remains a stub; wire it to
`docs/client_boq/templates/` once those exist.

In DEMO the module writes a gitignored scratch DB, so an offline run never touches the
committed `sitesource.db`.
