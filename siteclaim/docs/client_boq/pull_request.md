# client_boq — the client→tender review product: backend, UI, and the freeze gate

**Branch** `from-client-to-tender-BOQ` → `main` · this is the body for the already-open **PR #4**
(`https://github.com/weAOKSKDOKAS/SiteSource1/pull/4`) — push to update it, do not open another.

---

## 1. What this adds

A **second product** on the existing FastAPI + React chassis. Procurement sources work *out* to
subcontractors; `client_boq` takes the client's contract *in* and walks it to a priced offer.

| | **Procurement** (unchanged) | **client_boq** (this PR) |
|---|---|---|
| Direction | contractor → subcontractors | client → contractor |
| Flow | tender → split by trade → shortlist → enquiries → level → award | binder → **ingest** → departure register (**review**) → scope freeze → cost estimate, workbook, offer letter (**estimate**) |
| Code | `backend/pipeline/`, `db/`, `rules_engine/` | `backend/client_boq/` |
| API | ~58 routes at the root | **46 routes** under `/client-boq/*` |
| Frontend | 5-tab wizard, Atlas palette | Documents · Register · Scope at `#/tender`, paper/brass palette |

The governing principle is the same in both, and every design decision below follows from it:

> **The LLM reads, structures, proposes and drafts; deterministic code and human gates decide.**
> A measurement outranks a fixture, and outranks a model proposal.

No price, verdict, risk flag or document boundary is ever committed by a model alone.

## 2. Why

A real tender is one 400-page binder. `review/s01_ingest` used to concatenate every uploaded
document into a single prompt against `DEFAULT_MAX_TOKENS = 8000`, while
`documents.extract_document` silently stops at `TEXT_MAX_PAGES = 200`. **Half the binder was
dropped and the rest truncated, with nothing on screen saying so.** Splitting the binder into parts
first turns that into a dozen ordinary calls, and gives every clause a part and a page range to
cite — which is what makes the register auditable at all.

---

## 3. The change, in four passes

Read in this order; each pass assumes the one before it.

### Pass 1 — the module (12 commits, `backend/client_boq/**`)

Three sequential workflows separated by four human gates:

```
INGEST                                    REVIEW
inspect       Det  outline, coverage,     s01 ingest      Det+AI  parts → clauses
                   confidence ladder 1-4  s02 summary     AI      commercial risk
s01 plan      AI   propose the split      s03 criteria    AI→RULE match + 8 thresholds
              Det  validate bounds/gaps   s04 scope align AI→RULE precedence (SQD-01)
── GATE 1 /ingest/manifest/approve ──     s05 program     AI→Det  LD / mobilisation
cut           Det  slice pages, no LLM    s06 cashflow    Det     monthly profile
s02 interpret AI   one card per part      s07 register    Det     assemble ONE register
                                          s08 citations   Det     anti-hallucination
ESTIMATE                                  ── GATE 2 /review/approve ──
s01 scope review  AI draft + register     s03 cost buildup  Det  qty × rate
── GATE 3 /estimate/scope/approve ──      s04 indirects     Det  lump / per_week / pct
   (FREEZE — see Pass 3)                  s05 validate      RULE 5 flags
s02 schedule      Det  normalise          s06 offer letter  AI prose, injected numbers
                                          → workbook (.xlsx) + letter (.md)
```

**Four gate rules, enforced with distinct 409s.** `/ingest/split` refuses until the manifest is
approved; `/estimate/scope` until the register is approved; `/estimate/run` until **both** the
register and the scope are approved. The approve endpoints are the **only** writers of
`confirmed`/`dismissed` verdicts and gate flags — `DepartureProposal` (the AI's s03 output model)
deliberately has **no status field**, so a model structurally cannot open a gate, and
`PlannedSplit` carries no `approved` flag and no confidence tier, so the planner cannot promote its
own confidence.

**No silent drops.** Unmatched criteria → `unresolved`, unmatched clauses → `uncovered`, bad
citations → `citation_failed`. All stay visible.

Four lazily-created tables (`CREATE TABLE IF NOT EXISTS client_boq_*`, never in `db/schema.sql`):
`client_boq_manifests`, `client_boq_documents`, `client_boq_parts` (a part's **stable** identity),
`client_boq_part_revisions` (everything a revision can change). **Nothing is ever destroyed** — an
addendum appends a revision, Rev 0 survives Rev 1 and stays readable on disk, and the operative
revision is *derived* as the highest `rev` rather than stored as a flag that could drift.
Modelled on the real ND/2025/04 package: 154 documents stayed at Rev 0, 9 went to Rev 1, 2 to
Rev 2, and each addendum shipped only the replacements it affected.

### Pass 2 — Series T: the backend built ahead of any design

Their shape is set by how tendering works, not by a screen layout.

| # | What | Note |
|---|---|---|
| T1 | Split downloadable as a zipped folder tree | |
| T2 | List every tender with part count and gate states | |
| T3 | Revision axis + .xlsx document history | the append-only rule above |
| T4 | RFI / clarification loop — raise, batch into one numbered letter, answer | |
| T5 | Departure Schedule generator (md / xlsx) | **internal by default** |
| T6 | Letter of Qualifications generator | **internal by default** |
| T7 | Verified citation page-locating with highlight rectangles | |
| T8 | Strategy-flag detection at ingest | |

**The finding that reshaped T5/T6:** both reference tenders warn that qualifying a bid "may cause
the tender to be disqualified". So the two client-facing documents are **working papers** unless
you ask for `?audience=submission`, which adds the tender's own clause as a warning. Ingest flags
that rule when it finds it, because the safe route for a problem clause is a written query before
the cut-off, not a qualification attached to the bid.

**T7 is the anti-hallucination layer.** Three verdicts — `located` / `unverifiable` /
`not_located` — with **corroboration before accusation**: if no citation in a parse maps to a held
part, every one degrades to `unverifiable` ("the parse and the file may not correspond") rather
than 12 real citations being accused of being wrong.

### Pass 3 — Series U: the UI, from the design handoff

Source: `workspace-tendering/design_handoff_client_boq/` — seven frames plus a 302-line README
carrying every hex, size, weight and copy string. Full write-up in **`ui_build.md`**.

| # | Stage | Split |
|---|---|---|
| U1 | Foundation — tokens, types, API client, app shell, document pane | FE + 1 route |
| U2 | Documents tab (frame 01) + in-part search + re-interpret | FE + 2 routes |
| U3 | Register tab (frames 02/03) + negotiation text + RFI withdrawal | FE + 2 routes |
| U4 | Panels (frames 04, 05, 06) | FE only |
| U5 | Scope tab (frame 07) + **the freeze gate** | ~half BE |
| U6 | Price and Offer tabs | **blocked — not designed** |

Roughly three quarters frontend. The remaining quarter was not cosmetic: **frame 07 turned out to
be the freeze gate that T4, T5 and T6 had all pointed at and nothing implemented.**

The estimate's scope was one summary plus a flat list of notes — enough to brief a pricing run, not
enough to sign. Freezing needs three things a paragraph cannot carry, and each became a column in
the new `client_boq_scope_items` table:

- **where each line came from** (`source_ref`) — nothing walks into the scope on its own;
- **whose words it is in** (`badge`) — a model's suggestion and a person's decision must never look
  alike on a page that becomes a contract;
- **whether an unanswered query became an assumption somebody accepted**
  (`is_fallback` + `accepted`).

### Pass 4 — Series R: the revision after using it

The UI shipped, was used, and came back with six complaints. Investigating them found **one root
cause behind two of the worst** and **one defect that made LIVE mode impossible**. Write-up in
`ui_build.md` §6b.

| # | Complaint | What it actually was |
|---|---|---|
| R1 | "the pdf is too small", "scroll, not prev/next" | 400px base, stepper zoom, page stepper |
| R2 | "the design is rigid" | pane widths hard-capped at 760px |
| R3 | "the register is so ambiguous" + "can't see the quote highlighted" | **the register is about a different document** — and rows showed `PS-01` with no meaning |
| R4 | "documents doesn't highlight the context", "can't edit the context" | never built |
| R5 | — | **`pollJob` existed and no tab called it** |

**R3, measured, not guessed.** In DEMO the review parse is a fixture describing a fictional
"Harbour Crest Residences" subcontract. Against the real 411-page CIC binder, *none* of the
register's quoted text exists anywhere in it:

```
item 1  cl.8.3   'no cap on the aggregate amount'                NOT ANYWHERE in the binder
item 2  cl.5.2   'Retention of 10% of each payment'              NOT ANYWHERE
item 3  cl.11.2  'Defects Liability Period is 24 months'         NOT ANYWHERE
item 4  cl.10.4  'not remedied within 5 days of written notice'  NOT ANYWHERE
item 5  cl.4.8   'assessed and certified within 30 business days' NOT ANYWHERE
```

So every row cited a clause that was not on screen and no highlight could possibly draw. **This was
never a layout problem.** Fixed two ways: `_parse_mismatch` (a deterministic filename comparison
that must never fire in LIVE) raises a banner saying whose document the findings describe, and
`GET /criteria` finally exposes the position each finding is measured against, so a row reads:

```
PS-04 · Security (Retention)
  WE ACCEPT  5% cap; 2.5% released at Practical Completion.
  IT SAYS    Retention 10%, released only at Final Certificate
  RED FLAG   >5% retention, or no release at PC.
```

9 of the real tender's 17 rows now resolve like that. The other 8 have no clause and no criterion
and read on rationale alone, which was already a design rule.

**R5 — LIVE could never have worked.** In DEMO every job endpoint returns `done` inline; in LIVE it
returns `{status: "queued", job_id}` and the work happens on a thread. Every tab read `.result` off
the first response — perfect offline, silently inert with a real key. All job starts now go through
one helper that polls in LIVE and passes through in DEMO:

```ts
export async function runJob(start, poll, onProgress) {
  const started = await start();
  onProgress?.(started);
  if (started.status === "done" || started.status === "error" || !started.job_id) {
    if (started.status === "error") throw new Error(started.error || "The job failed");
    return started;
  }
  return pollJob(poll, started.job_id, onProgress);
}
```

A progress strip finally uses the `done` / `total` fields the `Job` model has always carried.

---

## 4. API surface — 35 → 46 routes

Eleven new endpoints, all under `/client-boq/*`.

| Route | Why it exists |
|---|---|
| `GET  /ingest/parts/{set}/{part}/page/{n}.png?dpi=` | server-rendered page image — takes a **source-document** page number |
| `GET  /ingest/parts/{set}/{part}/search?q=` | in-part text search, same rectangles as citations |
| `POST /ingest/parts/{set}/{part}/reinterpret` | a fresh machine reading of one part |
| `POST /ingest/parts/{set}/{part}/context` | edit the card prose; stamps `user` |
| `POST /ingest/parts/{set}/{part}/locate` | prove a quote against the page — three verdicts |
| `GET  /criteria` | the acceptable-terms library the register is measured against |
| `DELETE /rfi/{set}/{rfi_id}` | **withdrawal, not deletion** — the draft text stays on the register line |
| `GET  /estimate/scope/{set}/sources` | what the scope *could* be built from — **derived every read** |
| `POST /estimate/scope/map` | map one source in; nothing enters the scope alone |
| `POST /estimate/scope/item` | edit / accept a fallback / take ownership |
| `DELETE /estimate/scope/item/{set}/{item}` | remove a mapped line |

**Modified behaviour:** `ReviewApproval` gained `negotiations: dict[int, str]`;
`/estimate/scope/approve` now 409s while any AI fallback is unaccepted; `_manifest_payload` gained
`coverage_detail` and an explicit `part_id`.

## 5. Frontend

New directory `siteclaim/frontend/src/client_boq/` — 11 files, ~5,300 lines:

| File | Lines | |
|---|---|---|
| `tabs/Register.tsx` | 1058 | frames 02/03 + the criterion block and mismatch banner |
| `tabs/Documents.tsx` | 904 | frame 01 + editable cards + prove-a-quote |
| `tabs/Scope.tsx` | 536 | frame 07 — the freeze gate |
| `PageView.tsx` | 503 | continuous scroll, typed zoom, lazy pages |
| `types.ts` | 434 | the payload contracts |
| `chrome.tsx` | 412 | app bar, step strip, resizable panes |
| `panels.tsx` | 388 | frames 04, 05, 06 |
| `ui.tsx` | 310 | primitives + **the authorship derivation** |
| `api.ts` | 283 | fetch layer + `runJob` / `pollJob` |
| `App.tsx` | 290 | tab state, job progress, criteria fetch |
| `tokens.css` | 199 | the paper/brass `@theme` |

**Only two existing frontend files are touched.** `main.tsx` branches on `location.hash` (six lines,
no router dependency) and `index.css` imports the token file.

---

## 6. Decisions worth reviewing

These are the places where the obvious implementation is wrong, and the reason is not obvious from
the diff.

**Authorship survives a human verdict.** The design's rail shows five authorship swatches and none
is in any payload — they must be derived. The obvious derivation reads `status`, and it is wrong: a
human verdict *overwrites* `status`, so the moment a line is confirmed every trace of who found it
is gone. Half the register would lose its authorship the instant someone worked through it, on the
one screen whose whole purpose is showing who said what.

```ts
export function authorOf(item: Pick<DepartureItem, "status"|"source"|"rule_ref">): Author {
  const status = item.status as RegisterStatus;
  if (status === "citation_failed") return "failed";  // cannot be confirmed, so cannot be overwritten
  if (item.rule_ref) return "rule";                   // the rule layer is its only writer
  if (status === "uncovered") return "uncovered";
  if (item.source === "cashflow") return "code";      // s06 is arithmetic; no model involved
  return "model";                                     // honest default — over-crediting code is the dangerous direction
}
```

**The render ceiling is on pixels, not DPI.** A DPI cap would not have caught this. At 110 DPI the
A4 Conditions of Tender came back at 910×1287 / 58 KB and the A3 drawing sheet at 1819×1285 /
**1,666 KB** — the same request, 27× heavier, purely because the paper is bigger, and a tender is
full of A3 sheets.

```python
MAX_RENDER_WIDTH_PX = 1400
fitting = int(MAX_RENDER_WIDTH_PX * 72 / width_pt)
pixmap = target.get_pixmap(dpi=max(MIN_RENDER_DPI, min(dpi, fitting)))
```

**Search has no minimum length, and `locate` does — deliberately.** `pdfops.locate` refuses
fragments under 45 characters because a citation confirmed by an accidental match is worse than one
left unconfirmed. That is a rule about *proof*. `pdfops.search` is a separate function with no
floor, because a person typing into a search box is making no claim about the document. Both facts
are commented in the source, or someone will eventually "fix" one into the other.

**Seeing and searching are different questions.** An image-only part rasterises perfectly and
cannot be searched at all, so search returns `searchable: false` with a sentence rather than an
empty result set — reporting zero hits for a page nobody could look at trains the user to distrust
the search.

**Scope sources are derived on every read, never stored.** The register, the open questions and the
change log are each already the authority on their own contents; a stored copy goes stale the
moment a verdict changes or an answer arrives, and the scope would rest on a snapshot nobody took
deliberately.

**Editing always stamps `user`.** There is no state in which a person's words are attributed to a
model, and none in which a model's words silently become a person's. `Convert to user` exists for
taking ownership of wording you agree with without changing it. `readable` is deliberately **not**
editable on a context card, because it is a measurement.

**One deliberate departure from a drawn frame.** Frame 07 shows *Approve scope & unlock pricing*
live while two AI fallbacks are unaccepted; the implementation **disables it**, states the reason
where the button is, and 409s as a backstop. An open query does not block pricing — the submission
deadline does not move because the client has not replied — and the forcing function is *freeze*,
where every unanswered query becomes an answer **or a stated priced assumption**. Approving over an
unaccepted fallback would put a machine's guess behind a price with nothing recording that a person
agreed to it, which the same frame's own rule forbids ("a machine's number must not be able to look
priced").

**A `@theme` block only generates utilities if it reaches the ROOT stylesheet.** A `@theme`
imported from a `.tsx` is inert — Tailwind v4 emits nothing and the page renders unstyled with no
error. Every client_boq token is `cb-` prefixed because the names genuinely collide: Atlas owns
`--color-paper` at a cool `#eef2f7` where this palette wants a warm `#FAF9F6`.

**Type roles are not decorative.** Serif carries the argument (rationale, clause text, scope prose),
sans carries the interface, mono carries anything a machine produced or that must be compared digit
by digit. Mixing them blurs who said what, which is the one thing this product must not do.

---

## 7. Blast radius

client_boq is a bolt-on. It imports *from* the procurement chassis and the procurement side has
**zero** knowledge of it.

**Reuses by import, never modifies:** `pipeline.llm_client`, `pipeline.documents.extract_document`,
`db.store.get_connection`, `pipeline.workspace.Workspace`.

**Never touches:** the Gmail path (client_boq sends no email at all), procurement pipeline stages,
`rules_engine/`, `routing/`, `benchmark/`, `pipeline/estimate/` (a *different* estimator — do not
cross-wire), `db/schema.sql`, `db/seed.py`.

**Existing files modified — four in total:**

| File | The entire change |
|---|---|
| `backend/api.py` | 2 lines: one import + `app.include_router(client_boq_router)` |
| `siteclaim/CLAUDE.md` | 1 row in the "where everything lives" table |
| `frontend/src/main.tsx` | the `#/tender` hash branch |
| `frontend/src/index.css` | one `@import` of the token file |

Procurement's five tabs and every Atlas token still resolve — verified by grepping the built CSS for
both families, and by loading `localhost:5173` unchanged.

---

## 8. Testing

```
python -m pytest -q                    931 passed, 5 skipped   (from 879/5)
python -m pytest client_boq/tests/ -q  205 passed
tsc --noEmit && vite build             clean
```

The 5 skips are `requires_tesseract` and are the expected green state — see trap 1b.

New test files in this work: `test_part_viewer.py` (17), `test_context_and_criteria.py` (14),
`test_scope_freeze.py` (12), `test_register_negotiation.py` (9).

### Verified against the real 411-page tender, not a synthetic fixture

**Ingest and Documents.** 12 parts, 411/411 pages, no gaps, no overlaps, tier 1. Page render
exercised on the first and last page of all 12 parts; a page outside a part 404s rather than
silently rendering the wrong one. Both image-only parts render and honestly refuse search. 30
strategy flags found, including the CIC 4.26 qualification-disqualification clause.

**The Register reproduces the design's own numbers exactly** — which strongly suggests the frames
were drawn from this fixture:

| | Design | Measured |
|---|---|---|
| needing a verdict | 17 | 17 |
| with no clause, quote or position | 5 of 17 | 5 of 17 |
| unresolved criteria | 18 | 18 |
| aligned / passed | 2 | 2 |
| cash-flow periods | 9 | 9 |
| checks: criteria / scope / programme / cash flow | 9 / 5 / 2 / 1 | 9 / 5 / 2 / 1 |

Authorship across the 17: 7 rule, 7 model, 1 failed, 1 uncovered, 1 code. Confirming the
citation-failed line returns 409, which is why the control is disabled.

**The freeze gate.** An open query maps as an unaccepted fallback; approving returns 409 naming it;
`/estimate/run` stays shut; accepting it stamps `user` and opens the gate; the query is **still
open** afterwards — because the query never blocked, the unowned guess did.

**The six complaints, walked one at a time** (`walk_fixes.py`, verbatim output):

```
PASS [6] every zoom level renders                 100/150/155/178/200% → dpi 96–300
PASS [1] every page of the part renders           pp.5-16, all 200
PASS [2] rows resolve to a stated position        9 of 17
PASS [3] the mismatch is detected
PASS [4] at least one claim is located            qualifications-penalised → FOUND binder p.12
PASS [4] a quote absent from a part is reported, not guessed
PASS [5] editing stamps USER and survives a reload
PASS [5] readable is still a measurement
PASS [5] a fresh machine reading is labelled as one
ALL OK
```

The `locate` result is worth reading twice: the strategy flag **claims printed page 8** and is
**measured on binder page 12**, and the same quote on `04-sct` returns `not_located` rather than
scrolling somewhere plausible. That gap is the entire argument for measuring rather than trusting.

---

## 9. Known gaps — what this does not do

| Gap | Why |
|---|---|
| **Price and Offer tabs (U6)** | not designed. Their backend *works* — `/estimate/run`, the .xlsx workbook and the offer-letter draft are built and tested — so the gap is a drawn screen, not a capability. Both steps show `NOT YET RUN` rather than vanishing. |
| **No WAS/NOW clause diff (frame 06)** | `ChangeEntry` carries the addendum's own advisory change table and **no old or new clause text**, so there is nothing to diff. The panel says so instead of drawing an invented one. (The real ND/2025/04 addendum states its own change table is "neither exhaustive nor guaranteed to be accurate" anyway.) |
| **No manifest page-bound editing** | the endpoint accepts an edited parts list; the control that produces one is not built, so the button is disabled with a tooltip saying so. |
| **No verdict clearing** | no endpoint clears a recorded verdict, so `Undo` explains that rather than pretending. Re-running the review is the honest reset. |
| **Mobile** | designed for ≥1280 px. Below that the rail folds, then the document pane becomes a tab. |
| **The LIVE model path has still never been run end to end** | DEMO and LIVE are a real code fork on `demo_mode()`. Green tests prove the deterministic engine and the data contracts and prove **nothing** about the live model path. Needs `ANTHROPIC_API_KEY` in `backend/.env` — see `running_live.md`. |
| **No auth, CORS `allow_origins=["*"]`** | fine locally, unsafe published. |
| **Jobs live in an in-process dict; artifacts on local disk** | a restart drops in-flight jobs. Nothing is in durable storage. |

---

## 10. Incident to disclose

During this work a throwaway probe script called `store.get_conn()` **without `DEMO_MODE`**.
`client_boq` creates its tables lazily with `CREATE TABLE IF NOT EXISTS` on every connection, so
merely *opening* a connection added **13 empty `client_boq_*` tables** to `db/sitesource.db` — a
procurement-only committed database.

- **No data was lost**: 21 procurement tables, 1,664 rows, verified identical before and after,
  `integrity_check: ok`.
- First repaired by hand — dropping the 13 empty tables (asserting 0 rows on each) and `VACUUM`,
  which recovers the data but not the bytes.
- **Fully resolved**: once the working copy was wired to this remote,
  `git checkout -- siteclaim/backend/db/sitesource.db` restored it. The file in this PR is
  byte-identical to `381397a` (blob `822bfbd`), and the suite is green against it — 931 passed,
  5 skipped.
- Written up as **`CLAUDE.md` trap 3b**: always set `DEMO_MODE=true` before any ad-hoc script that
  opens the store; if it happens again, `git checkout --` that one path.

**Nothing to do at merge** — `db/sitesource.db` carries no change in this diff.

---

## 11. Reviewing this locally

```powershell
cd siteclaim\backend
py -3.14 -m venv .venv                 # a bare `python` is the MS Store stub
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m pytest -q                    # 931 passed, 5 skipped
$env:DEMO_MODE="true"; python -m uvicorn api:app --port 8000
```

```powershell
cd siteclaim\frontend; npm install; npm run dev
# localhost:5173         → procurement, unchanged
# localhost:5173/#/tender → this PR
```

**Things that will bite you**

- **Run everything from `siteclaim\backend\`** and only via `python -m pytest`. There is no
  `pytest.ini` or `pyproject.toml`, so imports resolve from that directory alone.
- **Do not set `SITESOURCE_DB`** in your shell, and **do not run the seed**. Both databases are
  committed.
- **Set `DEMO_MODE=true` before any ad-hoc script that opens the store** — see §10.
- **FastAPI is pinned to 0.115.6** and must stay there. Later versions make `include_router` lazy,
  `app.routes` then holds an `_IncludedRouter` wrapper, and 13 route tests fail. Assert against
  `app.openapi()`, never `app.routes`.
- **`pytesseract` without the system binary is worse than neither** — the OCR layer raises loudly
  by design and 7 tests fail. It is commented out in `requirements.txt` for that reason.

**Suggested reading order for the diff**

1. `backend/client_boq/CONTEXT.md` — the stage/bucket map and the locked decisions
2. `backend/client_boq/models.py` — the contracts, and what the models deliberately *lack*
3. `backend/client_boq/router.py` — the gates and their 409 messages
4. `backend/client_boq/ingest/pdfops.py` — the deterministic PDF layer, no model, no network
5. `frontend/src/client_boq/ui.tsx` — `authorOf`, the single most load-bearing helper
6. `frontend/src/client_boq/tabs/Scope.tsx` — the freeze gate as a screen
7. `docs/client_boq/ui_build.md` — every UI decision and departure, with reasons

---

## 12. Docs added

`docs/client_boq/`: `build_backlog.md` (Series T, U and R with the reasoning behind each),
`ui_build.md` (the full UI write-up incl. §6b, the revision), `running_live.md` (LIVE setup, and
why it matters), `citation_locating.md`, `client_boq_layer_mapping.md`, `review_criteria.md`,
`how_it_fits.md`, `ui_inventory.md`, `estimating_process.md`,
`reviewing_a_construction_contract_with_ai.md`, `templates/`.

Root `CLAUDE.md` gained traps 3b and a rewritten trap 4 (two products, two palettes); `README.md`
carries the current counts and the DEMO_MODE warning.

## 13. Checklist

- [x] Full suite green — 931 passed, 5 skipped
- [x] `tsc --noEmit && vite build` clean
- [x] Procurement untouched and verified at `localhost:5173`
- [x] client_boq footprint outside its own directory held to 4 files
- [x] Every AI call passes a `demo_fixture`; DEMO opens no socket
- [x] Verified end to end against the real 411-page tender
- [x] `db/sitesource.db` byte-identical to `381397a` — see §10
- [ ] **LIVE mode run end to end** — needs an `ANTHROPIC_API_KEY`; see §9 and `running_live.md`
