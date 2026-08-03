# client_boq build backlog — what can be built now, and the plan for each

Three series. **T1–T8** were built without waiting for the frontend design, because their shape is
determined by how tendering works rather than by how a screen is laid out. **U1–U5** are the UI
build, from the design handoff at `workspace-tendering/design_handoff_client_boq/`, plus the
backend that handoff turned out to need. **R1–R5** are the revision that followed using it.

`BUILD_PLAN.md` at the repo root is the **procurement** roadmap (phases A to D) and is unrelated
to this file. This one is client_boq only.

**Legend** — Size: S is under a day, M is a day or two, L is several days.
Status: `[ ]` not started · `[~]` in progress · `[x]` done.

## Series T — the backend, ahead of any design

| # | Task | Size | Depends on | Status |
|---|---|---|---|---|
| T1 | Return the split as downloadable folders | S | — | `[x]` done 2026-07-30 |
| T2 | List the tenders | S | — | `[x]` done 2026-07-30 |
| T3 | Revision axis (documents change) + .xlsx history | L | — | `[x]` done 2026-07-30 |
| T4 | RFI / clarification loop | M | T3 | `[x]` done 2026-07-30 |
| T5 | Departure Schedule generator | S | — | `[x]` done 2026-07-30 |
| T6 | Letter of Qualifications generator | S | — | `[x]` done 2026-07-30 |
| T8 | Strategy-flag detection at ingest | S | — | `[x]` done 2026-07-30, built with T5/T6 |
| T7 | Verified citation page-locating | M | — | `[x]` done 2026-07-30 |

## Series U — the UI, from the design handoff

Full write-up: **`ui_build.md`** — what the design specified, what the backend actually had, every
decision taken and why, and what it does not do.

| # | Stage | Size | Split | Status |
|---|---|---|---|---|
| U1 | Foundation — tokens, types, API client, app shell, document pane | M | FE + 1 route | `[x]` done 2026-07-30 |
| U2 | Documents tab (frame 01) + in-part search + re-interpret | M | FE + 2 routes | `[x]` done 2026-07-30 |
| U3 | Register tab (frames 02/03) + negotiation text + RFI withdrawal | L | FE + 2 routes | `[x]` done 2026-07-30 |
| U4 | Panels (frames 04, 05, 06) | M | FE only | `[x]` done 2026-07-30 |
| U5 | Scope tab (frame 07) + **the freeze gate** | L | ~half BE | `[x]` done 2026-07-30 |
| U6 | Price and Offer tabs | L | FE | `[x]` done 2026-08-01 — see Series P |

## Series R — the revision after using it

Six complaints from real use. Full write-up in `ui_build.md` §6b.

| # | Stage | Size | Split | Status |
|---|---|---|---|---|
| R1 | Document pane: continuous scroll, typed zoom, lazy pages | M | FE | `[x]` done 2026-07-31 |
| R2 | Layout: derived divider limits, collapse-to-tab, resizable rail | S | FE | `[x]` done 2026-07-31 |
| R3 | Register clarity: `GET /criteria` + the parse-mismatch banner | M | FE + 1 route | `[x]` done 2026-07-31 |
| R4 | Editable context cards + prove a quote against the page | M | FE + 2 routes | `[x]` done 2026-07-31 |
| R5 | LIVE: job polling everywhere, progress strip, run buttons | M | FE | `[x]` done 2026-07-31 |

**U6 was the last open item, and it is now closed** (Series P). It had sat blocked because the
handoff says "Not designed yet" for both steps while their *backend already worked* —
`/estimate/run`, the deterministic .xlsx workbook and the offer-letter draft were built and tested
from the start. What was missing was a drawn screen, so we drew them, following the handoff's own
rules rather than inventing new ones.

**After U1–U5:** 43 routes (from 35), 916 tests passing (from 879), the workflow drivable through
the UI as far as the scope gate.

**After R1–R5** (the revision that followed using it): 46 routes, 931 tests passing. The six
complaints are addressed and LIVE mode works — it could not have before, because no tab polled its
background job. See `ui_build.md` §6b and `running_live.md`.

## Series D — the tender desk (home), and the management screens

From the extended handoff (`workspace-tendering/client register screen wireframe home page/` —
Frame 00 plus the nav sidebar), plus three capabilities the user asked for that the handoff lists
as undesigned or does not contain at all: editing the criteria, editing the costing data, and
choosing the AI model. Decisions taken 2026-07-31: named profiles without passwords; the
Criteria/Rates screens designed here following the handoff's own rules; one app-wide model
setting; the close date built honestly (LIVE reads it with a citation, DEMO admits it cannot).

| # | Stage | Split | Status |
|---|---|---|---|
| D1 | Team + set metadata + the home counts (`blocked` agrees with the gates) | BE | `[x]` done 2026-07-31 |
| D2 | The close date as a FINDING — AI-quoted clause + deterministic parse + confirm-by-hand | BE | `[x]` done 2026-07-31 |
| D3 | Hash routing, nav sidebar, global bar, the shelf, drop-anywhere upload, profile picker | FE | `[x]` done 2026-07-31 |
| D4 | Criteria library: DB-backed (markdown as one-time seed), editable, disable-not-delete | BE + FE | `[x]` done 2026-07-31 |
| D5 | Rate book: the DB source `rates.py` declared itself the seam for; archive-not-delete | BE + FE | `[x]` done 2026-07-31 |
| D6 | App-wide model setting + `make_client()` + the one additive `llm_client.py` change | BE + FE | `[x]` done 2026-07-31 |

**After D1–D6:** 59 routes, 994 tests passing (63 new), 6 new tables. The app opens on the desk;
the browser's own history is the router. Sidebar items without screens (Letter templates, Standard
positions, Clients, Audit log) open and say so, per the no-padlock rule. Full write-up:
`ui_build.md` §9.

## Series L — the layout, the missing PDF, and joining the two products

Five complaints after using the desk. Two shared a root cause nobody would guess from the symptom,
and one floor turned out to have been specified but never enforced. Full write-up: `ui_build.md` §10.

| # | Stage | Split | Status |
|---|---|---|---|
| L1 | Contain the layout: scroller-local scrolling, `min-w-0`/`overflow-hidden`, a real 480px PDF floor, refit on mount + resize, and the handoff's fold-then-collapse degradation order | FE | `[x]` done 2026-07-31 |
| L2 | Make the PDF reliably visible: seed the Register's part, fit-on-open | FE | `[x]` done 2026-07-31 |
| L3 | Register highlights: show the part even when unverifiable, "show me on the page", first-click scroll fix, search no longer hides citation marks | FE | `[x]` done 2026-07-31 |
| L4 | Navigate between the products by click: the SiteSource logo menu, a Procurement button on the desk, Back working both ways | FE | `[x]` done 2026-07-31 |

**After L1–L4:** no backend change at all; verified by screenshot at 1152 / 1280 / 1366 against a
clean DEMO backend. `DOC_MIN` 160 → **480**.

---

## T1 — Return the split as downloadable folders `[x] DONE 2026-07-30`

**Shipped.** `GET /client-boq/ingest/{set_id}/download`, with `?include_source=true` to bundle
the original uploads. Verified on the real 325 tender: a 23 MB archive, 26 entries, 12 part
PDFs totalling 411 pages, 12 context cards, a README stating full coverage.

**Decision taken** (you did not need to answer): the original binder is **excluded by default**
and available behind the query parameter. It roughly doubles the archive and the user already
has it, so paying for it should be a choice.

**A real bug this surfaced.** In DEMO, `s02_interpret` returned the fixture card *before*
checking whether the part was readable — so a scanned part came back with a plausible summary
claiming it had been read. That is precisely the fabrication the stage exists to prevent, and
it made the offline demo dishonest. Readability is now measured first in every mode, and a part
with no text layer gets the honest "not read" card even in DEMO. On the 325 tender the two
scanned parts (`01-inv`, `10-gcc`) now correctly report unread.

**Original plan, for reference:**

**Goal.** A user who uploads one 400-page binder can download it back as the partitioned
folder tree, with the interpreted context cards alongside each part.

**Why now.** This is the thing you actually asked the ingest to produce, and it is nearly free:
the tree already exists on the server after a split. Only the download is missing.

**Plan.**

- New endpoint `GET /client-boq/ingest/{set_id}/download` returning a zip stream, filename
  `{set_id}-split.zip`.
- Build the archive from the existing `store.parts_dir(ws, name)` tree with `zipfile` from the
  standard library, over `io.BytesIO`. At ~25 MB for the 325 tender that is comfortable in
  memory; if a larger binder ever makes that uncomfortable, spool to a temp file instead.
- Archive contents:
  ```
  README.md                 the part table, page ranges, coverage, confidence tier
  split-manifest.json       the approved manifest
  01_INV/  <part>.pdf + context.md
  02_CT/   <part>.pdf + context.md
  ...
  ```
- **Fix a loose end while here:** `ingest/run.py::split_readme()` is written but never called —
  dead code today. It produces exactly the README this archive needs, so wire it in rather than
  writing a second one.
- 404 when the set has no parts. No gate check needed: parts only exist after the manifest gate.

**Verification.**

- The archive opens; entry count equals `2 + 2 x parts`.
- Each part PDF inside reopens at the page count the manifest claims.
- A scanned part's `context.md` still says "not read" rather than carrying invented content.
- Run against the real 325 tender: 12 folders, 411 pages across them.

**Decision I need.** Include the original uploaded binder in the archive under `source/`? It
makes the download a complete package, at the cost of roughly doubling its size.

---

## T2 — List the tenders `[x] DONE 2026-07-30`

**Shipped.** `GET /client-boq/sets`, newest first, one SQL query joining the set against all
three gate tables plus a part count. Returns exactly the shape below, including the headline
price pulled from the estimate blob without validating the whole model.

Pagination was not added, as proposed. Say so if you want it.

**Original plan, for reference:**

**Goal.** One endpoint that answers "what am I working on?", so the frontend has a home screen.

**Why now.** Every possible design opens on a list. There is nothing to call today, so this
blocks the first screen of any wireframe regardless of how it looks.

**Plan.**

- New `store.list_sets(conn)` joining `client_boq_document_sets` against the three gate tables
  (`client_boq_manifests`, `client_boq_review_registers`, `client_boq_estimate_scope`) plus a
  count from `client_boq_parts`.
- New endpoint `GET /client-boq/sets`, newest first. Per row:
  ```json
  {
    "set_id": "cic-325-attc-l5",
    "name": "CIC 325 ATTC L5",
    "status": "estimated",
    "created_at": "2026-07-28T10:12:00",
    "parts": 12,
    "gates": { "manifest": true, "review": true, "scope": true },
    "price": 6985002.25
  }
  ```
- The three booleans are what a status chip renders from, whatever the design turns out to be.

**Verification.** After running the full 325 chain, `GET /client-boq/sets` returns one row with
all three gates true, 12 parts, and the estimate price.

**Decision I need.** None. Pagination is not worth adding at single-firm scale; say so if you
disagree.

---

## T3 — Revision axis (documents change) `[x] DONE 2026-07-30`

**Shipped.** Four tables (`client_boq_documents`, `client_boq_parts` slimmed to identity,
`client_boq_part_revisions`, `client_boq_changes`), the addendum pipeline behind a change-mapping
gate, verdict reopening, the history endpoints, and the .xlsx revision workbook. Five new
endpoints; 16 new tests; the suite went 810 -> 826 with no test changes needed for step 1, which
was the proof the operative view is transparent.

**Verified on the real documents.** The ND/2025/04 Bill of Quantities genuinely exists at three
revisions issued by two addenda, and the system carried it through all three: Rev 0 -> Rev 1
(TA#1) -> Rev 2 (TA#2), each retained as a distinct file, causes correctly recorded as
`base/addendum/addendum`, the set replayable to any of the three points, and both addenda listed
for acknowledgement in the workbook while a correction is deliberately excluded.

**Two things worth knowing:**

1. **A stale schema was found in the wild.** The DEMO scratch database was still carrying a
   `client_boq_parts` table from before `source_doc` was added mid-development — `CREATE TABLE IF
   NOT EXISTS` never alters an existing table, so the column had been silently missing there all
   along. The migration now reads only the columns a given database actually has. Any long-lived
   database in this repo can be sitting on any earlier column set; assume nothing about its shape.
2. **Re-splitting is not a revision.** Editing the manifest and re-cutting rewrites the SAME rev.
   A manifest edit is a better reading of one document, not a new document, and counting it would
   fill the history with noise from ordinary fiddling. Only a new FILE creates a revision.

**Original plan, for reference:**

**Goal.** Model the fact that a tender is not static: addenda amend documents, parts move from
Rev 0 to Rev 1 to Rev 2, and you must know which revision you actually priced.

**Why now, and why it is urgent.** Today `set_id` equals the slug equals a pure function of the
project name, and every table upserts over itself — so re-ingesting a set silently *replaces* it
and no history exists. Every feature built while that holds is a feature written on the
assumption that documents never change. It is the hardest thing here to retrofit, and it
unblocks three separate things: addenda, repricing against revised scope, and the
addendum-acknowledgement returnable whose absence can void a bid.

**Plan — deliberately two steps, because step one must be invisible.**

*Step 1: introduce revisions with nothing changing behaviourally.*

- New table `client_boq_documents(set_id, doc_id, filename, kind, ref, received_at)` where
  `kind` is `base | addendum | clarification`. The originally uploaded binder becomes the one
  `base` row.
- Split the current `client_boq_parts` in two, matching the Part / PartRevision distinction:
  - `client_boq_parts` keeps the **stable identity**: `(set_id, part_id)`, title, abbr, slug,
    category.
  - New `client_boq_part_revisions(set_id, part_id, rev, doc_id, start_page, end_page, scanned,
    pdf_path, context_json, operative)` holds everything that can change.
- Every existing part becomes `rev = 0, operative = 1`.
- `store.load_parts()` keeps its exact signature and returns the **operative revision** of each
  part. Every downstream caller — review, estimate, the router — is untouched.
- **The whole 798-test suite must stay green after step 1 with no test changes.** That is the
  proof the operative view is transparent.

*Step 2: the addendum pipeline on top.*

- `POST /client-boq/ingest/addendum` — upload an addendum against an existing set. Classify it,
  warn on a contract-number mismatch, extract its own table of changes.
- New `client_boq_changes(set_id, change_id, doc_id, kind, part_id, description)` where `kind`
  is `replace-pages | add-part | delete-part | textual-amendment`.
- **A new human gate** showing the proposed change mapping before anything is committed —
  the same pattern as the manifest gate, for the same reason.
- On commit: affected parts gain `rev + 1`, the previous revision is marked non-operative, and
  only the changed parts are re-interpreted. Cheap, because nothing else is touched.
- Clarifications take a separate lane: recorded and summarised, **never** bumping a revision.
  Both reference tenders state clarifications are non-contractual, and the system should not
  quietly disagree with the contract.
- `GET /client-boq/revisions/{set_id}` returns the history, which is what the addendum
  acknowledgement returnable is generated from.

**Verification.**

- Step 1: the existing suite passes unchanged. This is the whole test.
- Step 2: a synthetic addendum replacing pages 5 to 16 produces rev 1 of part `02-ct`, marks
  rev 0 superseded, leaves the other 11 parts at rev 0, and a review run reads only operative
  revisions.
- The change log states what changed and why it matters, per addendum.
- Re-running the review after an addendum produces a register that cites the new revision.

### Evidence from the real package (ND/2025/04), checked 2026-07-30

Counted across `OneDrive_2026-07-21/ND202504 Contract Dcos/`:

| Finding | Detail |
|---|---|
| Revisions live on the **document**, in the filename | `I-ND_2025_04_BQ-0.pdf` then `-1` then `-2` |
| Most documents are never amended | **154 at Rev 0, 9 at Rev 1, 2 at Rev 2** — about 7% ever changed |
| One document changed twice | the BQ, the priced document, which attracts the most queries |
| An addendum ships **only the replacements** | TA#1 carried 8 documents across `BQ/`, `GP&PP/`, `S/PS/{PS1,PS7,PS25,PS27}/`; TA#2 carried 2, both BQ |
| The addendum is itself a document | `Tender Addendum No.1.pdf`, carrying a change table: 14 changes in TA#1, 3 in TA#2 |
| Clarifications ship separately and change nothing | `TC No. 1 & 2/`, two fax letters, expressly non-contractual |

**Consequence: revisions are per-part, addenda are the events that bump them, and the two are
linked.** Representing 11 real changes as whole-set snapshots would mean storing 154 unchanged
documents three times over. The Excel-tab view survives intact and costs nothing: a tab is an
addendum event, and "the tender as at TA#1" is each part's latest revision at or before that
event. For this tender that is exactly three tabs — Base, after TA#1, after TA#2.

**A guardrail the package taught us.** Tender Addendum No.1 states its own remarks column is
"neither exhaustive nor guaranteed to be accurate" and that the tenderer must check the actual
replacement pages. So the change table we extract is a **navigation aid, never the operative
record** — the replacement document is the authority. The change-mapping gate must therefore show
the human the replacement pages themselves, not only the model's reading of the summary table.

### Decisions

**DECIDED by the user, 2026-07-30 — nothing is ever destroyed.**

A corrected base re-upload does **not** replace Rev 0. It creates a new adjusted copy as Rev 1,
and Rev 0 is retained and remains viewable. The mental model given was **Excel worksheet tabs**:
each revision is its own sheet, all of them kept, the newest operative and the earlier ones still
there to flip back to.

This is stricter than the "replace" I had proposed, and it is the safer rule. It also makes the
model uniform: *every* change appends a revision, whether it came from the client (an addendum)
or from you (a correction). Nothing in the system ever overwrites a revision.

Consequence to build in: a revision must record its **cause** — `base | correction | addendum |
clarification` — because the addendum-acknowledgement returnable (R3) must list only the client's
addenda, never your own corrections. Without that field the acknowledgement would be wrong in a
way that is hard to spot.

**DECIDED, 2026-07-30 — stale verdicts are reopened and flagged.** When an addendum rewrites a
clause the register already has a verdict on, the verdict is cleared and the line is marked "the
underlying clause changed, re-review". The old verdict stays in the history, so nothing is lost,
but nobody can submit a departure schedule built on wording that no longer exists.

**DECIDED, 2026-07-30 — superseded revisions are view-and-compare only.** You can open an old
revision, read its context card, download its PDF and diff it against a newer one. The review and
the estimate always run on the operative revision. Nobody bids a superseded document, so the
much larger build of making every downstream table revision-aware is not worth it.

**DECIDED, 2026-07-30 — an .xlsx revision history is a real deliverable, not just a metaphor.**
Alongside the stored revisions, generate a workbook with one worksheet per addendum event
(Base, after TA#1, after TA#2), each listing every part with its operative revision at that
point, plus a changes sheet naming document, amended pages and what changed. It follows the
existing `estimate/workbook.py` openpyxl patterns and doubles as the evidence behind the
addendum-acknowledgement returnable (R3).

**Revision `cause` is required** on every revision: `base | correction | addendum | clarification`.
The acknowledgement returnable must list only the client's addenda, never your own corrections,
and without this field it would be subtly wrong.

---

## T4 — RFI / clarification loop `[x] DONE 2026-07-30`

**Shipped.** Two tables (`client_boq_rfi_items`, `client_boq_rfi_batches`), the fourth register
verdict `query`, five endpoints, and the numbered query letter. 19 new tests; the suite went
826 -> 845.

The lifecycle is `draft -> sent -> answered | overtaken | withdrawn`, and `RFI_OPEN =
{draft, sent}` is the count the freeze gate will have to see reach zero.

**Three things worth knowing:**

1. **`query` is a verdict, but not a closing one.** `HUMAN_VERDICTS` now holds three values and
   the approve endpoint is still their only writer; `CLOSING_VERDICTS` is the subset that closes a
   line. A queried line keeps `register_status = "open"` and does not block approval, so the count
   travels on the gate state instead — an open question that stops being visible is the one real
   risk of the non-blocking choice.
2. **A citation_failed line can be queried, though it still cannot be confirmed.** Asking the
   client about a clause whose citation we could not verify is usually the correct response, so
   the guard blocks confirmation only.
3. **An addendum overtakes open questions on the parts it amends.** A question about a clause the
   client has since rewritten has been answered, whether or not anyone wrote back; leaving it open
   would have you chasing a reply that is not coming, and would hold a stale item in the freeze
   count. `answered_by` records which document did it.

**The letter is assembled by code; the model writes only the wrapper** — salutation, one opening
paragraph, a sign-off. The questions themselves are reproduced verbatim with their clause and page
citations, because a paraphrased query asks the client something other than what was meant. If the
model call fails the letter still renders with plain fallback prose: a query letter must go out on
the day the cut-off falls.

**Original plan, for reference:**

**Goal.** The conversation with the client: raise questions, batch them into a letter, record
what comes back, and know which of your questions are still open.

**Why now.** It is the missing middle of the workflow, and the register's fourth verdict — *ask
the client* — has nowhere to go without it. Depends on T3 because an answer often arrives as an
addendum.

**Plan.**

- `client_boq_rfi_items(set_id, rfi_id, origin, register_item, clause, question, status,
  raised_at, batch_id, answer, answered_at)`.
  - `origin`: `register | pricing | manual`. The `pricing` origin matters — many real questions
    surface only while someone is trying to put a number on something.
  - `status`: `draft | sent | answered | overtaken | withdrawn`. `overtaken` is for a question an
    addendum answered before the client ever replied to you.
- `client_boq_rfi_batches(set_id, batch_id, ref, sent_at, letter_md)`.
- Register gains a fourth verdict, `query`, alongside `confirmed` and `dismissed`. It is written
  only by the approve endpoint, exactly like the other two.
- Endpoints: `POST /rfi` (raise), `POST /rfi/batch` (assemble and draft the letter),
  `GET /rfi/{set_id}`, `POST /rfi/answer` (record a reply, optionally linking the addendum that
  carried it).
- The letter is assembled deterministically — numbered questions, each with its clause citation
  and page — with the model drafting only the covering prose.

**Verification.**

- Raise a query from a register line, batch it, and the generated letter carries the numbered
  question with the correct clause and page citation.
- Record an answer: the item moves to `answered` and the register line shows the resolution.
- An addendum that supersedes the clause moves any open item on it to `overtaken` automatically.
- Open queries are visible and countable at any time, because that count is what tells you
  whether you are ready to freeze.

**DECIDED, 2026-07-30 — open queries do NOT block review approval.**

A line marked `query` carries forward as a visible open item. The register can still be approved
and the estimate can still run. The forcing function sits at the **freeze** gate instead: nothing
may be open there, so every unanswered query must become either an answer or a stated, priced
assumption, and those assumptions flow into the Letter of Qualifications (T6) that goes out with
the bid.

The reasoning is what the reference tender shows: Tender Clarification No. 1 alone carried 17
questions, answered in stages across TC1, TC2 and two addenda, and the submission deadline never
moved for any of them. Blocking would mean pricing a 400-page tender in the last days before
submission.

**Consequence for the UI:** the open-query count must be prominent rather than buried. The risk of
non-blocking is not that a question gets lost — the freeze gate catches that — but that it stops
being visible in the meantime.

**Consequence for the review gate:** `HUMAN_VERDICTS` currently holds `confirmed`/`dismissed` and
the approve endpoint is their only writer. `query` joins them under the same rule, and a queried
line is `register_status = "open"` rather than `closed`, so it stays actionable.

---

## T5 and T6 — the two client-facing documents `[x] DONE 2026-07-30`

### The finding that reshaped both

Checking the real tenders before building, as asked, turned up something that changes what these
documents are for. **Both reference tenders penalise qualifying a bid:**

> "Any qualification of the tender may cause the tender to be disqualified."
> — ND/2025/04, General Conditions of Tender **GCT 4**, page 6

> "Any qualification of tender or of the tender documents may cause the tender to be disqualified."
> — CIC (325), Conditions of Tender **4.26**, page 8

Reinforced by GCT 23 (uninvited alternative tenders "shall not be considered") and CIC 4.27 (no
unauthorised alteration to the documents). It is standard Hong Kong public and institutional
procurement language, and it is discretionary rather than automatic — but it means a Letter of
Qualifications is a commercial risk, not routine paperwork.

It also explains why T4 matters more than first credited: **the sanctioned route for a problem
clause is a query before the cut-off**, where an answer amends the contract for every tenderer.
Your own package shows exactly that — 17 questions in TC1, and the substantive answers came back
as addenda.

### What shipped

Both generators live in `client_boq/outputs/` and are **internal by default**, with a submission
version opt-in via `?audience=submission` that quotes the tender's own clause as a warning banner.

* **Departure Schedule** — `GET /client-boq/review/{set_id}/departure-schedule?audience=&format=md|xlsx`.
  Confirmed departures plus open queries marked "Subject to outstanding clarification" (your
  decision: the schedule should show every unresolved contractual point). A `citation_failed` line
  is **withheld and listed separately** — you cannot ask a client to amend a clause you could not
  locate in their own document.
* **Letter of Qualifications** — `GET /client-boq/estimate/{set_id}/qualifications?audience=`.
  Assembled from confirmed departures, **unanswered queries** (an open question is a priced
  assumption whether or not anyone writes it down — this is what T4 unlocked), and the approved
  scope. Every line carries its source in the internal copy.
* **Strategy-flag detection at ingest** (logged as T8, built here): the interpret stage now looks
  for conditions that change how you BID rather than what you price — qualifications penalised, no
  alterations, alternatives not considered, two-envelope, query cut-off, submission deadline — and
  surfaces them on `GET /ingest/parts/{set_id}` with `penalises_qualifications`. Quoted with clause
  and page so a human can check them. The point is timing: knowing on day one changes how the
  review is run; learning at submission is learning after the cut-off has passed.
* **The offer letter now references the two attachments** instead of restating their contents, so
  a departure has one source of truth. One existing test moved with it.

Both documents are wholly deterministic. 16 new tests; the suite went 845 -> 861.

**Original plan, for reference:**

## T5 — Departure Schedule generator

**Goal.** Export the approved departure register as a document you can actually submit.

**Why now.** The data already exists and the decisions have already been made at the gate. This
is formatting, not intelligence — the cheapest high-value item on the list.

**Plan.**

- Deterministic assembly from register items with a `confirmed` verdict.
- Columns: item number, clause reference, as drafted, our departure, reason, proposed amendment.
- Markdown and `.xlsx`, reusing the openpyxl patterns already in `estimate/workbook.py`.
- `GET /client-boq/review/{set_id}/departure-schedule?format=md|xlsx`.
- **Exclude `citation_failed` items entirely.** You cannot send a client a departure against a
  clause whose citation could not be verified. This falls out of the existing s08 guard and is
  a safety property worth having explicitly.

**Verification.** Every row traces back to a register item by number; the row count equals the
confirmed departures; no row exists without a clause reference; a `citation_failed` item never
appears.

**Decision I need.** Should `dismissed` items appear anywhere, for instance as an appendix of
"terms reviewed and accepted"? Some issuers like the completeness; most do not ask.

---

## T6 — Letter of Qualifications generator

**Goal.** The standalone document stating the assumptions and exclusions your price depends on.

**Why now.** Same reason as T5 — the assumptions register already exists and currently surfaces
only as appendix bullets inside the offer letter, which is not a submittable document.

**Plan.**

- Deterministic assembly, with the model drafting only the preamble prose.
- Sources, each line carrying its origin tag so nothing is free-floating:
  - assumptions injected from confirmed register departures,
  - exclusions and inclusions from the approved scope of record,
  - later, once T4 exists: assumptions created at freeze from unanswered RFIs.
- `GET /client-boq/estimate/{set_id}/qualifications?format=md`.
- Every number is code-injected, never model-written — the same discipline the offer letter
  already follows.

**Verification.** Every qualification traces to a tagged source; no sentence exists that is not
derived from a register item, the scope of record, or an open assumption; numbers match the
persisted estimate exactly.

**Decision I need.** None yet, but this document is where your commercial judgement lives, so
expect to rewrite my default wording once you see it against a real bid.

---

## T7 — Verified citation page-locating `[x] DONE 2026-07-30`

**Shipped.** `pdfops.locate` / `has_text_layer`, `s08_citation_verify.locate_citations`, and
`GET /client-boq/review/{set_id}/citations`. 18 new tests; the suite went 861 -> 879.

**Full write-up: [`citation_locating.md`](citation_locating.md)** — the measurements, the design,
and what it does not cover. In brief:

- The open decision was resolved by measuring first: **1,769 of 1,769 verbatim single-line
  quotations were found** across the two tenders, and paraphrases were correctly rejected. So a
  miss is meaningful, and a harder verdict than the "soft flag" originally proposed is justified —
  but only where the document was searchable.
- Hence **three verdicts**: `located` (page measured, rectangles returned), `unverifiable` (no text
  layer — not the citation's fault), `not_located` (searchable, corroborated, still missing).
- **Corroboration before accusation**: a citation is called wrong only when another citation from
  the same part was found. Otherwise a parse/file mismatch would condemn everything at once.
- Two assumptions were corrected by the measurement: ligatures and soft hyphens are a non-issue
  in these documents (zero across 85 pages), while **curly punctuation is the real hazard** (81
  curly quotes in the ND GCT alone) and defeated a live search until typographic variants were
  added. A second probe suggesting a 48% multi-line failure rate was the test's own fault and is
  documented so nobody repeats it.

**Original plan, for reference:**

## T7 — Verified citation page-locating

**Goal.** Know the page a quoted clause is *physically* on, and where on that page it sits.

**Why now.** It is a computation, so it does not depend on the design. It also closes a real gap:
`s08_citation_verify.py` proves the cited clause exists in the parse and that the quoted text
sits inside it, but it never checks the page number — and that number is model-supplied. A
click-to-source viewer built on it could land the user on the wrong page while the register
still reports the citation as verified.

**Plan.**

- New `pdfops.locate(part_bytes, needle) -> list[(page, [rects])]` using PyMuPDF's
  `page.search_for()`, which returns bounding boxes directly.
- Normalise whitespace before searching; if the exact quote fails, retry on its longest
  distinctive substring, since extraction differences (ligatures, columns, hyphenation) can
  break an exact match on text that is genuinely present.
- Upgrade s08 to record the **located** page and rectangles on `CitationCheck`, so the page a
  citation points at is measured rather than claimed.
- Explicitly **out of scope here:** rendering pages to images and anything about how highlights
  are displayed. Those wait for the wireframe.

**Verification.** On the real 325 tender, take genuine clause text out of a part, locate it, and
assert the returned page is the page it is actually on with non-empty rectangles. Assert that
text which is genuinely absent returns nothing rather than a false position.

**Decision I need.** When the quote cannot be located on any page, is that a hard
`citation_failed`, or a softer "verified against the parse, not located on the page"? I lean
**soft**, because PDF text extraction fails for legitimate reasons and a hard failure would flag
real citations as untrustworthy. But it is a judgement about how much you want the tool to
insist on proof.

---

## Not in this backlog, and why

**Waiting on your wireframe** — the shape of these is decided by the layout, and building them
blind means rework: the page-rendering endpoint (eager or lazy, DPI, thumbnails), the register
response shape for a side-by-side view, job progress granularity, and the freeze screen.

**Waiting on your domain input** — the acceptable-terms library and the rate library need your
firm's real clause positions and real rates. No backend or design work substitutes for them, and
they are what make the review and the pricing yours rather than generic.

**Waiting on infrastructure decisions** — management sign-off needs multi-user roles, and there
is no auth anywhere in the app today. Jobs also live in an in-process dict and uploads on local
disk, so a restart drops work in flight. Both are real, and neither is a client_boq problem to
solve alone.

## Series P — the last two screens: Price and Offer

The five-step workflow now runs end to end in the UI. Both screens were designed here, from the
handoff's rules, because it lists them as undesigned.

| # | Stage | Split | Status |
|---|---|---|---|
| P1 | Estimate + letter types and API methods | FE | `[x]` done 2026-08-01 |
| P2 | Price: run the estimate, the build-up, per-line cost traces, the five rule flags, the workbook | FE | `[x]` done 2026-08-01 |
| P3 | Offer: the letter draft, per-line appendix provenance, the two companion documents | FE | `[x]` done 2026-08-01 |
| P4 | A latent `usePanes` bug the new tabs exposed: a container that mounts late was never measured | FE | `[x]` done 2026-08-01 |

**After P1–P4:** no backend change; every one of the 59 routes now has a screen that uses it except
the revision workbook. Full write-up: `ui_build.md` §11.
