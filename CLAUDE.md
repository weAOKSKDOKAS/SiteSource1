# CLAUDE.md — repo orientation (read this first)

Repo-wide map for an agent arriving with no context: what is here, how this branch differs from
`main`, how to run it, and the traps. Deeper docs are indexed in §7 — this file is the entry point,
not a duplicate of them.

---

## 1. What this repo is, in 30 seconds

One FastAPI backend + one React frontend, hosting **two different construction products** that share a
chassis but almost no business logic:

| | **Procurement** (the original) | **client_boq** (newer, this branch) |
| --- | --- | --- |
| Direction | Contractor sources work **out** to subcontractors | Client's contract comes **in** to the contractor |
| Flow | tender → split by trade → shortlist firms → email enquiries → level bids → award | contract → departure register (**review**) → cost estimate + workbook + offer letter (**estimate**) |
| Code | `siteclaim/backend/pipeline/`, `db/`, `rules_engine/` | `siteclaim/backend/client_boq/` |
| API | ~58 endpoints at root (`/ingest`, `/shortlist`, …) | 13 endpoints under `/client-boq/*` |
| Frontend | Yes — 5 tabs, a 5-step wizard | **None.** API-only today |

The governing principle in both: **the LLM reads, structures, proposes and drafts; deterministic code
and human gates decide.** No price, verdict, or risk flag is ever written by a model.

Everything lives under `siteclaim/`. The repo root holds only `BUILD_PLAN.md`, `README.md`, and this file.

---

## 2. How this branch differs from `main` — the important part

Branch: **`from-client-to-tender-BOQ`**. It was forked from `claude/phase-a-implementation-k9p7z8`,
not from `main`, so the diff vs `main` has **two layers**:

```
origin/main  (908f894)
   │
   ├── 4 commits ──▶ claude/phase-a-implementation-k9p7z8   [LAYER 1: inherited]
   │                 Gmail dispatch hardening (procurement)
   │
   └────────────────▶ from-client-to-tender-BOQ (HEAD)      [LAYER 2: this branch's work]
                      12 commits — the entire client_boq module + docs
```

**Layer 1 — inherited (not this branch's work).** 4 commits hardening the procurement Gmail dispatch:
recipient fallback to `firms.enquiry_email`, compose failure falls back to template instead of 500,
honest token/draft-error status. Touches `pipeline/gmail_client.py`, `stage_03_dispatch/{dispatch,mailer}.py`,
`db/store.py`, their tests, and 3 frontend files.

**Layer 2 — client_boq (this branch).** 12 commits. **65 new files, and only 2 existing files modified:**

| Modified file | The entire change |
| --- | --- |
| `siteclaim/backend/api.py` | **2 lines**: one import + `app.include_router(client_boq_router)` |
| `siteclaim/CLAUDE.md` | **1 row** added to the "where everything lives" table |

Everything else is new and self-contained:
- `siteclaim/backend/client_boq/**` — 48 files (the module + its 18 test files)
- `siteclaim/backend/fixtures/cases/client_boq/**` — 8 DEMO fixtures
- `siteclaim/docs/client_boq/**` — 8 docs (specs, criteria library, letter templates, UI inventory)
- `siteclaim/backend/fixtures/samples/Belvidere.pdf` — a real 6 MB tender for live testing

**Takeaway for a new agent:** client_boq is a bolt-on module. It imports *from* the procurement chassis
(LLM client, PDF extraction, DB connection, Workspace) but the procurement side has **zero** knowledge of
it. You can work on either side without touching the other — and you should keep it that way (§4).

Total vs `main`: 79 files changed, ~6,950 insertions, 20 deletions.

---

## 3. Repo map

```
SiteSource1/
├── CLAUDE.md                    ← you are here (repo orientation)
├── BUILD_PLAN.md                ← the product/roadmap thinking (phases A–D)
└── siteclaim/
    ├── CLAUDE.md                ← procurement architecture: the 4 layers, 5 stages, DEMO_MODE
    ├── CONTEXT.md               ← procurement pipeline stage routing table
    ├── DEMO.md                  ← procurement demo runbook (3 scenarios)
    ├── backend/
    │   ├── api.py               ← the single FastAPI app (~2,500 lines, 71 endpoints)
    │   ├── pipeline/            ← PROCUREMENT: stage_01_ingest … stage_05_recommend
    │   │   ├── llm_client.py    ← ⭐ the ONLY LLM seam (both products use it)
    │   │   ├── documents.py     ← ⭐ PDF/OCR extraction (both products use it)
    │   │   ├── workspace.py     ← ⭐ per-tender file storage (both products use it)
    │   │   ├── gmail_client.py  ← 🚫 procurement only — client_boq must never import
    │   │   ├── routing/ benchmark/ estimate/   ← procurement sub-tracks
    │   ├── db/                  ← Layer 3: SQLite firm database + schema.sql + seeds
    │   │   ├── store.py         ← ⭐ get_connection() (both products use it)
    │   │   ├── sitesource.db    ← committed demo DB (1,407 firms) — do not mutate
    │   │   └── sitesource_live.db
    │   ├── rules_engine/        ← procurement deterministic math (leveling, ranking, risk)
    │   ├── schemas/             ← procurement pydantic models
    │   ├── client_boq/          ← ⭐ THE NEW MODULE (see §5)
    │   ├── fixtures/            ← DEMO fixtures (cases/) + out/ (gitignored runtime artifacts)
    │   └── references/rubrics/  ← trade taxonomy, leveling + risk rubrics
    ├── frontend/                ← React+TS+Vite+Tailwind — PROCUREMENT ONLY
    └── docs/                    ← EMAIL_SETUP, QUICKSTART, PRODUCT_ARCHITECTURE, client_boq/
```

Rough size (non-test): procurement backend ~14.9k lines Python · client_boq ~3.5k · frontend ~7.1k TS.

---

## 4. The boundary — what client_boq may and may not touch

This boundary was a design constraint, is enforced by the code layout, and should be preserved.

**client_boq REUSES (by import, never modifies):**
- `pipeline.llm_client` — `LLMClient().complete_json(system=, user=, target_model=, demo_fixture=, purpose=)`
- `pipeline.documents.extract_document(data, content_type, table_aware=)` — PDF text + page images
- `db.store.get_connection()` — the shared SQLite connection (honours `SITESOURCE_DB`)
- `pipeline.workspace.Workspace` / `tender_slug` — per-tender file storage

**client_boq must NEVER touch:**
- The Gmail path — `gmail_client.py`, `.gmail_token.json`, `reply_poller.py`, `/contacts`, `/dispatch/drafts`.
  client_boq sends no email at all.
- Procurement pipeline stages, `rules_engine/`, `routing/`, `benchmark/`, `pipeline/estimate/`
  (note: that last one is the *procurement* estimator — a different thing from `client_boq/estimate/`).
- `db/schema.sql` and `db/seed.py`. client_boq owns 4 tables it creates lazily itself with
  `CREATE TABLE IF NOT EXISTS client_boq_*` (see `client_boq/models.py`).

---

## 5. Inside `client_boq` — the module a new agent will most likely work on

Two sequential workflows separated by human gates. Start at `siteclaim/backend/client_boq/CONTEXT.md`.

```
REVIEW                                          ESTIMATE
s01 ingest        Det+AI  parse → clauses        s01 scope review   AI draft + register wiring
s02 summary       AI      commercial-risk        ─── GATE: /estimate/scope/approve ───
s03 criteria      AI→RULE match + 8 thresholds   s02 schedule       Det  normalise
s04 scope align   AI→RULE precedence (SQD-01)    s03 cost buildup   Det  qty × rate
s05 program       AI→Det  LD/mobilisation        s04 indirects      Det  lump/per_week/pct
s06 cashflow      Det     monthly profile        s05 validate       RULE 5 flags
s07 register      Det     assemble ONE register  s06 offer letter   AI prose + injected numbers
s08 citations     Det     anti-hallucination     → workbook (.xlsx) + letter (.md)
─── GATE: /review/approve ───
```

**Three gate rules that must not be broken:**
1. `/estimate/scope` 409s until the **review register** is approved.
2. `/estimate/run` 409s until **both** the register *and* the **scope** are approved (distinct messages).
3. The approve endpoints are the **only** writers of `confirmed`/`dismissed` verdicts and the gate flags.
   No stage may write a verdict — `DepartureProposal` (the AI's s03 output model) deliberately has **no
   status field**, so the model structurally cannot.

**Other invariants:** no silent drops (unmatched criteria → `unresolved`, unmatched clauses →
`uncovered`, bad citations → `citation_failed`, all kept visible); every AI call passes a `demo_fixture`
so DEMO is fully offline; heavy work runs as sync `def` on the in-package pool (`jobs.py`).

Key files: `router.py` (13 endpoints) · `models.py` (schemas + table DDL) · `rules.py` (the 8 numeric
threshold rules + precedence + LD math) · `store.py` (persistence + gates) · `criteria_loader.py`
(parses the criteria markdown) · `rates.py` + `data/rates.csv` (the future-DB seam).

---

## 6. Running it, and the one fork you must understand

### DEMO mode — works right now, fully offline
```bash
cd siteclaim/backend
DEMO_MODE=true uvicorn api:app --port 8000     # PowerShell: $env:DEMO_MODE="true"
```
Frontend (procurement only): `cd siteclaim/frontend && npm install && npm run dev` → `localhost:5173`.

### ⚠️ DEMO and LIVE are NOT "same code, different config"
There is a real **code fork** on `demo_mode()`, and a new agent will get burned by assuming otherwise:
- `pipeline/llm_client.py:175` — in DEMO, `complete_json` returns a baked fixture **before any provider
  code runs**. The entire live prompt/parse/retry path is bypassed.
- `client_boq/store.py` — in DEMO with no `SITESOURCE_DB` set, it opens a **gitignored scratch DB** so the
  committed `sitesource.db` is never written. Procurement does **not** do this; it reads the real DB.
- `api.py` — DEMO disables the `/contacts` and `/refresh` writes and the real mailer.

**Consequence:** green tests prove the deterministic engine and data contracts. They prove **nothing**
about the live LLM-reading path. As of this writing, the live path has **never been run** — no real
document has been processed end-to-end.

### LIVE mode — needs setup not present in a fresh container
```bash
pip install pymupdf anthropic openai      # lazily imported; absent by default
# siteclaim/backend/.env  (auto-loaded by api.py)
DEMO_MODE=false
EXTRACTION_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...
# DEEPSEEK_API_KEY=sk-...   # optional; text-only calls route here when set
```

### Tests
```bash
cd siteclaim/backend && python -m pytest -q          # 678 passed, 8 skipped
python -m pytest client_boq/tests/ -q                # 84 passed
```

---

## 7. Where to read next

| Doc | Read it when |
| --- | --- |
| `siteclaim/CLAUDE.md` | You need the procurement architecture (4 layers, 5 stages, DEMO_MODE philosophy) |
| `siteclaim/backend/client_boq/CONTEXT.md` | You are working inside client_boq — stage/bucket map + locked decisions |
| `siteclaim/docs/client_boq/how_it_fits.md` | You need the plain-language "how the two products relate" |
| `siteclaim/docs/client_boq/client_boq_layer_mapping.md` | **Authoritative** task→layer mapping (deterministic/rule/AI/gate) |
| `siteclaim/docs/client_boq/review_criteria.md` | The criteria library — 28 criteria + the 8-row threshold table |
| `siteclaim/docs/client_boq/reviewing_a_construction_contract_with_ai.md` | The review workflow's domain spec |
| `siteclaim/docs/client_boq/estimating_process.md` | The estimate workflow's domain spec |
| `siteclaim/docs/client_boq/templates/` | Letter-of-offer template + worked example (s06 follows these) |
| `siteclaim/docs/client_boq/ui_inventory.md` | You are designing/building a client_boq frontend |
| `BUILD_PLAN.md` | Product strategy — phases A–D, what's a commodity vs the moat |

---

## 8. Traps — things that have already bitten someone here

1. **`requirements.txt` pins almost nothing** (only `pydantic>=2`). A fresh `pip install` pulled FastAPI
   0.139, whose `include_router` is *lazy* — `app.routes` then holds an `_IncludedRouter` wrapper and 13
   existing route-registration tests fail. **The suite is green on FastAPI 0.115.6.** If route tests fail
   mysteriously, check the FastAPI version before debugging the code. Assert against `app.openapi()`
   rather than `app.routes` in new tests.
2. **Never let a test or a manual probe write `db/sitesource.db`.** It is committed. client_boq tests
   isolate via a temp `SITESOURCE_DB` (`client_boq/tests/conftest.py`) and there is a hygiene test
   asserting byte-identity. Procurement code reads the real DB, so pointing `SITESOURCE_DB` at an empty
   file breaks `/coverage` with "no such table: firms".
3. **The sample PDF is `Belvidere.pdf`, capital B** — the filesystem is case-sensitive.
4. **client_boq has no frontend.** Do not assume a UI exists; it is curl/Postman-driven today.
5. **Two different "estimators" exist.** `pipeline/estimate/` (procurement, corpus-backed rates) and
   `client_boq/estimate/` (CSV rates, fully independent). They share nothing. Don't cross-wire them.
6. **No auth anywhere, CORS is `allow_origins=["*"]`** (`api.py:163`). Fine locally, unsafe published.
7. **Background jobs live in an in-process dict** (`client_boq/jobs.py`, `api.py::_IngestJobStore`) and
   uploaded files live on local disk under `fixtures/out/`. A restart drops in-flight jobs; losing the
   disk loses artifacts. Nothing is in durable storage.
8. **SQLite is single-writer.** One operator is fine; concurrent writers will hit "database is locked".

---

## 9. Working agreements on this branch

- Develop on **`from-client-to-tender-BOQ`**; **PR #4** is already open for it
  (`https://github.com/weAOKSKDOKAS/SiteSource1/pull/4`) — pushing updates it, don't open another.
- Keep the client_boq footprint outside its own directory at **2 files** (`api.py` mount, `CLAUDE.md` row).
- Run the full suite before committing; it should stay at 678 passed / 8 skipped or better.
