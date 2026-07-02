# CLAUDE.md — SiteSource (Layer 0 orientation)

> Re-read this file first to orient. It is the map; the folders are the
> architecture. Coordination lives in the filesystem, not in a framework.

## What SiteSource is

SiteSource is an **AI subcontractor-sourcing and bid-leveling platform** for
established Hong Kong main contractors. It ingests a tender package, splits the
scope by trade, shortlists subcontractors from a **proprietary fused database**
with cited evidence, dispatches the right document bundle to each, ingests their
priced replies, levels the quotes, and produces a **risk-adjusted recommendation**.
The human makes the final award.

The chassis is carried over from the previous product (SiteClaim): the folder
structure *is* the architecture, stages hand off **plain typed data** (the Pydantic
models in `backend/schemas/models.py`), and there is **no agent framework**.

## The one principle

**The LLM reads, splits, composes, and explains. The deterministic rules engine
computes and checks (arithmetic, risk flags, ranking). A proprietary fused database
of subcontractor performance and risk signals makes the recommendation defensible.**

The LLM never invents a number, a risk flag, or a ranking — those come from Layer 1
and the database. The demo shows Claude working at every stage; the moat is the
cross-reference against data a generic chatbot cannot access.

## Four layers

- **Layer 1 — Rules engine** (`backend/rules_engine/`): pure, deterministic Python.
  Leveling arithmetic, risk scoring, candidate ranking. No ML, no LLM.
- **Layer 2 — Claude** (`backend/pipeline/llm_client.py`): reads tender documents,
  splits scope, runs semantic relevance over closeout text, parses replies,
  composes emails, narrates the recommendation.
- **Layer 3 — The proprietary database** (`backend/db/`): the fused subcontractor
  profiles (SQLite + baked embeddings). The grounding corpus and the moat. Two
  layers coexist: real scraped Hong Kong public records (`seed_data/public/`) are
  the **discovery/coverage** pool — screened and counted (see `GET /coverage`) but
  not auto-shortlisted; the **per-tender shortlist** is drawn only from firms with
  an assessable EOS closeout record (`store.shortlistable_firms_for_trade`). Phase B
  adds `cross_reference(..., include_public=True)` — the live-engine path — which
  opens the shortlist to the full screened pool so real firms can be shortlisted;
  the default keeps the assessed-firm behaviour the demo relies on. A `contacts`
  table (address book, keyed by firm+trade) records where each RFQ is sent.
- **Layer 4 — Human approval gates**: approve-before-dispatch, adjust-leveling,
  final-award.

> The live-engine roadmap and the current task list live in `BUILD_PLAN.md` at the
> repo root. Landed: Phase B (shortlist decouple), Phase A (engine-live plumbing:
> routed attachments, real SMTP send behind the mock-outbox default, the address book,
> the `/level-upload` inbound channel), Phase C (a `demo`/`live` seed profile split —
> `python -m db.seed --profile {demo,live}`, selected at runtime via `SITESOURCE_DB`;
> a human-gated public-data refresh at `/refresh/*`; and debarment-link cleanup), and
> the Phase D code-ready closeout ingest (`db/ingest_closeouts.py`). See `BUILD_PLAN.md`.
>
> Two databases now: `sitesource.db` is the demo profile (156 firms; the committed
> pitch DB the tests read). `sitesource_live.db` is the clean live profile (140 real
> firms only). Coverage is 140/46 in both — 140 real = 134 building-trade + 6
> ground-investigation firms (taxonomy v2); illustrative firms are present-but-excluded
> in demo and simply absent in live. Partner-archive firms carry provenance
> `partner_archive` and never enter the 140/46 figures.

## Five-stage pipeline (`backend/pipeline/`)

Forward-only, typed handoffs. Each stage folder has a `CONTEXT.md`
(Inputs / Process / Outputs).

1. **stage_01_ingest** — `TenderPackage` (Method of Measurement, Particular
   Specification, Tender Addendum, Schedule of Rates) → `ScopePackages`, one per
   trade. L2 splits, L1 validates trades against the taxonomy.
2. **stage_02_shortlist** — `ScopePackages` + database → `ShortlistSet`: ranked
   candidates per trade with cited evidence and risk flags. **Pure Layer 1
   cross-reference — the demo hero.**
3. **stage_03_dispatch** — `ShortlistSet` + human approval → `DispatchSet`: a
   per-subcontractor bundle (only that trade's documents) and a composed email,
   written to a mock outbox. **Layer 4 gate.**
4. **stage_04_level** — `BidReplies` → `LevelledBids`: normalized scope, corrected
   arithmetic, flagged exclusions and scope gaps, Excel export. L2 parses, L1
   calculates.
5. **stage_05_recommend** — `LevelledBids` + database track record + bid
   distribution + historical pricing → `Recommendation`. L1 risk-adjusted ranking,
   L4 human award.

## Where everything lives

| Path | What it is |
| --- | --- |
| `backend/schemas/models.py` | The typed contracts every stage passes. |
| `backend/rules_engine/` | Layer 1 — deterministic risk scoring, ranking, leveling. |
| `backend/pipeline/llm_client.py` | Layer 2 plumbing (DEMO_MODE, providers, strict-JSON, multimodal). **Chassis — kept verbatim.** |
| `backend/pipeline/documents.py` | PDF → base64 PNG for the live vision path. **Chassis — kept.** |
| `backend/pipeline/stage_NN_*/CONTEXT.md` | Per-stage contract. |
| `backend/db/` | Layer 3 — the proprietary database (SQLite + baked embeddings). |
| `backend/references/rubrics/` | Trade taxonomy, leveling rules, risk-scoring rules. |
| `backend/fixtures/` | Serialised stage objects for DEMO_MODE / tests. |
| `backend/api.py` | Thin FastAPI driver (one POST per stage + Excel download). |
| `frontend/` | React + TypeScript + Vite + Tailwind five-step wizard. |
| `eval/` | Left in place from SiteClaim; not part of this build. |

## DEMO_MODE

DEMO_MODE runs the whole pipeline **offline on fixtures**, exactly as the chassis
did: zero network, no model load. Treat any network call in DEMO_MODE as a bug.

## Status

**Build complete (Phases 0–10).** Run the demo with `bash scripts/demo.sh` (or
`make demo`) and see `DEMO.md` for the runbook and the three scenarios
(clean · hero · messy). Landed: Phase 0 (orient/strip/reskin), Phase 1
(schemas + rubrics), Phase 2 (the proprietary database `backend/db/` — schema,
store, baked-vector embeddings, the fused seed with the planted gotcha electrical
firm, plus `rules_engine/risk_scoring.py`, `rules_engine/ranking.py`, and
`db/cross_reference.py`), and Phase 3 (`stage_01_ingest` — tender → scope split
with Layer-1 taxonomy validation), Phase 4 (`stage_02_shortlist` — the hero:
ranked candidates per trade with cited evidence, the gotcha demoted and marked
`recommended_against`), and Phase 5 (`stage_03_dispatch` — trade-only document
bundles, Layer-2 composed emails, and a mock outbox, behind the Layer-4 approval
gate), Phase 6 (`stage_04_level` — `rules_engine/leveling.py` recomputes every
amount, flags arithmetic errors / scope gaps / exclusions, and exports the
comparison to Excel), and Phase 7 (`stage_05_recommend` — risk-adjusted ranking
with the bid distribution and historical band, Layer-2 rationale; plus
`run_pipeline.py`, the offline end-to-end runner that prints the hero catch), and
Phase 8 (`api.py` — one POST per stage `/ingest` `/shortlist` `/dispatch` `/level`
`/recommend`, the `/leveling.xlsx` download, the multipart `/ingest-upload`, and the
`/demo/cases` · `/demo/{id}` loaders; DEMO_MODE respected end-to-end, `/health`
reports it), and Phase 9 (the React/TS/Vite/Tailwind five-step wizard —
`StepIngest` · `StepShortlist` · `StepDispatch` · `StepLevel` · `StepRecommend` —
reusing the chassis visual language and recharts; the gotcha is shown
`recommended_against` with citations on both the shortlist and recommendation
screens), and Phase 10 (three deterministic demo scenarios from one selector,
`scripts/demo.sh`, projector tightening, and the `DEMO.md` runbook).
