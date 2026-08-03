# Running a real tender (LIVE mode)

**DEMO cannot review your document.** That is not a bug and no amount of UI work changes it: in
DEMO every AI call short-circuits to a baked fixture *before any provider code runs*, and the
review fixture describes a fictional "Harbour Crest Residences" subcontract. So the register you
see offline cites clause 8.3 of a document that is not on your screen, nothing can be located, and
no quotation is highlighted. The app now says so in a banner rather than looking broken.

To review **your** tender, run LIVE.

---

## 1. Supply a key

`siteclaim/backend/.env` is gitignored and does not exist yet. Create it from the template:

```powershell
cd siteclaim\backend
copy .env.example .env
```

Then edit `.env`:

```
DEMO_MODE=false
EXTRACTION_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...
# ANTHROPIC_MODEL=claude-opus-5      # optional; the code default is claude-sonnet-4-6
```

**Never commit this file.** `api.py` loads it automatically at startup.

## 2. Start on something small first

The live model path had never been executed end to end before this build, and a 411-page binder is
an expensive way to discover a schema mismatch. Ingest one part-sized document first — the CIC
Conditions of Tender at 12 pages is ideal — and only then run the full binder.

```powershell
cd siteclaim\backend
.\.venv\Scripts\python.exe -m uvicorn api:app --port 8000
```

The app bar's amber **DEMO — UPLOADS NOT READ** chip disappears when the backend is live. That chip
is the fastest way to tell which mode you are actually in.

## 3. What changes

| | DEMO | LIVE |
|---|---|---|
| Uploads | not read; every finding is canned | read; findings are about your document |
| Register clauses | a fictional subcontract | your parts, with real clause ids |
| Citation highlight | nothing to highlight, and the banner says so | the quotation is located and drawn on the page |
| Jobs | run inline, return instantly | run on a pool thread; the app polls and shows a progress strip |
| Cost | free | you are paying per call |

## 4. Expect first-contact breakage

`CLAUDE.md` records that the live path had never been run. The two places most likely to fail:

- **`review/s01_ingest` chunking** on a large part — the chunk boundary logic has only ever been
  exercised against fixture-sized text;
- **the strict-Pydantic retry** in `llm_client` — a model response that misses the schema twice
  becomes a job error, which the UI now surfaces rather than swallowing.

Both appear as an error banner naming the stage. Neither corrupts anything: a failed job leaves the
set exactly as it was, and re-running is free apart from tokens.

## 5. Jobs, and why the UI needed changing for this

In DEMO every endpoint returns `{status: "done", result: …}` inline. In LIVE the same endpoints
return `{status: "queued", job_id}` and the work happens on a background thread.

The first version of this UI read `.result` off the first response. That worked perfectly offline
and did **nothing at all** with a real key — the screen simply never updated. Every job-starting
call now goes through `runJob()` in `client_boq/api.ts`, which polls to completion in LIVE and
passes straight through in DEMO. If you add a new job endpoint, use `runJob` — a bare call will
appear to work right up until someone runs it live.

The progress strip under the step strip shows the stage and, for the split, per-part progress
(`interpreting 7/12`).
