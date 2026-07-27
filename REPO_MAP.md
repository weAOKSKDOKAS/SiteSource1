# REPO_MAP.md — orientation for a new agent

> **Read this before `siteclaim/CLAUDE.md`.** This file explains what the repo
> *is*, how it differs from the archived `SiteSource` repo, and which committed
> documents are **stale and will mislead you**. `CLAUDE.md` is still the best
> architecture map — but it under-reports the current state by several phases.

---

## 1. Three names, one product

| Name | Where it appears | What it means |
| --- | --- | --- |
| **NOVA** | `README.md` (root, literally `# NOVA`), `BUILD_PLAN.md` §1 ("the NOVA-main tree") | The repo/zip name. Carries no meaning in the code. |
| **siteclaim/** | The top-level source folder | **Legacy directory name, never renamed.** Not the product. |
| **SiteSource** | Everything current: `Makefile`, `CLAUDE.md`, `CONTEXT.md`, `sitesource.db`, `SITESOURCE_DB`, `sitesource-frontend` | **The actual product.** |
| *SiteClaim* | `siteclaim/README.md`, `eval/`, a few docstrings | A **dead predecessor product** (HK payment-claim drafting under Cap. 652 SOPO). Its chassis was reused; its domain logic is gone. |

**SiteSource** is an AI subcontractor-sourcing and bid-leveling platform for Hong
Kong main contractors. Ingest a tender → split by trade → shortlist firms from a
proprietary database with cited evidence → dispatch bundles → level the returned
quotes → produce a risk-adjusted recommendation. A human makes every decision.

---

## 2. Run it

```bash
cd siteclaim
make demo          # or: bash scripts/demo.sh
```

Seeds the DB if absent, starts the API in `DEMO_MODE` on `:8000`, starts the Vite
wizard on `:5173`. Fully offline — zero network, no model load.

```bash
cd siteclaim/backend && python -m pytest -q   # tests MUST run from backend/
cd siteclaim/frontend && npm run build        # tsc --noEmit && vite build
```

> **Trap:** `pytest` only passes when run from `siteclaim/backend/`. Several tests
> read `db/schema.sql` by relative path and fail from any other cwd. The `Makefile`
> `test` target does this correctly; running `pytest` from the repo root does not.

**Verified working** (this environment, 2026-07-27): DB seeds clean, API boots and
serves real data, frontend type-checks and builds, **665 passed / 13 failed / 8
skipped**. All 13 failures share one root cause — `requirements.txt` pins nothing,
so a fresh install pulls FastAPI 0.139.2, whose router internals broke the
`{r.path for r in app.routes}` idiom used *only* in tests asserting routes are
registered. Every one of those routes works when called live. Pin FastAPI if you
want a green suite on a fresh clone.

---

## 3. The four layers (the load-bearing idea)

Stated in `siteclaim/CLAUDE.md`, enforced by tests (`test_layer1_purity.py`,
`test_provenance_guard.py`):

- **Layer 1 — rules engine** (`backend/rules_engine/`): pure deterministic Python.
  Arithmetic, risk severity, ranking, variance. No ML, no LLM.
- **Layer 2 — Claude** (`backend/pipeline/llm_client.py`): reads, splits, parses,
  drafts, narrates.
- **Layer 3 — the database** (`backend/db/`): fused public records + private
  closeout archive. SQLite + baked embedding vectors. **The moat.**
- **Layer 4 — human gates**: approve-before-dispatch, adjust-leveling, final award.

**The one principle:** *the LLM never invents a number, a risk flag, a ranking, a
match, or a reason.* Severity is decided in `rules_engine/risk_scoring.py` and
nowhere else — the DB stores raw facts, never adjudicated severities.

---

## 4. Repo layout

```
/                          README.md (# NOVA), BUILD_PLAN.md, REPO_MAP.md (this)
└── siteclaim/             CLAUDE.md · CONTEXT.md · DEMO.md · Makefile · README.md(stale)
    ├── backend/
    │   ├── api.py              FastAPI driver — 2,503 lines, ~80 routes
    │   ├── schemas/            models.py + benchmark/estimate/project/routing.py
    │   ├── rules_engine/       Layer 1: risk_scoring · ranking · leveling · taxonomy · variance
    │   ├── db/                 Layer 3: schema.sql · store · cross_reference · seed · refresh …
    │   ├── pipeline/           stage_01..05 + routing/ estimate/ benchmark/ + gmail/ocr/reply
    │   ├── client_boq/         SEPARATE capability, mounted at /client-boq
    │   ├── references/rubrics/ trade_taxonomy.md · risk_scoring.md · leveling_rules.md
    │   └── fixtures/           DEMO_MODE fixtures (cases/) + out/ (generated)
    ├── frontend/src/       App.tsx + steps/ + 5 top-nav pages
    ├── docs/               QUICKSTART · EMAIL_SETUP · client_boq/
    ├── scripts/            demo.sh · *.bat · capture_fixture.py (BROKEN, legacy)
    └── eval/               DEAD legacy SiteClaim code — cannot import
```

### The rubrics are source-of-truth, not documentation
`rules_engine/taxonomy.py` **parses** `references/rubrics/trade_taxonomy.md` at
import. Add a trade to the markdown table, no code change needed. Likewise
`risk_scoring.md` and `leveling_rules.md` define the `rule_ref` strings the engine
emits. Edit the rubric, not the constant.

---

## 5. Two capabilities, deliberately separate

### 5a. The procurement pipeline (`backend/pipeline/`) — forward-only, typed handoffs

| Stage | In → Out | Layers |
| --- | --- | --- |
| `stage_01_ingest` | `TenderPackage` → `ScopePackages` | L2 splits, L1 validates taxonomy |
| `stage_02_shortlist` | `ScopePackages` + DB → `ShortlistSet` | **Pure L1 — the demo hero** |
| `stage_03_dispatch` | `ShortlistSet` + approvals → `DispatchSet` | L4 gate + L2 email |
| `stage_04_level` | `BidReplies` → `LevelledBids` | L2 parses, L1 recomputes |
| `stage_05_recommend` | `LevelledBids` + DB → `Recommendation` | L1 ranks, L2 narrates, L4 awards |

Each folder has a `CONTEXT.md` with its Inputs/Process/Outputs contract. **Flow is
strictly forward** — a stage may only read earlier stages' outputs.

Beyond the five stages the pipeline also holds the **unified engine**:
`pipeline/routing/` (self-perform vs sublet), `pipeline/estimate/` (the left
track), `pipeline/benchmark/` (tender vs outturn variance + EOS narratives), plus
`gmail_client.py`, `reply_poller.py`, `ocr.py`, `workspace.py`.

### 5b. `backend/client_boq/` — the client→BOQ module (newest capability)

Sits **beside** the pipeline, not inside it. Mounted with a single
`app.include_router(client_boq_router)` line in `api.py`. Two sequential
workflows over one parsed-document store:

- **REVIEW** (`review/s01..s08`) — ingest a client's contract set, match against a
  criteria library, produce a **departure register** a human approves.
- **ESTIMATE** (`estimate/s01..s06`) — gated behind review approval: scope review,
  pricing schedule, cost build-up, indirects, validation, letter of offer.

Four locked v1 decisions (in `client_boq/CONTEXT.md`): quantities are given (no
take-off), rates come from a hand-editable CSV, only 8 numeric criteria are
rule-pre-flagged, and review gates estimate. Start at
`docs/client_boq/how_it_fits.md`, then `client_boq/CONTEXT.md`.

**Why it's clean:** in DEMO it writes a gitignored scratch DB — two tests assert
the committed `sitesource.db` stays **byte-identical** through a full run.

---

## 6. What's different from the `SiteSource` repo

The other repo — **`weAOKSKDOKAS/SiteSource`** (private) — is **not a parallel
codebase**. It is a single commit ("Add files via upload") containing one file:
`NOVA-main (6).zip`, a snapshot of this tree dated **2026-06-21**.

**`SiteSource1` is a strict superset.** A full recursive diff shows **zero files
removed or renamed** — every path in the snapshot still exists here. The snapshot
is the *"Phases 0–10, demo complete"* state; this repo is that plus everything
since.

| | `SiteSource` (zip, 2026-06-21) | `SiteSource1` (now) |
| --- | --- | --- |
| Backend `.py` files | 53 | **212** |
| Test files | 16 | **99** |
| `api.py` | 271 lines, **11 routes** | 2,503 lines, **~80 routes** |
| Schema modules | `models.py` only | + `benchmark` `estimate` `project` `routing` |
| DB tables | 8 | **22** |
| DB firm rows | 150 | **1,423** |
| Frontend `src/` files | 14 | 23 |
| Wizard steps | 5 | **6** (Route inserted at 2) |
| Top-nav sections | none (wizard only) | **5** (Sourcing · Estimator · Benchmark · Projects · Database) |
| Demo scenarios | clean · hero · messy | **golden** · hero · messy · **two_trade** |
| Seed profiles | one | **demo / live** split |
| `client_boq/` | absent | present |
| `BUILD_PLAN.md` | absent | present |

### What SiteSource1 adds, grouped

**Phase A — engine live** (`stage_03_dispatch/`): `attachments.py`,
`relevant_docs.py`, `mailer.py` (real SMTP behind a triple gate), `drafts.py`,
`doc_refs.py`; `pipeline/workspace.py`; `POST /level-upload`.

**Phase B — shortlist decoupled from the EOS gate**: `cross_reference(...,
include_public=True)` opens the shortlist to the full screened public pool.
`include_public=False` stays the default so demo behaviour is unchanged.

**Phase C — real, refreshable public data**: `db/register_loader.py`,
`db/refresh.py` + `/refresh/*` behind a human confirm gate, the
`--profile {demo,live}` seed split (`sitesource.db` / `sitesource_live.db`,
selected at runtime by `SITESOURCE_DB`), `staged_firms`/`staged_flags` tables.

**Phase D — the moat, code-ready**: `db/ingest_closeouts.py` resolves partner
closeout exports to firms and bakes embeddings. *The partner archive itself is
still pending* — this is plumbing awaiting data.

**The unified engine** (the largest addition): `pipeline/routing/`,
`pipeline/estimate/`, `pipeline/benchmark/`, `rules_engine/variance.py`,
`db/{benchmark,estimate,routing,project}.py`, and four new frontend pages
(`EstimatorPage` `BenchmarkPage` `ProjectsPage` `DatabasePage`) plus
`RouteDecisionPanel`.

**Live-path infrastructure**: `gmail_client.py` (replaced n8n), `reply_poller.py`,
`reply_loop.py`, `ocr.py`, `ocr_table.py`, `concurrency.py`, `scope_store.py`,
`stage_01_ingest/{classify,doc_index}.py`, `stage_04_level/{reply_xlsx,route_items}.py`.

**The client→BOQ module** — `backend/client_boq/` + `docs/client_boq/` (§5b).

### Practical consequence
Treat the `SiteSource` repo as a **historical snapshot only**. There is nothing to
merge back from it and nothing in it that this repo lacks. All current work
happens here.

---

## 7. Stale documents — do not trust these

The repo's own docs lag the code. Verified against the running system:

| Document | Problem |
| --- | --- |
| **`siteclaim/README.md`** | **Entirely the dead SiteClaim product.** Describes a SOPO payment-claim copilot, stages `extract→validate→draft→audit`, a savings dashboard, `POST /extract-upload`. None of it exists. Single most misleading file in the repo. |
| **`siteclaim/CLAUDE.md`** | Architecture is sound, but **"Build complete (Phases 0–10)"** and the Phase 0–10 list stop at the June snapshot. Says **"156 firms … 140 real (134 building-trade + 6 GI)"** — see below. |
| **`siteclaim/DEMO.md`** | Repeats the stale **"140 real public-register firms / 46 flagged"**. |
| **`BUILD_PLAN.md`** | Mostly current, but §1 says 92 tests (now ~680) and 156 firms; §10's "next three tasks" still names n8n, which §4 declares removed. Internally inconsistent on 134 vs 140. |
| **`frontend/README.md`** | Says 5 wizard steps; there are 6, plus 5 top-nav sections. |
| **`siteclaim/eval/`** | Dead SiteClaim code. Imports `rules_engine.sopo_config`, `business_days`, `deadlines` — **none exist**. Cannot import. |
| **`scripts/capture_fixture.py`** | Imports `stage_01_extract`, `stage_02_validate`, … — all deleted. Broken at import. |
| **`Makefile` / `README.md`** | README advertises `make snapshots`; no such target. |

### The firm-count correction (important)

`CLAUDE.md` and `DEMO.md` both state **140 real firms**. The live database reports
otherwise:

```
demo profile: total_firms 1407  (register 1365 + overlay 42), flagged 46
live profile: total_firms 1407  — identical
firms table:  1423 rows = 1407 public_register + 16 illustrative
```

So the register was expanded roughly **10×** since those docs were written. What
*is* still accurate: **46 flagged** (11 debarment, 36 safety prosecution, 1
winding-up) across 6 government sources, and the demo/live split — illustrative
firms are present-but-excluded in demo, absent in live.

**If you cite coverage numbers anywhere user-facing, read them from
`store.coverage(conn)` at runtime. Do not copy them from the markdown.**

### What the honesty footnotes get right
`DEMO.md`'s footnotes remain true and matter for any pitch context: the
**benchmark, EOS, and estimator-precedent layers are illustrative** until a real
partner archive exists. The live profile ships the empty state honestly
(`/benchmark/summary` reads zero, rate suggestion reads "no corpus yet"). No rate
history is fabricated to look fuller. `rubric_items` ships empty by design.

---

## 8. DEMO_MODE — how offline actually works

`llm_client.complete_json()` checks `demo_mode()` **first** and returns a fixture
validated into the target Pydantic model, short-circuiting *before any provider
code runs*. No SDK import, no socket. The demo works with `anthropic`, `openai`
and `pymupdf` all uninstalled.

- `DEMO_MODE` is read **dynamically per call**, so tests can toggle it.
- A DEMO call with no `demo_fixture` **raises loudly** — silence is never the
  fallback.
- **Any network call in DEMO_MODE is a bug.**

Fixtures live in `backend/fixtures/cases/`, resolved relative to
`backend/fixtures/` — which is why `client_boq` fixtures must sit there rather
than inside the module.

---

## 9. Reading order for a new agent

1. **This file** — orientation + what not to trust.
2. `siteclaim/CLAUDE.md` — the four layers and the one principle (ignore its
   status/phase section).
3. `siteclaim/CONTEXT.md` — the five-stage routing table and the two invariants.
4. `BUILD_PLAN.md` — *why* the engine is built this way (§0 engine-vs-moat is the
   strategic frame) and what is genuinely pending.
5. `backend/schemas/models.py` — the vocabulary every stage passes.
6. The `CONTEXT.md` of whichever stage you're touching.
7. For client→BOQ work: `docs/client_boq/how_it_fits.md` →
   `backend/client_boq/CONTEXT.md`.

### House rules worth knowing before you edit
- Imports are rooted at `backend/` — `from pipeline...`, never `from backend.pipeline...`.
- Severity belongs to `rules_engine/risk_scoring.py`. The DB stores facts.
- A fatal risk flag demotes a firm **regardless of price**, and no award leaves
  Stage 05 without explicit human sign-off.
- Prefer routing **whole** documents; never silently slice a combined legal PDF.
- New capabilities go **beside** the pipeline (the `client_boq` pattern), not
  inside it.
