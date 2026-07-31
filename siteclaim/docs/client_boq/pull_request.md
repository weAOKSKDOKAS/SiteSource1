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
| API | ~58 routes at the root | **59 routes** under `/client-boq/*` |
| Frontend | 5-tab wizard, Atlas palette | a **tender desk** home (multi-tender shelf, team profiles, criteria/rates/model screens) + Documents · Register · Scope per tender, hash-routed under `#/tender`, paper/brass palette |

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

## 3. The change, in six passes

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

### Pass 5 — Series D: the tender desk, and managing the library

The app opened into ONE tender chosen by a `<select>`. An extended design handoff (Frame 00 + a
nav sidebar) turned the entry point into a **desk**, and three capabilities the user asked for rode
along that the handoff lists as undesigned or does not contain at all: editing the criteria,
editing the costing data, and choosing the AI model.

- **The hash is the router.** `#/tender` is the desk, `#/tender/s/{set}/{tab}` one tender,
  `#/tender/criteria|rates|team|settings` the management screens. The browser's own history powers
  the app bar's ← / →; a reload lands where you were. Still no router dependency.
- **The close date is a FINDING, not a form field.** Ingest already quotes the submission-deadline
  clause verbatim with clause + page; `ingest/close_date.py` parses that quote **deterministically**
  and conservatively — `14 August 2026` parses, `04/05/2026` **refuses**, two dates refuse. A refusal
  is not an error: the card shows `DATE NOT FOUND — CONFIRM IT` and a person types what the clause
  says, stamped with their name. **DEMO always lands on not_found** — the fixtures describe the
  sample tender, and a fixture date labelled "read from your upload" would be fabrication.
- **`blocked` is computed where the gates live.** The shelf's filter and the card's blocking
  sentence derive from counts `list_sets` computes server-side, because that filter must never
  disagree with what the 409s refuse. The sentence is composed client-side; "in progress" appears
  nowhere.
- **Named profiles, no passwords.** No auth exists in this app and a password box would be
  security theatre. What the team table honestly buys is attribution: `X-CBOQ-Actor` rides every
  mutating request, `DepartureItem` gained `decided_by`, and "CONFIRMED BY R. LAM" finally has a
  name behind it. Members archive rather than delete — their name is on history.
- **Criteria moved to the DB, markdown as a one-time seed**; **the rate book became the DB source
  `rates.py` had promised**; **one app-wide model setting**. See §6.

### Pass 6 — Series L: the layout, the missing PDF, and joining the two products

Five complaints after using the desk. Two shared a cause no amount of CSS-reading would find.

- **The app slid off the screen.** `PageView` used `el.scrollIntoView({behavior, block})`. That
  omits `inline`, which **defaults to `"nearest"`**, and `scrollIntoView` scrolls *every* scrollable
  ancestor — including the app root, which is `overflow-hidden` and so has no scrollbar to scroll
  back with. Opening Documents seeds a page, the scroll fires, and the bar and left rail leave the
  viewport permanently. Now it scrolls the pane's own scroller by hand.
- **The PDF pane had no floor.** `DOC_MIN = 160` lived only inside the divider's arithmetic; the
  pane was `flex-1 min-w-0`, whose real floor is 0px, and nothing ever re-measured — `clampMiddle`
  was called from exactly one place, inside the drag handler. A width persisted on a wide monitor
  was re-applied verbatim on a narrow window forever. `DOC_MIN` is now **480** (a 460px page at
  100% fits with no sideways scrolling) and applied as a real CSS `min-width`.
- **The panes ran off the right edge.** With that floor the row's minimum is
  `244 + 14 + 320 + 480 = 1058`, plus the 206px sidebar — a **1264px viewport**. The handoff said
  what should give ("the rail folds, then the third pane becomes a tab") and nothing implemented
  it. `fitPanes` now runs on mount and every resize, giving up capacity in that order and stopping
  at the first step that fits. Automatic folds reverse themselves; a deliberate one does not.
- **Three more defects in the same arithmetic**: only the 9px divider was counted (never the 5px
  one), the full rail width was reserved while the 44px folded strip was on screen, and the
  collapse test ignored drag direction — so **dragging left to enlarge the PDF could collapse it**.
- **Register highlights.** The pane now opens on a part (`partId` started `null` and was only ever
  set by a citation that LOCATED, which in DEMO never happens); selecting a row moves to the
  clause's part even when the citation is unverifiable, so the document is readable with the banner
  explaining why nothing is marked; a selected row with a quotation gains **"Show me on the page"**,
  the same locate control Documents has. A search no longer *replaces* citation marks, and the
  first click after a part change now scrolls (the page-element map was cleared on the way IN,
  wiping refs the new part had registered in the same commit).
- **Two products, one click.** The SiteSource logo is a menu (Procurement · Review tender), the
  desk has a Procurement button, and because both set the hash they push history — so Back moves
  between the products in both directions.

---

## 4. API surface — 35 → 59 routes

Twenty-four new endpoints, all under `/client-boq/*`. The first eleven came with the UI:

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

Thirteen more came with the tender desk:

| Route | Why it exists |
|---|---|
| `GET/POST /team` · `POST /team/{id}` | named profiles — attribution, deliberately not auth |
| `POST /sets/{id}/meta` | owner · client · package · archive · outcome |
| `POST /sets/{id}/close-date` | the ONLY writer of a hand-typed date, when the parser honestly refused |
| `POST /criteria` · `POST /criteria/{id}` | edit the library; **disable, never delete** |
| `GET/POST /rates` · `POST /rates/{id}` · `DELETE /rates/{id}` | the rate book; **archive → `missing_rate`**, never a stale price |
| `GET/POST /settings` | the app-wide AI model choice |

**Modified behaviour:** `ReviewApproval` gained `negotiations: dict[int, str]`;
`/estimate/scope/approve` now 409s while any AI fallback is unaccepted; `_manifest_payload` gained
`coverage_detail` and an explicit `part_id`; `GET /sets` gained `meta`, `counts`, `blocked`,
`has_letter` and `?include_archived`; `DepartureItem` gained `decided_by`.

## 5. Frontend

New directory `siteclaim/frontend/src/client_boq/` — **~8,250 lines**:

| Area | Lines | |
|---|---|---|
| `tabs/` | 2651 | Documents · Register · Scope, the three worked screens |
| `screens/` | 934 | Criteria library · Pricing & rates · AI model · Team · NotDesigned |
| `PageView.tsx` | ~540 | continuous scroll, typed zoom, lazy pages, the 480px floor |
| `home/` | 513 | the desk: shelf, folder cards, drop tile, summary strip |
| `chrome.tsx` | ~540 | global bar, step strip, `usePanes` + `fitPanes` |
| `types.ts` | ~530 | the payload contracts |
| `panels.tsx` | 388 | frames 04, 05, 06 |
| `api.ts` | ~360 | fetch layer, the actor header, `runJob` / `pollJob` |
| `App.tsx` | ~610 | hash-routed surface switch, drop-upload, profile picker |
| `ui.tsx` | ~355 | primitives + **the authorship derivation** + avatars |
| `nav/` | 268 | the sidebar and the route parser |
| `tokens.css` | 199 | the paper/brass `@theme` |
| `search/`, `profile/` | 274 | Ctrl-K search, the who-are-you picker |

**Three existing frontend files are touched.** `main.tsx` branches on `location.hash` (six lines,
no router dependency), `index.css` imports the token file, and `components.tsx` gains the
SiteSource logo menu — the one change on the procurement side, and the only way between the two
products without typing a URL.

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

**The close date is read, parsed and refused — never guessed.** The model quotes the deadline
clause verbatim with clause + page (checkable against the rendered page, like any citation); code
parses the quote. The parser is deliberately conservative: `04/05/2026` **refuses**, because
day-first and month-first disagree and a deadline has no safe default, and two distinct dates
refuse because choosing one is an interpretation. A refusal routes to a person, who types what the
clause says and is recorded doing it. DEMO never claims to have read anything.

**Criteria moved to the DB; the markdown is a one-time seed.** `review_criteria.md` promised "a
contractor edits rows without any code change", and that promise predates a UI. Editing through a
screen needs disable-without-delete (a past register may reference the id forever), authorship, and
write-safety — none of which a markdown round-trip gives you without silently reformatting a
hand-maintained file. `criteria_store.load()` returns the identical `CriteriaLibrary`, so the review
stage switched in one line. **Threshold rules are read-only**: their `extract_field` is wired into
`rules.py`, and rule text a person can edit but code does not obey would be a lie on the screen.

**The rate book is the DB source `rates.py` had already promised.** Its header comment has said
since v1 that a future company-DB source "only has to return the same list from a different reader
— nothing downstream reads the CSV directly". `rates_store` is that reader; the CSV seeds it
first-wins (mirroring `rate_index`), and no consumer changed. Rates **archive**, never delete: an
archived rate referenced by an old estimate resolves `missing_rate` on a re-run — honestly absent
and flagged, rather than priced at a number nobody stands behind.

**The model setting needed one additive change to the shared chassis, and it is the only one.**
`LLMClient._route` ignored the constructed provider entirely, so an explicit `provider=` was a
placebo whenever `DEEPSEEK_API_KEY` existed. It now honours an explicitly passed provider for text
calls — images still force Anthropic, which is a physical constraint (DeepSeek rejects image input).
Every procurement site constructs a bare `LLMClient()` and routes exactly as before; the pipeline
tests assert it. Rejected: mutating `os.environ`, which is a race under the job pool's threads.

**`scrollIntoView` scrolls every ancestor, and that broke the whole app.** Omitting `inline` defaults
it to `"nearest"`; the app root is `overflow-hidden`, which is still a scroll container but has no
scrollbar to scroll back with, so bringing a page into view dragged the chrome permanently
off-screen. Panes now scroll their own scroller by hand. Worth knowing before adding any
`scrollIntoView` anywhere in this app.

**A floor that lives only in arithmetic is not a floor.** `DOC_MIN` was respected by the divider's
drag handler and by nothing else, so the document pane's real minimum was 0px and a stale persisted
width made the PDF vanish while still mounted and still fetching images. It is now a CSS
`min-width` as well, and `fitPanes` re-measures on mount and on resize — the layout can no longer
be wider than the window.

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

**Reuses by import:** `pipeline.llm_client`, `pipeline.documents.extract_document`,
`db.store.get_connection`, `pipeline.workspace.Workspace` — with **one documented additive
exception** in `llm_client._route` (see §6), which is procurement-neutral and tested as such.

**Never touches:** the Gmail path (client_boq sends no email at all), procurement pipeline stages,
`rules_engine/`, `routing/`, `benchmark/`, `pipeline/estimate/` (a *different* estimator — do not
cross-wire), `db/schema.sql`, `db/seed.py`.

**Existing files modified — six in total:**

| File | The entire change |
|---|---|
| `backend/api.py` | 2 lines: one import + `app.include_router(client_boq_router)` |
| `backend/pipeline/llm_client.py` | +12/−4: `_provider_arg`, honoured by `_route` for text calls |
| `siteclaim/CLAUDE.md` | 1 row in the "where everything lives" table |
| `frontend/src/main.tsx` | the `#/tender` hash branch |
| `frontend/src/index.css` | one `@import` of the token file |
| `frontend/src/components.tsx` | the SiteSource logo product menu |

Procurement's five tabs and every Atlas token still resolve — verified by grepping the built CSS for
both families, and by loading `localhost:5173` unchanged.

---

## 8. Testing

```
python -m pytest -q                    994 passed, 5 skipped   (from 879/5)
python -m pytest client_boq/tests/ -q  320 passed
tsc --noEmit && vite build             clean
```

The 5 skips are `requires_tesseract` and are the expected green state — see trap 1b.

New test files: `test_part_viewer.py` (17), `test_context_and_criteria.py` (14),
`test_scope_freeze.py` (12), `test_register_negotiation.py` (9), `test_team_and_meta.py`,
`test_close_date.py`, `test_criteria_store.py`, `test_rates_store.py`, `test_settings_llm.py`
(63 between them).

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
**The tender desk, walked against the DEMO backend** (`walk_desk.py`, 18 checks, verbatim):

```
PASS [1] a card carries meta, counts and blocked   counts {undecided 25, citation_failed 1, open_rfis 39}
PASS [1] DEMO never claims to have read the date
PASS [2] a member joins with derived initials      rebecca-lam
PASS [2] ownership and client land on the card
PASS [2] the touch is attributed
PASS [3] confirmation stamps who
PASS [3] a non-ISO date is refused
PASS [4] rows carry editing metadata
PASS [4] an edit stamps the editor
PASS [4] a disabled criterion stays resolvable
PASS [5] the book serves with categories
PASS [5] an edit disowns the seed
PASS [5] archiving states its consequence
PASS [6] the setting round-trips
PASS [6] vision is always anthropic and the payload says so
PASS [6] a provider the app cannot honour is refused
PASS [7] CONFIRMED BY has a name behind it
PASS [8] a won tender leaves the shelf but stays on the record
ALL OK
```

**The layout, verified by screenshot rather than by assertion.** Headless Chrome at **1152 / 1280 /
1366** against a clean DEMO backend: nothing past either edge at any width, the rail auto-folding to
its count strip at the two narrow ones, the document pane holding its 480px floor, and the real CIC
Invitation Letter rendering in the pane on both the Documents and Register tabs. The Register used
to open on "Select a part to read it here" and now opens on a document.

---

## 9. Known gaps — what this does not do

| Gap | Why |
|---|---|
| **Price and Offer tabs (U6)** | not designed. Their backend *works* — `/estimate/run`, the .xlsx workbook and the offer-letter draft are built and tested — so the gap is a drawn screen, not a capability. Both steps show `NOT YET RUN` rather than vanishing. |
| **No WAS/NOW clause diff (frame 06)** | `ChangeEntry` carries the addendum's own advisory change table and **no old or new clause text**, so there is nothing to diff. The panel says so instead of drawing an invented one. (The real ND/2025/04 addendum states its own change table is "neither exhaustive nor guaranteed to be accurate" anyway.) |
| **No manifest page-bound editing** | the endpoint accepts an edited parts list; the control that produces one is not built, so the button is disabled with a tooltip saying so. |
| **No verdict clearing** | no endpoint clears a recorded verdict, so `Undo` explains that rather than pretending. Re-running the review is the honest reset. |
| **Mobile** | designed for ≥1280 px. Below that the rail folds and then the document pane collapses — implemented and verified at 1152, but a phone is out of scope. |
| **The LIVE model path has still never been run end to end** | DEMO and LIVE are a real code fork on `demo_mode()`. Green tests prove the deterministic engine and the data contracts and prove **nothing** about the live model path. Needs `ANTHROPIC_API_KEY` in `backend/.env` — see `running_live.md`. |
| **No auth, CORS `allow_origins=["*"]`** | fine locally, unsafe published. |
| **Jobs live in an in-process dict; artifacts on local disk** | a restart drops in-flight jobs. Nothing is in durable storage. |
| **Presence (live viewers)** | the avatar stack of who else has a tender open is not built. Faking it would be worse than omitting it; it needs a heartbeat endpoint. |
| **Letter templates · Standard positions · Clients · Audit log** | sidebar entry points exist and open a screen that says the screen is not designed. Every fact an audit log would show is already recorded (who, what, when) — it is the reading-back that is missing. |
| **The logo menu's open-on-click** | verified by type-check and build, not by a click: headless Chrome cannot click, and adding Playwright for one assertion was not worth the dependency. |

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
  byte-identical to `381397a` (blob `822bfbd`), and the suite is green against it — 994 passed,
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
python -m pytest -q                    # 994 passed, 5 skipped
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

`docs/client_boq/`: `build_backlog.md` (Series T, U, R, D and L, with the reasoning behind each),
`ui_build.md` (the full UI write-up — §6b the first revision, §9 the tender desk, §10 the layout),
`running_live.md` (LIVE setup, and why it matters), `citation_locating.md`,
`client_boq_layer_mapping.md`, `review_criteria.md`, `how_it_fits.md`, `ui_inventory.md`,
`estimating_process.md`, `reviewing_a_construction_contract_with_ai.md`, `templates/`.

Root `CLAUDE.md` gained trap 3b, a rewritten trap 4 (two products, two palettes), the documented
`llm_client` exception in §4, and current counts; `README.md` carries the counts, the desk
endpoints and the DEMO_MODE warning.

## 13. Checklist

- [x] Full suite green — **994 passed, 5 skipped**
- [x] `tsc --noEmit && vite build` clean
- [x] Procurement untouched and verified at `localhost:5173`
- [x] client_boq footprint outside its own directory held to 6 files, one of them the documented
      additive `llm_client._route` change
- [x] Every AI call passes a `demo_fixture`; DEMO opens no socket
- [x] Verified end to end against the real 411-page tender
- [x] Layout verified by screenshot at 1152 / 1280 / 1366 — nothing past either edge
- [x] `db/sitesource.db` byte-identical to `381397a` — see §10
- [ ] **LIVE mode run end to end** — needs an `ANTHROPIC_API_KEY`; see §9 and `running_live.md`
- [ ] The logo menu's open-on-click — needs one human click; see §9
