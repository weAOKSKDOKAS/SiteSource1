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

## 4. What the first real run actually found (2026-08-01)

The live path had never been executed before this date. It has now, on the real CIC Conditions of
Tender (12 pages, cut from the 411-page binder), with `deepseek-v4-flash` for text and
`claude-sonnet-5` for vision. **It works.** Four things are worth knowing before you run yours.

### a. A reasoning model changes what `max_tokens` means

The first call failed instantly and confusingly:

```
plan-split        76.8s  in=901  out=8000   <- the ceiling, exactly
plan-split-retry  79.3s  in=935  out=8000   <- and again
-> 1 validation error for PlannedSplit: Invalid JSON: EOF while parsing at line 1 column 0
```

`deepseek-v4-flash` is a **reasoning model**. Its chain of thought is billed as completion tokens
and is returned in `reasoning_content`, not `content` — so a hard prompt spends the entire budget
thinking and answers with an empty string. Measured directly: at `max_tokens=600` it produced
2,175 characters of reasoning and `content=''` with `finish_reason='length'`; the same prompt at
8,000 used 3,240 tokens and answered correctly.

`DEEPSEEK_MIN_MAX_TOKENS` (default 32,000) is the fix — reasoning headroom, so a documented budget
means the same thing on both providers. Raise it if you see `CompletionTruncated`, or set
`DEEPSEEK_MODEL` to a non-reasoning model. **It is load-bearing**: the review's first chunk used
19,801 output tokens and could not have completed under the old ceiling.

### b. Reasoning is slow, and the retry doubles it

| stage | wall time | out tokens |
|---|---|---|
| plan the split | 147 s | 14,807 |
| interpret the part | 48 s + **68 s retry** | 5,996 + 8,663 |
| review, chunk 1 | 153 s | 19,801 |
| review, chunk 2 | 122 s + **140 s retry** | 16,398 + 17,311 |
| criteria match | 145 s | 17,878 |

**12 pages took ~17 minutes.** The strict-JSON corrective retry fired on two of five stages, so
budget for it. A 411-page binder is not this times ten — ingest chunks per part — but it is hours,
not minutes, on a reasoning model.

### c. The planner will propose a bad split, and the gate is why that is survivable

On this 12-page extract the planner proposed **two parts both covering page 1**. Everything
downstream then read the title page: identical summaries, no strategy flags, empty register lines,
zero citations.

The deterministic layer had already measured it:

```
coverage : 2 of 12 pages
overlaps : p.1 claimed by parts [1, 2]
tier     : 4 — "no bookmarks, contents page, or divider pages found"
```

**This is the design working.** A measurement outranks a model proposal, the manifest gate is a
*human* gate, and the Documents tab shows that coverage bar precisely so nobody approves a split
covering one page in twelve. Look at it before you approve. Editing the split at the gate and
re-running produced the real result below.

Tier 4 is also honest about the input: a slice cut out of a binder has no bookmarks, contents page
or dividers for the planner to work from. The full binder reaches tier 1.

### d. With a correct split, it reviews your document

```
75 register lines, 18 carrying a quotation
counts: candidate 7 · uncovered 53 · citation_failed 15 · unresolved 26
citations: 71 -> 56 LOCATED with rectangles across 8 pages, 15 unverifiable
parse mismatch: None
```

The quotations are verbatim CIC text against real clause numbers — 1.2(d), 4.4(b), 4.18, 4.22,
4.25, 3.1 — and they highlight on the page, which is the one thing DEMO structurally cannot show.
`parse_mismatch: None` is the mismatch banner correctly staying silent because the findings really
are about the uploaded file.

Read the other numbers honestly too: **53 uncovered** clauses matched no criterion and **15
citations could not be verified**, both kept visible rather than dropped. That is the no-silent-drops
rule doing its job, and it is also a fair signal of this model's precision — a stronger text model
should move those numbers.

### e. Ten "failed" citations that were not failures — fixed 2026-08-02

The run above reported 10 of 75 lines as citing a clause "not in the document set". Every one was a
formatting mismatch, not a missing clause: a document-name prefix (`CIC Conditions of Tender,
Clause 4.13`), several clauses in one reference (`8.1; 2.3; 10.1`), or a sub-clause limb (`4.4(b)`)
where the index keys the parent (`4.4`). The tell: clause 4.13 resolved from one stage and failed
from another, in the same register.

Both halves of the guard were adjusted, and neither was weakened:

- the **lookup** expands a reference into every id it might mean;
- the **containment** check splits a composite quotation on its ellipsis and requires each fragment
  to appear in the clauses that line cites — because a finding about a conflict quotes from several
  clauses at once, and asking whether all of it sits in one has no right answer.

An invented fragment is still in none of them and still fails. On this register `citation_failed`
fell **10 → 3**, and those three name the fragment that is genuinely absent.

**If you re-run this tender, expect ~3 failures rather than 10.** The counts in section 4 are from
before the fix.

## 5. Your `.env` and the test suite

`api.py` loads `.env` at import, so before 2026-08-01 creating one made **10 tests fail** — they
inherited `DEMO_MODE=false`, a redirected `SITESOURCE_DB` and a different `ANTHROPIC_MODEL`.
`backend/conftest.py` now sets `SITESOURCE_SKIP_DOTENV=1` before any test module imports `api`, so
the suite is hermetic and configuring LIVE cannot change what the tests assert.

**Do not point `SITESOURCE_DB` at a committed database.** `db/sitesource.db` and
`db/sitesource_live.db` are both tracked, and `client_boq` creates its 19 tables lazily on any
connection — a live run would write real rows into a file git is watching. Point it at something
under the gitignored `fixtures/out/`:

```
SITESOURCE_DB=fixtures/out/live_run.db      # a copy of sitesource_live.db
SITESOURCE_LLM_LOG=fixtures/out/llm_calls.jsonl
```

That log is worth having: one JSON line per call with provider, model, purpose, ms and tokens. Every
number in section 4 came from it.

## 6. Jobs, and why the UI needed changing for this

In DEMO every endpoint returns `{status: "done", result: …}` inline. In LIVE the same endpoints
return `{status: "queued", job_id}` and the work happens on a background thread.

The first version of this UI read `.result` off the first response. That worked perfectly offline
and did **nothing at all** with a real key — the screen simply never updated. Every job-starting
call now goes through `runJob()` in `client_boq/api.ts`, which polls to completion in LIVE and
passes straight through in DEMO. If you add a new job endpoint, use `runJob` — a bare call will
appear to work right up until someone runs it live.

The progress strip under the step strip shows the stage and, for the split, per-part progress
(`interpreting 7/12`).
