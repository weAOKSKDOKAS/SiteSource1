# SiteSource

Two construction products on one FastAPI backend. Everything below lives under
`siteclaim/`; the repo root holds only `README.md`, `CLAUDE.md` and `BUILD_PLAN.md`.

- **Procurement** (`backend/pipeline/`) — a contractor sources work **out**: a tender is
  ingested and split by trade, firms are shortlisted from the proprietary database,
  enquiries go out by email, bids come back and are levelled, and an award is recommended.
  Five numbered stages; it owns the React frontend.
- **client_boq** (`backend/client_boq/`) — the client's contract comes **in**: a tender
  binder is ingested and split into parts, reviewed into a departure register, and priced
  into an estimate with a workbook and an offer letter. Three gated workflows; no frontend
  yet, driven over HTTP.

The guiding principle in both: **the LLM reads, structures, proposes and drafts;
deterministic code and human gates decide.** No price, verdict, risk flag, or document
boundary is ever committed by a model alone.

`CLAUDE.md` is the architecture (the four layers, the module boundary, the traps).
`CONTEXT.md` is the procurement stage routing table.
`backend/client_boq/CONTEXT.md` is the client_boq stage map.

## Run the demo (offline)

Requires **Python 3.11+** (verified on 3.14) and **Node 18+**. DEMO mode is fully offline:
every AI call short-circuits to a baked fixture, so it needs no API key and opens no socket.

On Linux/macOS, from `siteclaim/`:

```bash
make install     # backend + frontend dependencies
make demo        # API (DEMO_MODE) on :8000 + wizard on :5173, zero network
make test        # the backend suite
```

On Windows, `make` is unavailable and a bare `python` is the Microsoft Store stub, so run
the commands directly with the `py` launcher:

```powershell
cd backend
py -3.14 -m venv .venv                 # scripts\start_backend.bat looks for it here
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m pytest -q                    # 798 passed, 5 skipped
$env:DEMO_MODE="true"; python -m uvicorn api:app --port 8000
```

Then `cd frontend; npm install; npm run dev` for the procurement wizard on `:5173`, or open
`http://localhost:8000/docs` to drive either product directly.

**Run pytest and uvicorn from `backend/`.** There is no `pytest.ini` or `pyproject.toml`, so
imports resolve only from that directory and only via `python -m pytest`. (Note the
Makefile's `seed` target contradicts this — it is written to run from `siteclaim/`.)

## Live mode

DEMO and LIVE are a real code fork on `demo_mode()`, not the same code with different
config. Green tests prove the deterministic engine and the data contracts; they prove
nothing about the live model path.

```
# backend/.env  (auto-loaded by api.py; copy from .env.example)
DEMO_MODE=false
EXTRACTION_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...
# DEEPSEEK_API_KEY=sk-...        # optional; text-only calls route here when set
```

Provider routing lives in one place, `backend/pipeline/llm_client.py`: anything carrying
images goes to Anthropic, text-only goes to DeepSeek when a key is present. `openai`,
`anthropic` and `pymupdf` are imported lazily, so DEMO never loads them.

## Architecture

An **ICM (Interpreted Context Methodology) workspace**: the folder structure *is* the
architecture. Stages hand off **plain typed data** (Pydantic models) — no agent framework,
no shared mutable memory. A stage reads typed objects, does its work, and writes the next
object; a stage boundary can be an in-process call, a file, or an HTTP payload, and the
contract is identical.

### Four layers

1. **Rules engines** (`backend/rules_engine/`, `backend/client_boq/rules.py`) — pure,
   deterministic Python. Arithmetic and thresholds live here. No LLM imports.
2. **The model** (`backend/pipeline/llm_client.py`) — reads messy documents, structures
   them, proposes and drafts. It never writes a decision value.
3. **Grounding** (`backend/db/`, `backend/references/rubrics/`,
   `backend/docs/client_boq/review_criteria.md`) — the proprietary firm database, the
   trade taxonomy and levelling rubrics, the acceptable-terms criteria library.
4. **Human gates** — a person reviews and edits at every gate; the API has one endpoint per
   stage, with no monolithic `/run`, precisely so a human can edit between every step.

### Procurement — five stages (`backend/pipeline/`)

| # | Stage | Consumes | Produces |
| - | ----- | -------- | -------- |
| 01 | `ingest` | `TenderPackage` | `ScopePackages` |
| 02 | `shortlist` | `ScopePackages` + database | `ShortlistSet` |
| 03 | `dispatch` | `ShortlistSet` + approvals | `DispatchSet` |
| 04 | `level` | `BidReplies` + `ScopePackages` | `LevelledBids` |
| 05 | `recommend` | `LevelledBids` + database | `Recommendation` |

Flow is strictly forward. A fatal risk flag demotes a firm regardless of price, and no
award leaves stage 05 without explicit human sign-off.

### client_boq — three gated workflows (`backend/client_boq/`)

```
ingest    inspect -> plan the split (AI) -> [GATE] -> cut (Det) -> interpret each part (AI)
review    read the parts -> criteria match -> assemble one register -> [GATE] verdicts
estimate  scope draft -> [GATE] -> cost build-up (Det) -> workbook + offer-letter draft
```

Each gate refuses with a distinct 409 until it is passed. Ingest exists because the review
could not otherwise survive a real tender: a 400-page binder in one prompt overran both the
output ceiling and the 200-page extraction cap, so it is split first and read a part at a
time.

## Workspace layout

```
siteclaim/
├── CLAUDE.md            architecture + the traps (read first)
├── CONTEXT.md           procurement stage routing
├── DEMO.md              procurement demo runbook
├── Makefile             make demo / test / install / build-frontend
├── backend/
│   ├── api.py                     FastAPI — one endpoint per stage, + /health
│   ├── schemas/models.py          the typed contracts the procurement stages pass
│   ├── rules_engine/              deterministic levelling, ranking and risk
│   ├── pipeline/                  procurement stages 01-05
│   │   ├── llm_client.py          the ONLY LLM seam (both products use it)
│   │   ├── documents.py           PDF text + page images (both products use it)
│   │   └── workspace.py           per-tender file storage (both products use it)
│   ├── client_boq/                ingest/ review/ estimate/ + router, models, store
│   ├── db/                        the proprietary firm database + schema + seeds
│   ├── references/rubrics/        trade taxonomy, levelling and risk rubrics
│   └── fixtures/                  DEMO fixtures (cases/) + out/ (gitignored artifacts)
├── docs/                          EMAIL_SETUP, QUICKSTART, PRODUCT_ARCHITECTURE, client_boq/
└── frontend/            React + TS + Vite + Tailwind — PROCUREMENT ONLY
```

## Notes

- **Do not set `SITESOURCE_DB`** in your shell, and **do not run the seed**. Both databases
  are committed; a DEMO run writes to a gitignored scratch DB and a hygiene test asserts the
  committed one stays byte-identical.
- **FastAPI is pinned to 0.115.6.** Later versions make `include_router` lazy and break the
  route-registration tests. See `CLAUDE.md` section 8.
- **5 tests skip by design** — they need the system `tesseract` binary. Read the notes at the
  bottom of `backend/requirements.txt` before installing `pytesseract`: the package without
  the binary is worse than neither.
