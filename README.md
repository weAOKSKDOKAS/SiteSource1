# SiteSource

Two construction products on one FastAPI backend, sharing a chassis but almost no business
logic.

| | **Procurement** | **client_boq** |
| --- | --- | --- |
| Direction | contractor sources work **out** to subcontractors | the client's contract comes **in** to the contractor |
| Flow | tender → split by trade → shortlist firms → email enquiries → level bids → award | binder → **ingest** → departure register (**review**) → cost estimate, workbook and offer letter (**estimate**) |
| Code | `siteclaim/backend/pipeline/`, `db/`, `rules_engine/` | `siteclaim/backend/client_boq/` |
| API | ~58 endpoints at the root | 59 endpoints under `/client-boq/*` |
| Frontend | yes, a 5-tab wizard | yes — a tender-desk home + all five steps (Documents · Register · Scope · Price · Offer), at `#/tender` |

The governing principle in both: **the LLM reads, structures, proposes and drafts;
deterministic code and human gates decide.** No price, verdict, risk flag, or document
boundary is ever committed by a model alone.

`CLAUDE.md` is the deeper orientation — the repo map, the module boundary, and the traps.
Read it before changing anything.

## Quickstart (Windows)

Python here is the **`py` launcher**; a bare `python` is the Microsoft Store stub and will
not work. `make` is not installed either, so the Makefile targets are spelled out below.

```powershell
cd siteclaim\backend
py -3.14 -m venv .venv                 # scripts\start_backend.bat looks for it here
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

python -m pytest -q                    # 994 passed, 5 skipped
$env:DEMO_MODE="true"; python -m uvicorn api:app --port 8000
```

Then open `http://localhost:8000/docs`. The frontend is
`cd siteclaim\frontend; npm install; npm run dev` on `:5173` — **one app, two products**:
`localhost:5173` is procurement, `localhost:5173/#/tender` is the tender-review product.

DEMO mode is fully offline: every AI call short-circuits to a baked fixture, so it needs no
API key and opens no socket.

### Things that will bite you

- **Run everything from `siteclaim\backend\`.** There is no `pytest.ini` or `pyproject.toml`,
  so imports resolve only from that directory, and only via `python -m pytest` (which puts
  the working directory on `sys.path`). A bare `pytest`, or the same command one level up,
  fails at collection.
- **Do not set `SITESOURCE_DB`** in your shell. The procurement tests read the committed
  `db/sitesource.db`; pointing it at an empty file breaks them.
- **Do not run the seed.** Both databases are committed. A DEMO run writes to a gitignored
  scratch DB, and a hygiene test asserts the committed one stays byte-identical.
- **Set `DEMO_MODE=true` before any ad-hoc script that opens the store.** `client_boq` creates
  its tables lazily, so merely opening a connection without it adds empty `client_boq_*` tables
  to the procurement-only `db/sitesource.db`. See `CLAUDE.md` trap 3b.
- **FastAPI is pinned to 0.115.6** and must stay there — see `CLAUDE.md` section 8.
- **5 tests skip by design.** They need the system `tesseract` binary. Installing the
  `pytesseract` package *without* that binary is worse than not installing it at all: the OCR
  layer then raises loudly by design and 7 tests fail. See the notes in
  `siteclaim/backend/requirements.txt`.

## Live mode

DEMO and LIVE are a real code fork on `demo_mode()`, not the same code with different config.
Green tests prove the deterministic engine and the data contracts; they prove nothing about
the live model path.

```
# siteclaim/backend/.env   (auto-loaded by api.py; copy .env.example)
DEMO_MODE=false
EXTRACTION_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...
ANTHROPIC_MODEL=claude-opus-5      # optional; the code default is claude-sonnet-4-6
```

## The client_boq flow, end to end

```
GET  /client-boq/sets                     -> every tender, with its part count and gate states
POST /client-boq/ingest/upload            -> a DRAFT split manifest (nothing is cut yet)
POST /client-boq/ingest/manifest/approve  -> GATE 1: the human owns the split
POST /client-boq/ingest/split             -> parts on disk, with an interpreted card each
GET  /client-boq/ingest/{id}/download     -> the split as a zipped folder tree
POST /client-boq/review/run    {set_id}   -> the departure register
POST /client-boq/review/approve           -> GATE 2: confirm / dismiss / query each line
POST /client-boq/rfi  ·  /rfi/batch       -> raise queries, send them as one numbered letter
POST /client-boq/ingest/document          -> an addendum arrives (a correction, a clarification)
POST /client-boq/ingest/changes/approve   -> GATE 4: which parts it supersedes; bumps revisions
POST /client-boq/estimate/scope           -> the scope draft
GET  /client-boq/estimate/scope/{id}/sources -> what the scope COULD be built from (derived)
POST /client-boq/estimate/scope/map       -> map one source in; nothing enters the scope alone
POST /client-boq/estimate/scope/item      -> edit / accept a fallback / take ownership
POST /client-boq/estimate/scope/approve   -> GATE 3 (FREEZE): the human owns the scope of record
POST /client-boq/estimate/run             -> the priced estimate
GET  /client-boq/estimate/{id}/workbook   -> .xlsx
GET  /client-boq/estimate/{id}/letter     -> the offer-letter draft
GET  /client-boq/review/{id}/citations            -> where each quotation sits, measured
GET  /client-boq/review/{id}/departure-schedule   -> terms we do not accept (md / xlsx)
GET  /client-boq/estimate/{id}/qualifications     -> the assumptions the price rests on
GET  /client-boq/revisions/{id}[/workbook]        -> the document history, and its .xlsx
GET  /client-boq/ingest/parts/{id}/{part}/page/{n}.png  -> a rendered page, for the viewer
GET  /client-boq/ingest/parts/{id}/{part}/search?q=     -> find text, with the same rectangles

# The tender desk (the home screen) and its management surfaces:
GET/POST /client-boq/team           -> named profiles (attribution, deliberately not auth)
POST /client-boq/sets/{id}/meta     -> owner / client / package / archive / outcome
POST /client-boq/sets/{id}/close-date -> a person confirms the date the parser refused to guess
GET/POST /client-boq/criteria[/{id}]  -> the editable criteria library (disable, never delete)
GET/POST /client-boq/rates[/{id}]     -> the editable rate book (archive -> missing_rate, honest)
GET/POST /client-boq/settings         -> the app-wide AI model choice
```

Every gate refuses with a distinct 409 until it is passed. That is deliberate: the point of
the tool is that a person signs off each stage, not that it runs unattended.

**The two client-facing documents are internal by default.** Both reference tenders warn that
qualifying a bid "may cause the tender to be disqualified", so the Departure Schedule and Letter
of Qualifications are working papers unless you ask for `?audience=submission`, which adds the
tender's own clause as a warning. Ingest flags that rule when it finds it, because the safe route
for a problem clause is a written query before the cut-off, not a qualification with the bid.
