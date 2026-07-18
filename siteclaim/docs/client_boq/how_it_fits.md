# How client_boq fits beside the original SiteSource

A one-page orientation: what the original product does, how the client_boq module sits
next to it, where they touch, and what client_boq deliberately leaves alone.

---

## (a) How the original SiteSource works, end to end

SiteSource is a **subcontractor-sourcing and bid-leveling** platform for a main
contractor. A person drives it through a five-step wizard in the browser; a FastAPI
backend (`backend/api.py`) runs a five-stage pipeline, calling the Claude/DeepSeek API
only where a document has to be *read*, and doing every decision in deterministic code.

1. **Ingest** (`pipeline/stage_01_ingest/`) — the operator uploads a tender package; the
   AI reads it and splits the scope by trade into `ScopePackages`. The heavy extraction
   runs as a **background job** (`/ingest-upload` → poll `/ingest-status`).
2. **Shortlist** (`pipeline/stage_02_shortlist/`) — the scope is cross-referenced against
   the proprietary firm database (`backend/db/`) to rank subcontractors with cited risk
   evidence. Pure deterministic Layer 1.
3. **Dispatch** (`pipeline/stage_03_dispatch/`) — after a human approves, each firm gets
   the relevant document bundle + a composed enquiry, as a **Gmail draft**
   (`pipeline/gmail_client.py`). A human gate holds before anything sends.
4. **Level** (`pipeline/stage_04_level/`) — subcontractors' priced replies come back
   (inbound Gmail poller or manual upload), and the engine normalises scope, recomputes
   every amount, and exports an Excel comparison.
5. **Recommend** (`pipeline/stage_05_recommend/`) — a risk-adjusted ranking; the human
   makes the final award.

Uploaded originals and per-tender artifacts live on disk in a `Workspace`
(`pipeline/workspace.py`), keyed by a deterministic slug of the tender name. `DEMO_MODE`
runs the whole thing offline on fixtures.

## (b) How client_boq sits beside it, and every point they touch

client_boq is a **different capability on the same chassis**: instead of sourcing
subcontractors *out*, it processes the client's tender/contract set *in* — first
**REVIEW** (contract → approved departure register), then **ESTIMATE** (approved context
→ cost build-up). It reuses the chassis but shares no procurement business logic. The
touch points — all additive — are:

- **`backend/api.py`** — one line, `app.include_router(client_boq_router)`, mounts the
  module under `/client-boq`. *Why unavoidable:* FastAPI only serves routes that are
  registered on the app; without this include the module's endpoints return 404. Nothing
  else in `api.py` changes.
- **`backend/pipeline/documents.py` + `pipeline/ocr.py`** — reused *by import* for
  PDF/OCR text extraction in REVIEW s01. *Why:* re-implementing extraction would
  duplicate tested chassis code. Imported, never modified.
- **`backend/pipeline/llm_client.py`** — reused *by import* for every AI stage
  (`complete_json`, strict-schema JSON). *Why:* it is the single sanctioned LLM seam
  (DEMO fixtures, provider routing, retries). Imported, never modified.
- **`backend/db/store.py`** — reused *by import* for `get_connection()` only. The module
  then creates its **own** `client_boq_*` tables (lazy `CREATE TABLE IF NOT EXISTS`).
  *Why:* one connection helper, honouring `SITESOURCE_DB`, avoids a second DB stack.
- **`backend/fixtures/cases/client_boq/`** — DEMO fixtures for the AI stages. *Why:*
  `complete_json` resolves `demo_fixture` paths relative to `backend/fixtures/`, so the
  offline path only works if they live here.
- **`siteclaim/CLAUDE.md`** — one routing-table row pointing at the module. *Why:* the
  map has to name the module or it is invisible to the next reader.

Everything else the module needs is inside `backend/client_boq/`.

## (c) What client_boq deliberately does NOT touch

- **The Gmail path** — `pipeline/gmail_client.py`, `.gmail_token.json`, `/contacts`,
  `/dispatch/drafts`, the reply poller/loop. client_boq sends no email in v1.
- **The procurement pipeline** — `stage_01`…`stage_05`, `pipeline/routing/`,
  `rules_engine/`. Not imported, not modified.
- **Existing DB tables** — nothing in `db/schema.sql` is altered; `schema.sql` and
  `seed.py` are untouched. Only new `client_boq_*` tables are added, lazily.
- **The existing procurement estimator** — `pipeline/estimate/`, `db/estimate.py`,
  `schemas/estimate.py`, `EstimatorPage.tsx`. The client_boq estimate is fully
  independent (hand-edited CSV rates, its own schemas, its own tables) and shares no
  import, table, or schema with it.
