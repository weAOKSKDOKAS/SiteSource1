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

## Series S — the schedule, so LIVE can price

Checking each LIVE branch against what the UI actually sends found that three of the five steps
were ready for a real API key and the fourth could never have been: `/estimate/run` requires
`margin_pct` **and** a structured `schedule` in LIVE, DEMO filled both from a fixture, and there was
nowhere in the app to type a bill of quantities. `CONTEXT.md` says quantities are *given* ("no
take-off in this slice"), so the schedule was always meant to come from outside — nobody had built
the door.

| # | Stage | Size | Split | Status |
|---|---|---|---|---|
| S1 | `client_boq_schedules` + `GET`/`POST /estimate/schedule` | S | BE | `[x]` done 2026-08-01 |
| S2 | The schedule editor on the Price tab (rate-book-backed) | M | FE | `[x]` done 2026-08-01 |
| S3 | The letterhead: `letter.*` settings + `POST /company`, wired from set metadata | S | FE + 1 route | `[x]` done 2026-08-01 |
| S4 | Reasoning-model truncation in the shared LLM client | S | BE | `[x]` done 2026-08-01 |

**After S1–S4:** 62 routes, 1,006 tests. All five steps run in LIVE. Full write-up in
`ui_build.md` §12; the live-run findings are in `running_live.md`.

## Series C — reading the live register

What using the first live run in the UI turned up. Full write-up in `ui_build.md` §13.

| # | Stage | Size | Split | Status |
|---|---|---|---|---|
| C1 | Clause references: prefixes, multi-clause strings, sub-clause limbs | S | BE | `[x]` done 2026-08-02 |
| C2 | Composite quotations checked against all the clauses a line cites | S | BE | `[x]` done 2026-08-02 |
| C3 | The page mark becomes a highlighter — multiply, no border | S | FE | `[x]` done 2026-08-02 |
| C4 | Dismiss the marks: Escape and a Clear chip | S | FE | `[x]` done 2026-08-02 |

**After C1–C4:** `citation_failed` on the live CIC register falls 10 → 3, and the three that remain
name the fragment that is genuinely missing. No route change; 1012 tests.

## Series B — the bill of quantities, and the costing model behind a rate

What studying the real ND/2025/04 package turned up, and what it forced. Full write-up:
`prd_boq_costing.md`.

The estimate half did not model what it claimed to. `EstimateSchedule` is a flat list of invented
activities with no bill, no item numbering, no client quantity and — the load-bearing omission — **no
unit rate**, only `activity_total`. But the contract this module exists to serve hands you a finished
bill of 166 numbered items in a workbook you are required to price *in place* (GCT App A 9: the bill
"shall only be submitted in Editable File format, i.e. the Microsoft Excel format"; para 10: using
"the electronic files ... provided by the Client"). There was nowhere to put it. Locked decision 1
had said quantities come "from a **BOQ** or manual entry" and `estimate/s02_schedule.py:9` had marked
itself the seam; nobody had built the door.

| # | Stage | Size | Split | Status |
|---|---|---|---|---|
| B1 | `boq/reader.py` — the workbook, and the four things in it that break a naive reader | M | BE | `[x]` done 2026-08-03 |
| B2 | `boq/diff.py` — revision diff keyed on the item reference, caption chain included | M | BE | `[x]` done 2026-08-03 |
| B3 | `boq/carry.py` — the client's own re-pricing rules (GCT App C 2.2(v)) + `needs_review` | S | BE | `[x]` done 2026-08-03 |
| B4 | `boq/production.py` — the condition mix: where the resource quantities come from | M | BE | `[x]` done 2026-08-03 |
| B5 | `boq/pricing.py` — unit rate, lump items, the spread pool, the roll-up | M | BE | `[x]` done 2026-08-03 |
| B6 | `boq/checks.py` — seven guards, each naming the clause it enforces | S | BE | `[x]` done 2026-08-03 |
| B7 | 3 tables, 9 routes, and the re-price gate | M | BE | `[x]` done 2026-08-03 |
| B8 | A latent 500 the addendum → re-price loop walks straight into | S | BE | `[x]` done 2026-08-03 |

### The finding that decided the design

**The workbook does not mark what changed. At all.** Across all three revisions: every one of 1,239
non-empty cells in Rev 2 has `fill_type = None`, changed rows carry the same font as unchanged rows,
there are zero cell comments, no defined names and no tracked changes. Rev 1 carries a sheet-level
print footer on the bills it touched; **Rev 2's spreadsheet carries no revision marking whatsoever**
(its PDF twin does — the two deliverables disagree).

So the largest price movement in that tender reached the tenderer as seven words —

> "Updated the quantities of item nos. 6.4 – 6.6."

— covering three unmarked cells mid-page that took groundwater monitoring from 24 weeks per
instrument to 52 (1,128 → 2,451, 1,623 → 3,546, 2,760 → 5,996 nr-wk; ×2.17). The tenderer asked for
one extra week to reprice it and was refused, twice. And the addendum disclaims its own summary as
"neither exhaustive nor guaranteed to be accurate" — correctly, since one of its three bill remarks
is factually wrong (it says item 3.2 was split into "3.2a and 3.2b"; only 3.2a exists).

A machine diff is the only honest defence, which is what B2 is.

### Identity is the item reference, never the row

Across both transitions: **0 items renumbered, 0 deleted**, 35 moved rows. When they inserted the
signboard they numbered it `1.61A` — a suffix letter — so 1.62 and 1.63 would not have to move. When
they split 2.2 they kept 2.2 as a caption and put bare `a`/`b` beneath it. So the diff keys on
`(bill_no, full_ref)` and reports a move as *not a change* — otherwise 35 false changes bury 5 real
ones, which is how a safeguard stops being read.

### The four things that break a naive reader (B1)

1. **Item references are floats.** Item `1.20` is stored as `1.2` — the same value as item `1.2`.
   **Twelve collisions** in Rev 2, separated only by `cell.number_format` (`General` vs `'0.00'`).
   Read `cell.value` alone and two differently-priced items silently merge. The reference is now
   rendered *through* the format, and a lossy render is reported (the real bill holds `2.244` under
   `'0.00'` and prints "2.24").
2. **There is no description column.** Description spreads across B/C/D and *the column is the indent
   level*, plus hard-wrapped continuation rows whose leading spaces are load-bearing. Item 2.9's own
   cell reads "maximum depth not exceeding 3.00m" — meaningless until read up to "Extra over for
   excavation in rock". General Preambles 2 makes that contractual.
3. **`Bill No.4` is structurally corrupt**: `max_column = 16384`, ~76,500 stray cells and 9,963 merged
   ranges from an old fill-right that still says "Bill No. 1" inside Bill 4. It printed fine for
   years; openpyxl `MemoryError`s enumerating it. Every read clamps to column H.
4. **Page references exist only as `row_breaks` geometry.** `BQ/2/1` is in no cell, yet the Index,
   the Grand Summary and both addenda all cite it.

One limit is the format's and not the reader's, and is documented rather than papered over: captions
in the same column cannot be nested (`Trial Pits and Inspection Pits`, `Trial pits`, `Inspection
pits` and `Extra over for excavation in rock` all sit in column B at four levels of meaning, and
leading whitespace is applied inconsistently). The SMM section banner is tracked separately, because
it is detectable and was otherwise being overwritten by the first group caption beneath it.

### The costing model (B4/B5)

The resource → cost engine in `estimate/s03_cost_buildup.py` was already right and is reused
unchanged. What was missing sat either side of it.

*Below*: the bill says `2,300 m` of drilling and one rate, but does not say which holes. The SMM
slices drilling by material, hole size, depth stage (20 m bands from existing ground level) and class
of site; the consultant's QS worked it out hole by hole from the drawings and summed. Pricing runs
that backwards. `ItemAssumption` holds the mix and the output rate in each condition, cites the
drawing page it came from, and expands deterministically into shifts and crew-hours. **The mix must
reconcile to the client's quantity and is never scaled to fit** — the total is fixed (GCT 6), so a
mix that disagrees is an error in the mix, and a rate built from a silently corrected one is
indistinguishable from a right answer.

*Above*: `unit_rate = money(priced_cost / qty)`. `CostActivity` gave a total; the box on the form
wants a rate, and under Option B that rate is what every remeasured metre is paid at for the life of
the contract.

Also `SpreadLine`: costs with no bill item at all — 31 deemed-included heads plus the "no separate
item" instructions (PP 11/2A site uniform, NTT C2, NTT C25) — pooled and allocated pro rata on value,
with the rounding residue landing on **one named item** rather than smeared invisibly.

### The re-price gate (B7)

The mirror of decision 7. A revision reopens the **rates** that depended on it:
`POST /boq/{set_id}/revision/{rev}/sign-off` 409s while any carried rate is unconfirmed, naming them.
Carrying a 24-week rate onto a 52-week quantity is what App C 2.2(v) prescribes and is not a decision
anybody made.

### B8 — the latent 500

`router.py:2050` read `doc["applied"]`, a key `store.list_documents` never returned. The `or`
short-circuits for the base document, so it only fires once a set holds a **second** document — and
every scope test ingested one binder and stopped. `GET /estimate/scope/{set_id}/sources` therefore
500'd the moment a real addendum arrived, which is exactly the loop that scope exists to serve.
`applied` is now derived from the revision rows (received is not applied: `/ingest/document`
proposes and commits nothing), with a regression test proven to fail without the fix.

**After B1–B8:** 71 routes, **1,102 tests**. No model call anywhere in `boq/` — every file is
deterministic, which is what makes the package provable offline. Tests run against a generated
workbook (`tests/_bqfixture.py`) reproducing each measured trap, so no client tender data enters the
repository.

**Not in this slice:** the UI; writing rates back into the client's workbook (required for a real
submission, deferred on the evidence of that corrupt sheet — it needs byte-level proof and a
paste-the-rates fallback); reading the drawings with vision to draft a condition mix (the seam is
`boq/production.expand`, which takes an `ItemAssumption` as an argument); an AI reading of the
preambles to propose what belongs in the spread pool; and take-off, which stays out per decision 1.

## Series E — the costing engine, modelled on a real estimator's workbook

The governing question, and it reshaped the design: *"the person who can already do the work will just
do it himself, because he trusts his own work — how do I augment him rather than automate him?"*

So the dividing line for every feature: **if two good estimators would get the same answer it is
clerical and the app does it; if they would disagree it is judgement and the app asks.** The product
is a clerk and a checker, not an estimator.

| # | Stage | Size | Split | Status |
|---|---|---|---|---|
| E1 | `boq/duration.py` — the day-by-day drilling simulation | M | BE | `[x]` done 2026-08-03 |
| E2 | `boq/resources.py` — classes, coefficients, duration drivers, materials from geometry | M | BE | `[x]` done 2026-08-03 |
| E3 | `boq/allocate.py` — `RateRecipe`, and the blend across hole groups | M | BE | `[x]` done 2026-08-03 |
| E4 | `boq/schedule.py` + `criteria.py` — the station table and the general-notes rules | S | BE | `[x]` done 2026-08-03 |
| E5 | `boq/groups.py` — spreads, proximity clustering, the 80/11 reconciliation | M | BE | `[x]` done 2026-08-03 |
| E6 | `boq/derive.py` — recompute the bill's quantities and report the divergences | M | BE | `[x]` done 2026-08-03 |
| E7 | `boq/docmap.py` — the Particular Specification index as a lookup | S | BE | `[x]` done 2026-08-03 |
| E8 | `boq/unbilled.py` — the gate on costs with no bill item | S | BE | `[x]` done 2026-08-03 |

### The finding that made it buildable

**The drawings are readable.** An earlier pass concluded all 33 sheets were useless because
`get_text()` returns 29 characters — true, and the wrong test. They are flattened raster, so a *text*
extractor sees nothing. Rendered at 420 dpi and read with **vision** they are crisp:

- **GI/210** is the station schedule: one row per borehole with easting, northing, ground level,
  rockhead, total depth, **tentative length in soil**, **expected length in rock**, standpipe ✓ and
  piezometer ✓ — plus a second table of **21 trial pits**. This is the take-off, and it includes the
  material split, which a previous write-up had declared underivable from any drawing. It was a
  printed column.
- **GI/100** carries every rule: sampling at 2.0 m, trial pits 1.5 × 1.5 × 3.0 m sampled at 1 m from
  0.5 m, an inspection pit at every drillhole, termination at 5 m of Grade III+ rock or 80 m, *"up to
  two standpipes/piezometers … in each drillhole"*, monitoring *"at least 12 months"*, and Table 1's
  tentative test counts.
- **GI/020/021** give the working areas as four corner coordinates each — every one a 10 × 5 m plot.
- **GI/200–205** are 1:2000 contoured plans: which holes are beside a highway and which are up Saddle
  Pass.

### Every row is checked twice, which is why reading a picture is safe here

Per row, the schedule must satisfy its own arithmetic — `length = soil + rock`, verified on the real
sheet (29.90 + 5.0 = 34.90 · 21.10 + 5.0 = 26.10 · 23.11 + 5.0 = 28.11). Per item, the totals must
equal the client's own bill — Σ soil = 2,300 m, holes = 91, standpipes = 47, piezometers = 68.

**The bill is the answer key for our reading of the drawing.** Where the two disagree, that is the most
valuable output, not a failure. Two already exist: GI/100 Table 1 gives 52 permeability and 30
pressuremeter tests against the bill's 54 and 31; and the Particular Specification's index heads
SECTION 28 with section 29's title, while its own clauses and the contents page both say Environmental
Ground Investigation. `docmap` reports that rather than silently correcting it — guessing which of the
client's two statements is true is not a parser's job.

### The costing model, reproduced to the cent

`E1`–`E3` reproduce a working estimator's spreadsheet exactly, and that is the regression test for the
whole design — if our number and his differ on his inputs, the code is wrong.

```
days        soil_rate = 20 m/day × (1 − 5%)^floor(cum_soil/20)   ← decays per 20 m band, as the SMM stages
            day_left  = 1 − soil_today/soil_rate                  ← soil finishing at 11am gives rock the afternoon
            60 m soil + 72 m rock → 11 days · soil 3.1108 d · rock charged 7.8892 d

resources   every line = rate × qty × coefficient, then × 1.33
            drivers      n = 11 (labour, PM, geologist, consumables) · n+4 = 15 (plant, staff)
            coefficients rig 1.23 · workers 2 · PM 0.33 ("split across three jobs") · water barriers 0.2
            materials    tubes ROUNDUP(60/2)=30 · boxes 2+18 · grout π(0.04)²×132×1000 = 663.5 L

rate        material days × daily cost × markup ÷ material metres
            soil 3.1108 × 1.33 × 12,986.60 ÷ 60 = 895.51/m ✓    rock ÷ 72 = 1,892.55/m ✓
```

All ten of its BOQ rates match to the cent, every class subtotal matches, and the totals match
(263,457.13 cost / 350,397.98 selling).

**Two day-counts, deliberately different.** `rock_days_actual` is what the rig really spends;
`rock_days_charged` is `total_days − soil_days`, and it is what the *rate* divides by — because the
last day is paid for whole whether or not the hole finished at 3pm. Charging that rounding to rock is
the workbook's convention and is reproduced rather than tidied.

### What changes for a real tender: groups

The workbook prices *one* situation. Bill 2 wants one rate over 91 holes that are not alike. So the
model runs **once per hole group** and the bill rate is the blend — `Σ(cost) ÷ Σ(metres)`. A single
group is the degenerate case and must equal the workbook, which is exactly what the regression asserts.

The access class is the estimator's, never the app's: the client bills **80 Class A and 11 Class B**
and **names no holes**. `GroupPlan.reconcile()` is his only external check. And PS 7.01B's **Class C —
helicopter access — has no bill item at all**, so a station classed C has nowhere to be priced.

### E8 — silence is not neutral

General Preambles ¶6: *"Items against which no rate is entered shall be deemed to be covered by the
other rates."* An unpriced cost is a promise to work for free for the life of a remeasured contract. So
a believed cost with no bill item must route to **query · load onto a named item · spread pool ·
accepted risk**, and the gate refuses the fifth option of doing nothing. An accepted risk without a
recorded reason is also refused — a risk somebody took deliberately and one nobody noticed look
identical six months later.

**After E1–E8:** **1,181 tests**. No model call anywhere in the new code; every module is deterministic
or a gate. No route change — this is the arithmetic spine, and per the plan the three modules whose
shape *is* a UI decision (`trace`, `georef`, `coverage`) wait until the screens are pinned.

**Not in this slice:** the vision stages (`triage`, `extract`, `setting`) and the screens they feed;
`georef` and `coverage`; the submission pack; write-back; re-pointing the register.
