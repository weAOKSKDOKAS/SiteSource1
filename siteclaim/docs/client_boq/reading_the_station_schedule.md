# Reading the station schedule — research before building

**Status:** research complete, nothing built yet. Written 2026-08-11.
**Subject:** `POST /client-boq/site/schedule` accepts a `StationSchedule`. Nothing in this repository
produces one. This is the report on what it would take, and what cannot be settled here.

---

## 0. The finding that reframes the question

The brief says the reader "does not exist". That is true, and it is the smaller half.

The larger half: **the schedule has no way in at all.** Not a missing reader — a missing *door*.

- `grep -rn "site/schedule" siteclaim/frontend/src/` → **zero matches.** `api.ts:366` exposes the GET
  (`stationSchedule`) and there is no POST wrapper. There is no paste box, no upload, no editor.
- `grep -rn "StationSchedule(" --include=*.py`, minus `/tests/` → **one hit**, the `class` statement at
  `boq/schedule.py:100`. No production code has ever constructed one.
- `save_station_schedule` has exactly two callers: its own definition (`store.py:723`) and the endpoint
  (`router.py:3781`).
- `fixtures/out/client_boq_demo.db`: `select count(*) from client_boq_station_schedules` → **0**.

So a schedule can only arrive as hand-authored JSON on the raw HTTP API, exactly as
`test_boq_site.py:56-60` does it. `Site.tsx:117` renders a `WaitingOn` with no button, no upload and no
editor, and `_schedule_or_404` (`router.py:3611-3616`) answers *"Read it off the borehole details
drawing (GI/210 on the reference contract) and save it first"* — an instruction the app gives no means
of following.

**Consequence for sequencing: the door is worth more than the reader, and is independent of it.** A
typed or pasted schedule unblocks everything below; a machine-read schedule then arrives through the
same door as a *proposal*. Building the reader first would be building a producer with no consumer that
a human can reach.

### What is blocked today, traced

| Blocked | Mechanism |
| --- | --- |
| **The independent check on the client's quantities** — `derive.py` | `router.py:3802` `_schedule_or_404` → 404. Also never requested: `Site.tsx:79` skips the call when `stations` is empty |
| Sheet georeferencing | `router.py:4013` → 404 |
| The station table, `bad_rows`, totals | `Site.tsx:117` returns above the whole render tree |
| Map / positions / access board | 200 with `waiting_on`; `AccessMap.tsx:76-83`'s purpose-written empty state is **unreachable** |
| **Hole classification (the A/B/C decision)** | `HolesView` is the app's only writer of a class, and it sits behind the gate |
| Group measured facts | `summarise` skipped → groups store with `soil_m`/`rock_m`/`deepest_m` at zero, and `ready()` (`groups.py:107-118`) then passes trivially: a group that measures nothing looks ready |
| Rate-trace divisor provenance | `trace.py:226-233` returns `""` — the one degradation that is **silent** rather than stated |
| **The sweep's unclassed-hole refusal** | `router.py:4262` `if schedule is not None:` — with no schedule there are no holes, so none are unclassed, so nothing refuses |
| **The Price chip's `⚠ N HOLES UNASSIGNED`** | `App.tsx:914-916` computes 0 over an empty list; `chrome.tsx:161-163` never fires |

The last two are the sharp ones. The design is deliberate — *"Site has no gate; the sweep is what
refuses"* (`Site.tsx:9-11`, `router.py:3577-3579`) — but **the compensating refusal is conditional on
the very artefact whose absence is the problem.** A tender can be settled and priced with the
access-class safety net silently absent rather than tripped, and §1 above establishes there is no path
by which those classes could have been supplied.

`next.tsx:31-119 nextFor` also never reads `data.site`. The app's single "what now?" line routes a user
straight past the take-off to "build the price".

---

## Q1 — What are the DRG PDFs really?

**Cannot be determined from this repository. No drawing has ever existed here.**

`git ls-files '*.pdf' '*.png' '*.jpg' '*.xlsx' '*.tif'` returns exactly one file:
`fixtures/samples/Belvidere.pdf` (6,274,993 B). `git log --all --diff-filter=ADM --name-only` over the
same globs plus `*.dwg` returns one commit touching that same path. Root `.gitignore:5` is `*.png`, so
no PNG can be committed at all.

Belvidere is the wrong document twice over: born-digital Word output with a full text layer
(~1,569 chars/page — the *opposite* of the flattened raster the real sheets are, so it exercises none
of the code path a reader needs), and a Canadian municipal park tender with
`borehole 0 · drillhole 0 · standpipe 0 · piezometer 0 · easting 0 · northing 0 · rockhead 0`. Its
largest raster is **1322×1007**, a location map embedded in Word prose. Reading a 91-row table off an
A1 sheet needs roughly ten thousand pixels on the long edge.

**What the repo's own documentation asserts** (this is testimony from an earlier reading, not evidence
in the tree):

- `build_backlog.md:810-813` — *"An earlier pass concluded all 33 sheets were useless because
  `get_text()` returns 29 characters — true, and the wrong test. They are flattened raster… Rendered at
  420 dpi and read with vision they are crisp."*
- `build_backlog.md:814-817` — **GI/210 is the station schedule**: one row per borehole with easting,
  northing, ground level, rockhead, total depth, tentative length in soil, expected length in rock,
  standpipe ✓, piezometer ✓ — plus a second table of 21 trial pits.
- `prd_boq_costing.md:117-119` — the inventory is **33** drawings, not 35. GI/200-205 engineering,
  GI/301-303 environmental, GI/210 and GI/310 the coordinate tables, GI/000-016 the working areas,
  GI/100 the tentative in-situ test quantities.

**Discrepancies I cannot adjudicate:** the brief says 35 sheets; both docs say 33. The names
`DWGS COMBINED`, `DWGS`, `60740338-GI-` return zero hits repo-wide — the filename convention in the
brief is not the one recorded here (`GI/210` slash form, and `ND202504/DRG/GI-210.pdf` as a synthetic
test filename). The four arithmetic checks quoted at `schedule.py:22-24` (`29.90 + 5.0 = 34.90`, etc.)
are prose in a docstring; **no fixture reproduces them and no test exercises those numbers.**

**What "flattened raster" costs, measured on this box** against a synthetic A1 landscape sheet
(2384×1684 pt):

| Render path | Pixels | PNG | Wall |
| --- | --- | --- | --- |
| raw @150 DPI (`documents.to_images` — no width cap) | 4967×3509 | 77 KB | 1.81 s |
| raw @300 DPI (`ocr._render_png` — no width cap) | 9934×7017 | 304 KB | **6.16 s** |
| **`pdfops.render_page` @110 DPI, capped 1400 px** | **1391×983** | **16 KB** | **0.15 s** |

The 300-DPI pixmap is ~70 megapixels ≈ **209 MB of RGB in memory per sheet**. `ocr._render_png`
(`ocr.py:216-220`) applies `OCR_DPI` flat with **no width ceiling**; the cap at `pdfops.py:701` exists
only in `render_page`. That single fact decides Q3.

---

## Q2 — Which sheet carries the schedule, found cheaply?

**Four stages, stopping at the first that answers. Three of them are free.**

**Stage 0 — metadata triage, ~5 ms/page, zero tokens.** `pdfops.inspect` already returns `filename`,
`report.metadata` (`doc.metadata` — `title`/`subject` frequently carry the sheet title) and
`report.outline`. A real GI set names its sheets. Measured: `_page_chars` over 79 pages = 0.397 s
(5.0 ms/page); `get_toc` = 0.001 s/doc. **On the reference contract this alone may identify GI/210 by
name, at no cost.** It also confirms you are in the raster case (`page_chars` all zero) rather than
assuming it.

**Stage 1 — a text layer, if any sheet has one.** `pdfops.has_text_layer` then `pdfops.search(data,
"SCHEDULE")` at ~3 ms/page. Free, exact, and `locate` already returns fractional highlight rectangles a
viewer can draw. Mixed sets are common; do not assume all sheets are raster because some are.

**Stage 2 — one batched vision call over width-capped thumbnails.**
`pdfops.render_page(sheet, 1, dpi=110)` → 0.15 s, 16 KB each. Then a **single** `complete_json(images=
[…])` asking only *"which of these sheets carries a per-borehole schedule table? return the index and
the sheet number from the title block."* That is a routing question, not a transcription question, so
the answer model stays tiny.

Estimated: ~5 s of rendering, ~53k input tokens, ~$0.16, **one round trip**. `running_live.md` §4b is
the reason the round-trip count is what matters: five *text* stages took ~17 minutes for 12 pages,
because per-call latency dominates.

**Stage 3 — read the located sheet, once.** `render_page(sheet, 1, dpi=300)` (`MAX_RENDER_DPI` is 300
at `pdfops.py:694`, and the width cap still applies) and a second vision call to transcribe.

**Use `pdfops.render_page`, never `documents.to_images`.** `to_images` has no width cap; the repo's own
measurement (`documents.py:697-701`) is *"the A3 drawing sheets in part 07 render 1819px and weigh
1.6MB each — the same request producing a 27x heavier response purely because the paper is bigger."*
The API downscales to ~1.15 MP regardless, so the uncapped path buys **zero extra tokens** for 12× the
render time and a multi-megabyte payload.

Also budget for the corrective retry at `llm_client.py:308-319`: **it re-sends every image.** Keep the
routing model strict and small so one bad parse cannot double a 53k-token call.

---

## Q3 — Reading strategies, and what each costs

| Strategy | Verdict |
| --- | --- |
| **`pdfops` native text** | Free, exact, and **cannot read a raster at all** — probed on a genuine image-only PDF: `page_text → ''`, `has_text_layer → False`, `locate → None`, `search → []`. Use it as a *test*, not a plan. |
| **Local OCR (`pipeline/ocr.py` + `ocr_table.py`)** | **Reject.** Four independent reasons below. |
| **Vision via `llm_client.complete_json(images=…)`** | The recommendation. Routing already forces a `VISION_CAPABLE` provider for any image (`llm_client.py:253-275`, `VISION_CAPABLE = {anthropic, openai}`), so a vision call **cannot** be routed to DeepSeek regardless of the app-wide model setting. |
| **Human transcription** | Always available, always correct, and currently **the only option** — which is the door problem, not a strategy. |

**Why local OCR is rejected, specifically:**

1. **Unavailable on this box.** `pytesseract` is not installed and no binary is on the machine
   (`ocr._find_tesseract() → None`, verified). Installing `pytesseract` *without* the binary is
   strictly worse than neither — repo trap 1b, `OcrEngineUnavailable` propagates uncaught.
2. **A trap found by tracing, not documented anywhere:** `ocr_enabled()` (`ocr.py:102`) checks only the
   `OCR_ENABLED` env flag and **not** that `pytesseract` is importable. Measured here —
   `extract_document(raster, "application/pdf", table_aware=True)` raised
   `ModuleNotFoundError: No module named 'pytesseract'`, where `table_aware=False` degraded gracefully.
   `ocr_table._words` (`ocr_table.py:33`) imports at function scope with no guard and
   `_pdf_table_aware:238` does not wrap the call.
3. **The cost is absurd for this shape.** 6.16 s and a 209 MB pixmap *per sheet* to rasterise, ≈3.6 min
   for 35 sheets before tesseract touches a 70 MP image.
4. **Its column recovery was built for a different page.** `ocr_table._column_bounds` clusters into
   exactly **five** columns by largest gaps (`ocr_table.py:63-72`), for A4 Schedule-of-Rates pages. A
   GI/210 sheet has ~12 columns, a title block, a legend and a survey grid. `--psm 6` linearises a
   ruled table and loses column association — `ocr_table.py:4-6` says so itself.

OCR earns its keep in exactly one case: **repeated** search across the same sheets, because
`pipeline/ocr.py:121-182` is a content-addressed cache keyed on
`sha256(bytes)-{dpi}-{lang}-psm{psm}`, with no TTL and a poisoned-payload guard (an all-empty `pages`
list is treated as a miss, `ocr.py:170-172`). For a one-shot "find GI/210" it does not.

**The honest gap: this repo contains no vision measurement at all.** `running_live.md` §4b's table is
five *text* stages on DeepSeek; the 12-page CIC extract had a text layer so no vision call ever fired,
and no `SITESOURCE_LLM_LOG` JSONL exists anywhere on disk. The ~$0.16/35-sheet figure above is
**derived** from Anthropic's `w×h/750` billing after downscale, not measured. Getting a real number
needs a live run with `SITESOURCE_LLM_LOG` set against a real raster sheet.

---

## Q4 — What already exists that must not be rebuilt

Substantial machinery. The reader is smaller than it looks because all of this is already here.

**Rasterisation and sheet triage** — `client_boq/ingest/pdfops.py`, entirely deterministic, no model,
no network: `inspect`, `_page_chars`, `_outline`, `has_text_layer`, `search`, `locate` (returns page
fractions for a viewer), `render_page` (**`MAX_RENDER_WIDTH_PX = 1400`, `MAX_RENDER_DPI = 300`, solves
for the DPI that lands on the ceiling**), `slice_pdf` (returns the *original* bytes on any failure
rather than losing content).

**The vision seam** — `llm_client.complete_json(images=[base64 png], …)`. `demo_fixture`
short-circuits before any provider code runs, so a DEMO reader never opens a socket. Existing vision
call sites to copy: `client_boq/ingest/s02_interpret.py:129-160` (and note **it measures first, in
every mode** — the trap-9 fix) and `router.py:5011-5019`.

**Every arithmetic check a reader needs, already written and already correct:**

- `Station.reconciles()` / `discrepancy()` (`schedule.py:74-84`) — per-row `length ≈ soil + rock`
  within `ROW_TOLERANCE_M = 0.05`.
- `StationSchedule.bad_rows()` / `usable()` (`schedule.py:147-153`) — named, never dropped, never a
  gate.
- **`boq/derive.py`** — the whole independent check against the bill: `soil_m`, `rock_m`, `holes`,
  `standing_time`, standpipes, piezometers, `agmd`, three monitoring-week lines, trial-pit volume and
  samples, inspection pit, mazier, permeability, pressuremeter, televiewer. `Derived.compare`
  (`derive.py:60-73`) writes the sentence *"derived X is Y more than the billed Z. Either the drawing
  was misread or the bill diverges from it — worth settling before the rate rests on it."*
  `derive.py:28`: **"Nothing here overwrites anything. It reports."**
- `boq/georef.py`, `boq/hk1980.py`, `boq/access.py` — all consume a schedule and none need a reader.

**The storage and confirm semantics** — `store.save_station_schedule` / `load_station_schedule`, and
`POST /site/schedule`'s non-sticky confirm (`router.py:3773-3778`: *"Confirming is not sticky. A
re-read lands unconfirmed again, because the thing somebody checked is no longer the thing on the
screen"*). **This is exactly the semantics a machine proposal requires, and it is already built.**

**Do not build:** an OCR path, a second rasteriser, a second arithmetic checker, a second
bill-comparison, a coordinate transform, or any confirm/gate machinery.

---

## Q5 — Where it should live, and how it is triggered

**Home: `client_boq/ingest/`, beside `pdfops.py`.** The ingest package is already the place where
documents become structure, already owns the deterministic PDF operations, and already owns the
"measure first, then decide whether the fixture applies" discipline (trap 9). `boq/` is where a
*schedule* is checked and used; `ingest/` is where a *document* is read. Two files:

- `ingest/sheet_finder.py` — deterministic. Stages 0 and 1 of Q2, plus thumbnail assembly. No model.
- `ingest/s0X_station_schedule.py` — the two vision calls, each with a `demo_fixture`.

**Trigger: a job on the existing pool, not a request-time call.** `client_boq/jobs.py` already has
`JOBS`/`POOL` (`jobs.py:204-205`, `max_workers=2`) and every heavy stage runs there as sync `def`.
Two vision round trips against A1 sheets will not finish inside an HTTP request.

**And the endpoint must be additive, not a replacement.** `POST /site/schedule` stays the human
writer. The reader posts a *proposal* through the same store with `confirmed=False`.

---

## The three constraints, and how each is met

**1. A machine-produced schedule is a proposal, never a fact.**
Already structurally enforceable: `save_station_schedule(..., confirmed=False)`, and confirm is
non-sticky by design, so a re-read cannot inherit a human's earlier tick. The reader must never pass
`confirm=True`, and — following the `DepartureProposal`/`PlannedSplit` precedent in §5 of the repo
CLAUDE.md — **the model's output type should structurally lack a confirm field** so it cannot.

**2. Name what could not be read.** `bad_rows()` exists and is the right instrument for *arithmetic*
failure. It is **not sufficient for reading failure**, and this is the most important gap I found:

> `Station.soil_m`, `hard_above_rockhead_m` and `rock_m` are **non-optional `float` defaulting to
> `0.0`.** A blank cell and a genuine zero are the same value. `rock_m == 0.0` is legitimate and
> common — a soil-only hole, rendered as `—` at `Site.tsx:367` — so "0 means unread" cannot be inferred
> downstream. And `reconciles()` short-circuits to `True` when `length_m is None`
> (`schedule.py:76-77`), so `Station(station="CE19-ABH42")` with nothing else read is
> `soil 0 + rock 0 = 0`, reconciles, has no discrepancy, and contributes 0.0 to the totals. **It passes
> every honesty check in the module.**

Worse for a machine reader: `index()` is keyed on `station` and **the last duplicate silently wins** —
there is no duplicate check anywhere in the module. A vision model that reads `ABH07` twice loses a
row without a sound. And `Station.notes` / `StationSchedule.notes` exist and are consumed by **nothing**
— no backend reader, no router field, no frontend render (`types.ts:155` declares it unused).

**Therefore a reader is not safe to build until a station can say "I could not read this cell."**
That is a model change, it is independent of any drawing, and it should come first.

**3. Degrade, don't fail.** The confidence-ladder precedent is `pdfops.plan_draft` (tier 1 bookmarks →
tier 2 printed contents → tier 3 dividers → tier 4 whole document, *"degraded success, never raises"*).
The reader's ladder is the Q2 stages, and its floor is the door: **no sheet identified → the human
types it**, which is a working outcome rather than an error.

**4. It is an independent check, never a back-fit.** `derive.py` is already built the right way round
— it computes from the schedule and *sets the bill beside it*. The rule the reader must not break is
that no bill figure may ever enter the reading prompt as an expected answer. The bill is the answer key
we grade ourselves against **after**, and `schedule.py:33-36` states the payoff: *"When the two
disagree, that disagreement is the most valuable thing here."*

---

## What cannot be determined without the pack

Stated plainly, because the brief asked for it:

- **What a GI/210 sheet actually looks like** — column order, header wording, row pitch, whether the
  table continues across sheets, how blanks and ticks are printed, raster resolution and compression.
  The docs describe the *columns*; no pixels exist here to check any of it against.
- **Whether the pack is 33 or 35 drawings**, and whether `DWGS COMBINED.pdf` / `60740338-GI-*.pdf` are
  the real filenames. Neither string occurs in this repository.
- **The real accuracy of a vision transcription of a 91-row table**, and therefore whether one call per
  sheet or one call per row-band is needed. The largest station fixture anywhere in the repo is **12
  holes**, generated by a loop with two soil values and two rock values, every row reconciling by
  construction (`test_boq_derive.py:46-57`). It cannot represent a misread digit, a row split across a
  page break, a hyphen in a blank cell, or a duplicated station name.
- **Measured vision cost and wall clock.** No vision call has ever been made in this repo.

**What would close it:** one real GI/210 page as a rendered raster (a PNG at the working DPI is enough
and sidesteps the 232 MB), plus the ground-truth 91-row schedule as CSV to score against. Given
`.gitignore:5` blocks `*.png` and the standing rule that no client tender data enters the repo
(`_bqfixture.py:2-4`, `_hke_workbook.py:12-13`), that sample lives outside version control — mirroring
how `_hke_workbook.py` keeps the transcription in and the source workbook out. A synthesised raster is
available and is worth exactly what it is: **a picture of our own assumptions — it can prove the
plumbing and cannot measure the reading.**

---

## Recommended order

1. **Say "unread" out loud** — `Station` gains a way to mark a cell it could not read, `bad_rows()`
   gains a sibling for it, duplicate station names stop being silent. Needs no drawing. Must precede
   any reader.
2. **Open the door** — `api.ts` gains the POST; `Site.tsx`'s dead end becomes an editor a person can
   paste 91 rows into. Unblocks `derive`, the map, hole classification, and re-arms the sweep's
   unclassed-hole refusal. Needs no drawing.
3. **The deterministic half of the reader** — sheet triage (metadata → filename → text layer →
   thumbnails). Fully testable against synthetic PDFs, because it is testing *structure*, not reading.
4. **The vision half** — two calls behind a job, output a proposal, `confirmed=False`, arithmetic and
   `derive` as the gate. Buildable and unit-testable in DEMO; **its accuracy is not measurable here**,
   and that must be said on the screen, not just in a docstring.
