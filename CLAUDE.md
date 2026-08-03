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
| Flow | tender → split by trade → shortlist firms → email enquiries → level bids → award | binder → split into parts (**ingest**) → departure register (**review**) → cost estimate + workbook + offer letter (**estimate**) |
| Code | `siteclaim/backend/pipeline/`, `db/`, `rules_engine/` | `siteclaim/backend/client_boq/` |
| API | ~58 endpoints at root (`/ingest`, `/shortlist`, …) | 59 endpoints under `/client-boq/*` |
| Frontend | Yes — 5 tabs, a 5-step wizard, **Atlas** palette | Yes — a **tender desk** home (multi-tender shelf, team profiles) + Documents · Register · Scope per tender, all hash-routed under `#/tender`, **paper/brass** palette. all five steps have screens, plus Criteria / Rates / AI-model / Team. |

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
- `pipeline.llm_client` — `LLMClient().complete_json(system=, user=, target_model=, demo_fixture=, purpose=)`.
  **One documented additive exception** (2026-07-31, for the app-wide model setting): `_route` now
  honours an EXPLICITLY constructed provider for text calls (`LLMClient(provider=...)`). Every
  procurement site constructs bare `LLMClient()` and routes from env exactly as before — verified
  by `pipeline/tests` — and client_boq applies its setting via `client_boq/llm.py::make_client()`,
  never by mutating env (the job pool runs on threads; a mutable process env is a race).
- `pipeline.documents.extract_document(data, content_type, table_aware=)` — PDF text + page images
- `db.store.get_connection()` — the shared SQLite connection (honours `SITESOURCE_DB`)
- `pipeline.workspace.Workspace` / `tender_slug` — per-tender file storage

**client_boq must NEVER touch:**
- The Gmail path — `gmail_client.py`, `.gmail_token.json`, `reply_poller.py`, `/contacts`, `/dispatch/drafts`.
  client_boq sends no email at all.
- Procurement pipeline stages, `rules_engine/`, `routing/`, `benchmark/`, `pipeline/estimate/`
  (note: that last one is the *procurement* estimator — a different thing from `client_boq/estimate/`).
- `db/schema.sql` and `db/seed.py`. client_boq owns 19 tables it creates lazily itself with
  `CREATE TABLE IF NOT EXISTS client_boq_*` (see `client_boq/models.py`) — the workflow tables
  plus the desk's team/meta/criteria/rates/settings tables.

---

## 5. Inside `client_boq` — the module a new agent will most likely work on

Three sequential workflows separated by human gates. Start at `siteclaim/backend/client_boq/CONTEXT.md`.

```
INGEST                                          REVIEW
inspect       Det   outline, text coverage,      s01 ingest        Det+AI  parts → clauses
                    confidence ladder 1-4        s02 summary       AI      commercial-risk
s01 plan      AI    propose the split            s03 criteria      AI→RULE match + 8 thresholds
              Det   validate bounds/gaps         s04 scope align   AI→RULE precedence (SQD-01)
─── GATE: /ingest/manifest/approve ───           s05 program       AI→Det  LD/mobilisation
cut           Det   slice pages (zero LLM)       s06 cashflow      Det     monthly profile
s02 interpret AI    one context card per part    s07 register      Det     assemble ONE register
                                                 s08 citations     Det     anti-hallucination
                                                 ─── GATE: /review/approve ───
ESTIMATE
s01 scope review   AI draft + register wiring    s03 cost buildup   Det  qty × rate
─── GATE: /estimate/scope/approve ───            s04 indirects      Det  lump/per_week/pct
s02 schedule       Det  normalise                s05 validate       RULE 5 flags
                                                 s06 offer letter   AI prose + injected numbers
                                                 → workbook (.xlsx) + letter (.md)
```

**Four gate rules that must not be broken:**
1. `/ingest/split` 409s until the **split manifest** is approved, and `/review/run` with a
   `set_id` 409s the same way. An edited manifest is validated against the real page count
   before it is stored, so a split that does not fit the document is refused at the gate.
2. `/estimate/scope` 409s until the **review register** is approved.
3. `/estimate/run` 409s until **both** the register *and* the **scope** are approved (distinct messages).
4. The approve endpoints are the **only** writers of `confirmed`/`dismissed` verdicts and the gate flags.
   No stage may write a verdict — `DepartureProposal` (the AI's s03 output model) deliberately has **no
   status field**, so the model structurally cannot. `PlannedSplit` likewise carries no `approved` flag
   and no confidence tier: the planner cannot open its own gate or promote its own confidence.

**Ingest exists to make the review survivable.** A real tender is one 400-page binder;
`review/s01_ingest.py` used to concatenate every uploaded document into a single prompt
against `DEFAULT_MAX_TOKENS = 8000`, while `documents.extract_document` silently stops at
`TEXT_MAX_PAGES = 200`. So half the binder was dropped and the rest truncated. Splitting
first turns that into a dozen ordinary calls, and every clause gains a part and page range
to cite. The pre-ingest path still works for a single loose document with nothing to split.

**Other invariants:** no silent drops (unmatched criteria → `unresolved`, unmatched clauses →
`uncovered`, bad citations → `citation_failed`, all kept visible); every AI call passes a `demo_fixture`
so DEMO is fully offline; heavy work runs as sync `def` on the in-package pool (`jobs.py`).

Key files: `router.py` (59 endpoints) · `models.py` (schemas + table DDL) · `rules.py` (the 8 numeric
threshold rules + precedence + LD math) · `store.py` (persistence + gates) · `criteria_store.py`
(the editable criteria library — DB-backed, seeded once from the markdown via `criteria_loader.py`) ·
`rates_store.py` (the editable rate book — the DB source `rates.py` declared itself the seam for) ·
`llm.py` (`make_client()` — where the app-wide model setting is applied) ·
`ingest/close_date.py` (the close date as a finding: conservative parse of the AI-quoted clause) ·
`ingest/pdfops.py` (pure PDF structure ops — outline walk, text-coverage scan, the confidence
ladder, manifest validation, page slicing; no model, no network).

**The ingest tables**: `client_boq_manifests` (one per set, the tier and the gate flag),
`client_boq_documents` (every file that entered the set, in arrival order — the history's tabs),
`client_boq_parts` (a part's STABLE identity: what it is does not change when it is amended), and
`client_boq_part_revisions` (everything a revision can change, keyed `(set_id, part_id, rev)`).

**The revision rule: nothing is ever destroyed.** A correction or an addendum APPENDS a revision;
Rev 0 survives Rev 1 and stays readable on disk. The operative revision is derived as the highest
`rev`, never stored as a flag that could drift. `store.load_parts()` returns the operative view, so
review and estimate read the current documents without knowing revisions exist;
`load_parts_as_at(seq)` replays the set to any point in its history. Re-splitting after a manifest
edit rewrites the SAME rev — a manifest edit is a better reading of one document, not a new one.

Modelled on the real ND/2025/04 package: 154 documents stayed at Rev 0, 9 went to Rev 1, 2 went to
Rev 2, and each addendum shipped only the replacements it affected. Whole-set snapshots would have
stored the 154 unchanged documents once per addendum.

Note `set_id = slug = tender_slug(name)` is still a pure function of the project name, so a set is
identified by its name; the revisions live below that, per part.

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
cd siteclaim/backend && python -m pytest -q          # 994 passed, 5 skipped
python -m pytest client_boq/tests/ -q                # 320 passed
```

On Windows use the `py` launcher to build the venv (`py -3.14 -m venv .venv` inside
`siteclaim/backend/`, where `scripts/start_backend.bat` already looks for it); a bare `python`
is the Microsoft Store stub. `make` is not available there either — run the Makefile's commands
directly. The 5 skips are the `requires_tesseract` tests and are the expected green state.

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
| `siteclaim/docs/client_boq/build_backlog.md` | What is built, what is not, and every decision behind it |
| `siteclaim/docs/client_boq/citation_locating.md` | You are touching citation verification, or building a document viewer |
| `siteclaim/docs/client_boq/ui_build.md` | You are touching the client_boq frontend, the freeze gate, or the two-palette setup |
| `workspace-tendering/design_handoff_client_boq/README.md` | The design source for that UI — every hex, size and copy string, with the reasoning |
| `BUILD_PLAN.md` | Product strategy — phases A–D, what's a commodity vs the moat |

---

## 8. Traps — things that have already bitten someone here

1. **FastAPI must be 0.115.6.** Later versions make `include_router` *lazy* — `app.routes` then holds
   an `_IncludedRouter` wrapper and 13 route-registration tests fail. `requirements.txt` is now pinned
   to a verified-green set, so a fresh install is reproducible; if route tests fail mysteriously, check
   the installed version before debugging the code. Assert against `app.openapi()`, never `app.routes`,
   in new tests.
1b. **`pytesseract` without the system `tesseract` binary is worse than neither.** The OCR layer treats
   that combination as a configuration fault and raises `OcrEngineUnavailable` **loudly** by design
   (never silently swallowed), which fails 7 tests in `test_documents.py` and `test_doc_index.py`. It is
   correct behaviour, not a bug. `pytesseract` is therefore commented out in `requirements.txt`: install
   it only together with the binary. With neither installed, scanned pages degrade to vision and the
   suite is green with 5 skips.
1c. **Some tests assert that optional packages are ABSENT.** `test_gmail_client.py` asserted
   `state == "no_libs"`, which fails once the (declared, legitimate) `google-*` packages are installed.
   It now accepts either state and asserts the thing it is actually about. Watch for this pattern if you
   add optional dependencies: the environment is not the subject of the test.
2. **Never let a test or a manual probe write `db/sitesource.db`.** It is committed. client_boq tests
   isolate via a temp `SITESOURCE_DB` (`client_boq/tests/conftest.py`) and there is a hygiene test
   asserting byte-identity. Procurement code reads the real DB, so pointing `SITESOURCE_DB` at an empty
   file breaks `/coverage` with "no such table: firms".
3. **The sample PDF is `Belvidere.pdf`, capital B** — the filesystem is case-sensitive.
3b. **A bare `store.get_conn()` outside DEMO_MODE writes to the COMMITTED db.** `client_boq`
   creates its tables lazily with `CREATE TABLE IF NOT EXISTS` on every connection, so merely
   *opening* a connection in a throwaway script adds 13 empty `client_boq_*` tables to
   `db/sitesource.db` — which is a procurement-only database. No data is lost and the tests still
   pass (they isolate via a temp `SITESOURCE_DB`), but the committed file stops being the file that
   shipped. This has happened once, on 2026-07-31; it was first repaired by hand (dropping the
   empty tables and vacuuming, which restores the data but not the bytes) and then fully undone
   with `git checkout -- siteclaim/backend/db/sitesource.db` once the working copy was under
   version control. **Always set `DEMO_MODE=true` before running an ad-hoc script that touches the
   store.** If it happens again, `git checkout --` that one path; a hand repair is only the fallback
   when the file is not tracked.
4. **The frontend hosts TWO products with TWO palettes.** `main.tsx` branches on `location.hash`:
   `#/tender` renders client_boq (`src/client_boq/`, warm paper/brass), anything else renders
   procurement (Atlas, cool navy/blue). Every client_boq token is `cb-` prefixed because the names
   genuinely collide (`--color-paper` is `#eef2f7` in Atlas and `#FAF9F6` here). **A `@theme` block
   only generates utilities if it reaches the ROOT stylesheet** — `client_boq/tokens.css` is imported
   from `src/index.css` for that reason, and importing it from a `.tsx` instead renders the whole app
   unstyled with no error.
5. **Two different "estimators" exist.** `pipeline/estimate/` (procurement, corpus-backed rates) and
   `client_boq/estimate/` (CSV rates, fully independent). They share nothing. Don't cross-wire them.
6. **No auth anywhere, CORS is `allow_origins=["*"]`** (`api.py:163`). Fine locally, unsafe published.
7. **Background jobs live in an in-process dict** (`client_boq/jobs.py`, `api.py::_IngestJobStore`) and
   uploaded files live on local disk under `fixtures/out/`. A restart drops in-flight jobs; losing the
   disk loses artifacts. Nothing is in durable storage.
8. **SQLite is single-writer.** One operator is fine; concurrent writers will hit "database is locked".
9. **A DEMO fixture can silently paper over an honest-degradation path.** `ingest/s02_interpret.py`
   returned its fixture *before* checking whether the part was readable, so in DEMO a scanned part
   came back with a confident summary claiming it had been read — fabricating content for pages
   nobody had seen, which is the exact failure that stage exists to prevent. Fixed by measuring
   first in every mode. When writing any new AI stage: **read the input deterministically, THEN
   decide whether the fixture applies.** A measurement outranks a fixture and outranks a model
   proposal. Full rule in `siteclaim/backend/client_boq/CONTEXT.md`.

---

## 9. Working agreements on this branch

- Develop on **`from-client-to-tender-BOQ`**; **PR #4** is already open for it
  (`https://github.com/weAOKSKDOKAS/SiteSource1/pull/4`) — pushing updates it, don't open another.
- Keep the client_boq footprint outside its own directory minimal: `api.py` (the mount), the
  documented additive `pipeline/llm_client.py` change (§4), `frontend/src/main.tsx` (the hash
  branch), `frontend/src/index.css` (the token import), and the docs.
- Run the full suite before committing; it should stay at **994 passed / 5 skipped** or better.
  (The 5 skips are `requires_tesseract` — see trap 1b. An older figure of 678/8 predates the
  client_boq module and is no longer the bar.)
