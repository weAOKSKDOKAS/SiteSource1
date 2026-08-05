# The client_boq UI — how it was built, and what it does not do

**Built 2026-07-30 (backlog U1–U5).** This note records what the design specified, what the
backend actually had, every decision taken and why, the places the implementation departs from
the drawn frames, and what is still missing.

Design source: `workspace-tendering/design_handoff_client_boq/` — a seven-frame reference
(`client_boq_ui_reference.dc.html`) plus a 302-line README carrying every hex, size, weight and
copy string, and the reasoning behind each rule.

Code: `siteclaim/frontend/src/client_boq/` · new backend in `client_boq/router.py`,
`client_boq/ingest/pdfops.py`, `client_boq/ingest/run.py`, `client_boq/store.py`,
`client_boq/models.py`.

---

## 1. What was there, and what the design needed

The backend was finished and green (879 tests, 35 routes) and had never had a frontend. Mapping
the seven frames onto it produced a clean split: most of the work was drawing screens over data
that already existed, and one frame needed a capability nobody had built.

| Frame | Already live | Had to be built |
|---|---|---|
| 01 Documents | manifest, coverage, tier, parts, context cards, gate, split, ZIP, revisions | page images, in-part search, per-part re-interpret |
| 02/03 Register | register, verdicts, citations **with highlight rectangles**, RFI raise | page images, negotiation text, RFI withdrawal |
| 04/05 RFI | raise, batch into a letter, answer, read a batch | taking a draft question back out |
| 06 Addendum | change plan, mapping gate, revisions | a WAS/NOW diff — **not possible, see §6** |
| 07 Scope | one summary + a flat list of notes | the whole thing — **this is the freeze gate** |

Roughly three quarters of the work was frontend. The remaining quarter was not cosmetic: frame 07
turned out to be the freeze gate that T4, T5 and T6 had all pointed at and nothing implemented.

## 2. Two palettes in one app, deliberately

`siteclaim/frontend` already hosts the procurement wizard on the cool navy-and-blue **Atlas**
palette. The handoff's palette is warm paper and brass, and states every hex in it is final.

Both now live in one Vite build. Every client_boq token is `cb-` prefixed
(`--color-cb-paper`, `--font-cb-serif`) because the names genuinely collide — Atlas owns
`--color-paper` at a cool `#eef2f7` where this palette wants a warm `#FAF9F6`. `bg-cb-paper` and
`bg-paper` can now sit in one stylesheet without either being wrong.

Two things about this were easy to get wrong:

- **`@theme` must reach the root stylesheet.** A `@theme` block in a CSS file imported from a
  `.tsx` component is inert — Tailwind v4 generates no utilities for it, and the page renders
  unstyled with no error. `tokens.css` is imported from `src/index.css` for that reason, and the
  reason is written down there.
- The rest of the app is untouched: procurement's five tabs and every Atlas token still resolve.
  Verified by grepping the built CSS for both families.

`main.tsx` branches on `location.hash` — `#/tender` renders client_boq, anything else renders
Atlas. Six lines and no router dependency; the app has never needed routing and one branch does
not justify adding it.

### Type roles are not decorative

Serif carries the argument (rationale, clause text, scope prose). Sans carries the interface.
Mono carries anything a machine produced or that must be compared digit by digit. Mixing them
blurs who said what, which is the one thing this product must not do.

## 3. Authorship, and the bug in the obvious derivation

The design's rail shows five authorship swatches — rules engine, Claude, citation failed,
uncovered clause, code-no-model — and none of them is in any payload. They have to be derived.

The obvious derivation reads `status`: `rule_flagged` → navy, `candidate` → brass, and so on.
**That is wrong, and it took writing it out to see why:** a human verdict *overwrites* `status`.
The moment a line is confirmed, `status == "confirmed"` and every trace of who found it is gone.
Half the register would lose its authorship the instant someone worked through it — on the one
screen whose entire purpose is showing who said what.

The precedence that survives a verdict, in `ui.tsx` and nowhere else:

| Order | Test | Swatch | Why it survives |
|---|---|---|---|
| 1 | `status == citation_failed` | red | cannot be confirmed, so the status cannot be overwritten |
| 2 | `rule_ref` is set | navy | the rule layer is its only writer and never clears it |
| 3 | `status == uncovered` | blue | — |
| 4 | `source == cashflow` | grey | s06 is arithmetic on the payment terms; no model involved |
| 5 | otherwise | brass | s03/s04/s05 are all AI-propose |

Rule 5 is the honest default: anything not demonstrably deterministic is attributed to the model.
Over-crediting code is the dangerous direction of the two.

## 4. The document pane

Server-rendered PNGs, not a client-side PDF renderer. The reason that matters more than bundle
size: **the server measured the highlight rectangles in the same coordinate space it rasterises
the page from**, so nothing has to agree about scale across a process boundary. Rectangles arrive
as fractions of page width and height and overlay correctly at any zoom.

`GET /ingest/parts/{set}/{part}/page/{page}.png?dpi=` takes a **source-document** page number —
the same numbering as manifest ranges, citation pages and highlight rectangles. There is
deliberately one page-number convention; two on one screen is how a highlight lands on the wrong
page.

### The pixel ceiling, found by measuring

The first real run exposed something a DPI cap would not have caught. At 110 DPI:

| Part | Paper | Rendered | Weight |
|---|---|---|---|
| `02-ct` Conditions of Tender | A4 | 910 × 1287 px | **58 KB** |
| `07-drg` Tender Drawings | A3 | 1819 × 1285 px | **1,666 KB** |

The same request, 27× heavier, purely because the paper is bigger — and a tender is full of A3
drawing sheets. The cap is therefore on the **image**, not the DPI: `MAX_RENDER_WIDTH_PX = 1400`,
which still leaves better than 2× for zoom over a ~400–470 px pane. The drawings now come back at
1389 px / 1006 KB, and the A4 pages are untouched because they were never near the ceiling.

### Search has no minimum length, and that is not an oversight

`pdfops.locate` refuses fragments under 45 characters, because a citation confirmed by an
accidental match is worse than one left unconfirmed. That is a rule about **proof**.

`pdfops.search` is a separate function with no floor, because a person typing into a search box is
making no claim about the document — applying the rule there would break the feature outright.
Both facts are commented in the source, or someone will eventually "fix" one into the other.

Verified against the real CIC Conditions of Tender: `locate` and `search` return **the same page
and the same rectangle** for a real clause on binder page 12. The viewer draws a citation
highlight and a search hit through one code path because they are one code path.

### Seeing and searching are different questions

An image-only part rasterises perfectly and cannot be searched at all. The search endpoint returns
`searchable: false` with a sentence saying so, rather than an empty result set that reads as "no
matches" — reporting zero hits for a page nobody could look at trains the user to distrust the
search. Both scanned parts of the reference tender (`01-inv`, `10-gcc`) behave this way and still
render.

## 5. The freeze gate (frame 07)

The estimate's scope was one summary plus a flat list of notes: enough to brief a pricing run, not
enough to sign. Freezing needs three things a paragraph cannot carry, and each became a column:

- **where each line came from** (`source_ref`) — so nothing walks into the scope on its own;
- **whose words it is in** (`badge`) — so a model's suggestion and a person's decision never look
  alike on a page that becomes a contract;
- **whether an unanswered query became an assumption somebody accepted**
  (`is_fallback` + `accepted`).

New table `client_boq_scope_items`; new routes `GET …/scope/{set}/sources`, `POST …/scope/map`,
`POST …/scope/item`, `DELETE …/scope/item/{set}/{item}`.

**Sources are derived on every read, never stored.** The register, the open questions and the
change log are each already the authority on their own contents; a stored copy would go stale the
moment a verdict changed or an answer arrived, and the scope would be built on a snapshot nobody
took deliberately. "Already mapped" is computed as: a scope row points at that `source_ref`.

**Editing always stamps `user`.** There is no state in which a person's words are attributed to a
model, and none in which a model's words silently become a person's. `Convert to user` exists for
taking ownership of wording you agree with without changing it.

### The one deliberate departure from the drawn frame

Frame 07 shows *Approve scope & unlock pricing* live while two AI fallbacks are still unaccepted.
**The implementation disables it**, with the reason where the button is, and the backend 409s as a
backstop.

The reason is locked decision 8: an open query does not block pricing — the submission deadline
does not move because the client has not replied — and the forcing function is *freeze*, where
every unanswered query becomes an answer **or a stated priced assumption**. Approving over an
unaccepted fallback would put a machine's guess behind a price with nothing recording that a
person agreed to it, which is precisely what the same frame's own rule forbids ("a machine's
number must not be able to look priced"). It also follows the pattern the design already uses for
a citation-failed row: disable the control and state the reason, rather than catch a 409 later.

What still does **not** block: the open query itself. Verified — after freezing, the query is
still unanswered and still counted.

## 6. What this does not do

- **No WAS/NOW clause diff (frame 06).** `ChangeEntry` carries the addendum's own advisory change
  table — document, pages, description — and no old or new clause text, so there is nothing to
  diff. The panel says so in place of the diff rather than drawing an invented one. (The real
  ND/2025/04 addendum states its own change table is "neither exhaustive nor guaranteed to be
  accurate", so the replacement pages are the authority in any case.)
- **No Price or Offer screen.** Not designed. Their backend works — `/estimate/run`, the .xlsx
  workbook and the offer-letter draft are all built and tested — so the gap is a drawn screen, not
  a capability.
- **No manifest page-bound editing.** The endpoint accepts an edited parts list; the control that
  produces one is not built, so the button is disabled with a tooltip saying so.
- **No verdict clearing.** There is no endpoint that clears a recorded verdict, so `Undo` explains
  that rather than pretending. Re-running the review is the honest reset.
- **The citation highlight cannot be demonstrated in DEMO.** See below — it is the most likely
  thing to be mistaken for a bug.
- **Mobile.** Designed for ≥1280 px. Below that the rail folds, then the third pane becomes a tab.
- **Loading and empty states** are mine, not the designer's — the handoff lists them as not drawn.
  They follow the design's own logic: a step that has not run opens and states what it is waiting
  for.

### The DEMO citation limitation, in detail

Running the review over the real 411-page binder in DEMO returns **12 citations, all
`unverifiable`**, so no highlight is ever drawn. This is correct behaviour, not a fault:

The DEMO review fixture describes a fictional `subcontract_agreement.pdf` — 11 clauses with
`part_id: ""`, on pages 2–11 of a document that is not the uploaded tender. No citation maps to a
held part, so the corroboration rule in `s08_citation_verify` degrades every one to
`unverifiable` with "the parse and the file may not correspond", rather than accusing 12 real
citations of being wrong. That rule is documented in `citation_locating.md` and this is exactly
the case it was written for.

**The mechanism itself is verified working** on the same documents: `pdfops.locate` finds real
clauses in the real parts with rectangles, and the UI draws them. What cannot be shown offline is
the *fixture* pretending to be about this binder. In LIVE mode the parse comes from the real
parts, so `part_id` and quotations correspond and the highlight draws.

In the meantime, the pane's **search** works fully in DEMO — searching a readable part highlights
real hits on the real pages — so the side-by-side highlighting is visible offline, just driven by
the search box rather than by a register row.

## 6b. The revision after using it (R1–R5, 2026-07-31)

The first build was used and came back with six complaints. Investigating them found one root
cause behind two of the worst, and one defect that made LIVE mode impossible.

**The register was ambiguous, and no quotation highlighted, for the same reason: in DEMO the
register is about a different document.** Measured against the real binder, *none* of the
register's quoted text exists anywhere in it — the parse fixture describes a fictional
"Harbour Crest Residences" subcontract. So every row cited a clause that was not on screen. No
layout work could have fixed that. It now shows as a banner (`_parse_mismatch`, a deterministic
filename comparison that must never fire in LIVE), and `running_live.md` says how to review a real
tender.

Separately, rows showed `PS-01` and nothing else. The position a finding is measured against lives
in `review_criteria.md` and was never exposed; `GET /criteria` now serves it and each row reads
**WE ACCEPT / IT SAYS / RED FLAG**. On the real tender 9 of 17 rows resolve.

**LIVE could not have worked at all.** `pollJob` existed and no tab called it: in DEMO every job
endpoint returns `done` inline, in LIVE it returns `queued` and the work happens on a thread. The
UI read `.result` off the first response — perfect offline, silently inert with a real key. All
job starts now go through `runJob()`, which polls in LIVE and passes through in DEMO, and a
progress strip finally uses the `done`/`total` fields the Job model has always carried.

The rest were straightforward: the page pane now scrolls continuously with lazily-mounted pages
(a 105-page drawings part must not fetch 105 PNGs), zoom is a number you type (default 150%, base
460px), the divider derives its limits from the container instead of a hard-coded 760px and
collapses the pane to a tab, the rail resizes, and context cards are editable — stamped `user` on
save, `ai` again on re-interpret, with `readable` deliberately not editable because it is a
measurement.

Strategy-flag quotes gained a **show me** control reusing the citation verdicts. It immediately
earned its keep: the DEMO fixture broadcasts the same three flags onto all ten readable parts, and
locating them proves only `02-ct` contains them — on binder page 12, where the flag claims printed
page 8. That gap between the printed label and the measured page is the whole argument for
measuring.

**One real accident, recorded because it cost something.** A throwaway probe script called
`store.get_conn()` without `DEMO_MODE`, and `client_boq`'s lazy `CREATE TABLE IF NOT EXISTS`
added 13 empty tables to the committed procurement database. No rows were touched (1,664 rows
across 21 tables, verified identical before and after), but the file stopped being byte-identical
to the one that shipped, and the working copy had no `.git` to restore from. Repaired by hand first
— dropping the empty tables and vacuuming, which recovers the data but not the bytes — and fully
undone later with `git checkout --` on that one path, once the copy was wired to the remote. The
file is byte-identical again and the suite is green against it. Written up as `CLAUDE.md` trap 3b,
where the lesson is now two-part: set `DEMO_MODE=true` first, and keep the work under version
control so a mistake like this costs one command.

## 7. Craft notes

The handoff asks for 120–160 ms on colour and 200 ms on expansions. What makes that read as
deliberate rather than merely fast:

- Custom curves, not the CSS built-ins: `--cb-ease-out: cubic-bezier(0.23, 1, 0.32, 1)`. Never
  `ease-in` on UI, never `transition: all`.
- Every pressable scales to `0.97` on `:active` at 160 ms — instant physical feedback.
- Expansions animate `grid-template-rows: 0fr → 1fr`, so content below slides instead of jumping
  and no height has to be measured first.
- **Register row selection does not animate.** A reviewer clicks through seventeen rows; at that
  frequency motion reads as lag. Colour only.
- **Nothing staggers.** This is a dense desk tool — crisp and quiet, not playful.
- Hover is gated behind `@media (hover: hover) and (pointer: fine)`; a touch device fires hover on
  tap, which reads as a stuck state.
- `prefers-reduced-motion` keeps colour and opacity and drops movement — gentler, not none.

## 8. Verified against the real tender

Everything below is the actual 411-page `(325) Tender Document.pdf`, not a synthetic fixture.

**Ingest and the Documents tab.** 12 parts, 411/411 pages, no gaps, no overlaps, tier 1. Page
render exercised on the first and last page of all 12 parts. A page outside a part 404s rather
than silently rendering the wrong one. Both image-only parts render and honestly refuse search. 30
strategy flags found, including the CIC 4.26 qualification-disqualification clause.

**The Register.** The design's own numbers, reproduced exactly — which strongly suggests the
frames were drawn from this fixture:

| | Design | Measured |
|---|---|---|
| needing a verdict | 17 | 17 |
| with no clause, quote or position | 5 of 17 | 5 of 17 |
| unresolved criteria | 18 | 18 |
| aligned / passed | 2 | 2 |
| cash-flow periods | 9 | 9 |
| checks: criteria / scope / programme / cash flow | 9 / 5 / 2 / 1 | 9 / 5 / 2 / 1 |

Authorship across the 17: 7 rule, 7 model, 1 failed, 1 uncovered, 1 code. Confirming the
citation-failed line returns 409, which is why the control is disabled. Negotiation text stored;
the question queued as an RFI; withdrawing it kept the draft text on the register line.

**The freeze gate.** An open query maps as an unaccepted fallback; approving returns 409 naming
it; `/estimate/run` stays shut; accepting it stamps `user` and opens the gate; the query is still
open afterwards, because the query never blocked — the unowned guess did.

**Suite.** 916 passed, 5 skipped (from 879/5). `tsc --noEmit && vite build` clean. Committed
`sitesource.db` byte-identical throughout.


## 9. The tender desk (Series D, 2026-07-31)

The app used to open into one tender chosen by a `<select>`. The extended handoff (`client
register screen wireframe home page/`, Frame 00 + the nav sidebar) turned the entry point into a
**desk**: a shelf of folders, one per live tender, worked by a small team. Three user requests
rode along that the handoff itself lists as undesigned or does not contain: editing the criteria,
editing the costing data, and choosing the AI model.

**The hash is the router.** `#/tender` is the desk, `#/tender/s/{set}/{tab}` one tender,
`#/tender/criteria|rates|team|settings` the management screens. The browser's own history powers
the app bar's ← / → (an index stamped into `history.state` lets → honestly dim), and a reload
lands where you were. Still no router dependency.

**The close date is a finding, not a form field.** The interpreter already quotes the
submission-deadline clause verbatim with clause + page (`RULE_SUBMISSION_DEADLINE`); a
deliberately conservative parser (`ingest/close_date.py`) turns the quote into ISO — `14 August
2026` parses, `04/05/2026` refuses, two dates refuse. A refusal is not an error: the card shows
`DATE NOT FOUND — CONFIRM IT` and a person types what the clause says, stamped with their name.
The card's provenance line is the rule made visible: `READ FROM COT cl.4 · p.14` (clickable — it
opens that page), `CONFIRMED BY HAND`, or `READING THE DATE…`. **DEMO always lands on
not_found**: the interpret fixtures describe the sample tender, and a fixture date labelled as
read from this upload would be trap 9 all over again.

**`blocked` is computed where the gates live.** The shelf's Blocked filter and the card's
blocking sentence derive from counts `list_sets` computes server-side — undecided verdicts,
failed citations, unaccepted fallbacks, open RFIs past the query cut-off — because the one thing
that filter must never do is disagree with what the 409s refuse. The sentence itself is composed
client-side from the counts; the word "in progress" appears nowhere.

**Named profiles, no passwords.** There is no auth in this app, and a password box would be
security theatre. What the team table honestly provides is attribution: the uploader owns the
tender, `X-CBOQ-Actor` rides every mutating request, verdicts gain `decided_by` (additive on
`DepartureItem`, backward-compatible with stored registers), and "CONFIRMED BY R. LAM" finally
has a name behind it. Members archive rather than delete — their name is stamped on history.

**Criteria moved to the DB; the markdown is the seed.** Editing needs disable-without-delete (a
past register may reference the id forever), authorship, and write-safety; round-tripping a
hand-maintained markdown file has none of those. `criteria_store.load()` returns the identical
`CriteriaLibrary`, so the review stage switched in one line and `GET /criteria` kept its shape.
Threshold rules ride along **read-only**: their `extract_field` is wired into `rules.py`, and
rule text a person can edit but code does not obey would be a lie on the screen.

**The rate book is the DB source `rates.py` promised.** Its header comment has said since v1
that a future DB source "only has to return the same list from a different reader — nothing
downstream reads the CSV directly". `rates_store` is that reader; the CSV seeds first-wins
(mirroring `rate_index`), and nothing downstream changed. Rates archive rather than delete: an
archived rate referenced by an old estimate resolves `missing_rate` on a re-run — honestly
absent and flagged, never a stale price.

**One model setting, applied at construction.** `client_boq/llm.py::make_client()` reads the
settings row per stage run and passes `provider=`/`model=` explicitly; the 12 stage call sites
switched from bare `LLMClient()`. The chassis needed one additive change — `_route` honours an
explicitly constructed provider for text calls — because env routing would otherwise override
the setting whenever `DEEPSEEK_API_KEY` exists. Procurement constructs bare clients and routes
exactly as before (proven in `pipeline/tests`). Two residual truths the screen states: page
images always go to Anthropic vision (DeepSeek rejects them), and DEMO calls no model at all.

**Numbers.** 59 routes (from 46), 994 tests (from 931; 63 new across
`test_team_and_meta` / `test_close_date` / `test_criteria_store` / `test_rates_store` /
`test_settings_llm`), 6 new tables, `tsc && vite build` clean, committed DB byte-identical.
The desk walk (`walk_desk.py`) exercised every capability against the DEMO backend end to end.


## 10. The layout, the missing PDF, and joining the two products (Series L, 2026-07-31)

Five complaints. Two of them shared a cause that no amount of staring at CSS would have found, and
one "limit" turned out never to have been enforced at all.

**The app slid sideways off the screen.** `PageView` brought a page into view with
`el.scrollIntoView({behavior, block})`. That call omits `inline`, which defaults to `"nearest"`,
and `scrollIntoView` scrolls **every scrollable ancestor** — including the app root, which is
`overflow-hidden` and therefore has no scrollbar to scroll back with. Opening the Documents tab
seeds a page, the scroll fires, and the whole bar and left rail leave the screen for good. Fixed by
scrolling the pane's own scroller by hand:
`root.scrollTo({ top: el.getBoundingClientRect().top - root.getBoundingClientRect().top + root.scrollTop })`,
plus `min-w-0` and `overflow-hidden` on the three-pane rows so nothing else can try it either.

**The PDF pane's floor did not exist.** `DOC_MIN = 160` lived only inside the divider's arithmetic;
the pane itself was `flex-1 min-w-0`, whose true floor is 0px. A middle-column width persisted on a
wide monitor was re-applied verbatim on a narrow window — `clampMiddle` was called from exactly one
place, inside `dragMiddle`, so nothing ever re-measured — and the pane was squeezed to nothing while
still mounted and still fetching page images. `DOC_MIN` is now **480** (a 460px page at 100% fits
with no sideways scrolling) and it is applied as a real CSS `min-width`.

**The panes ran off the right-hand edge.** With that floor the row's own minimum is
`244 + 14 + 320 + 480 = 1058`, plus the 206px sidebar — a **1264px viewport**. Below that something
has to give, and the handoff said what ("below 1280 the rail folds, then the third pane becomes a
tab") but nothing implemented it. `fitPanes` now runs on mount and on every resize and gives up
capacity in that order, stopping at the first step that fits. Automatic folds undo themselves when
the window grows; a fold the user performed by hand does not.

Three smaller defects in the same arithmetic, all real: only the 9px divider was counted (never the
5px one beside the rail); the full rail width was reserved even while the 44px folded strip was on
screen; and the collapse test ignored drag direction, so dragging LEFT to **enlarge** the PDF could
collapse it.

**"Why can't I see the PDF" had a second cause on the Register.** `partId` started `null` and was
only ever set by a citation that LOCATED — which in DEMO never happens, because the register
describes a different document. The clause viewer therefore sat on "Select a part to read it here"
forever. It now opens on the first part, exactly as Documents does.

**Highlighting in the Register.** Three fixes. Selecting a row now moves the pane to the clause's
part even when the citation is unverifiable — the document is on screen to read and the banner says
why nothing is marked, which is different from an empty pane that explains nothing. A selected row
with a quotation gains **"Show me on the page"**, the same `locate` control Documents has, with the
same three verdicts. And a search no longer *replaces* the citation's marks: typing in the search
box used to hide the very quotation being checked.

There was also a first-click bug worth recording. The `[partId]` effect cleared the page-element map
on the way IN, wiping refs the new part had already registered in the same commit, so the first
scroll-to-page after a part change silently did nothing — the first citation click landed on page 1.
Clearing in the effect's cleanup (i.e. against the part being left) fixes it.

**Two products, one click.** `main.tsx` has always branched on the hash and nothing ever wrote it.
The SiteSource logo is now a menu (Procurement · Review tender, current one ticked), the desk's
sidebar has a Procurement button under "+ New tender" and on its collapsed rail, and because both
navigations are hash assignments they push history — so the browser's Back moves between the
products in both directions. The desk's own ← needed one fix: arriving from procurement mounts the
app fresh at history index 0, so it now falls back to `window.history.length > 1`.

**Verified by screenshot**, not by assertion, against a clean DEMO backend at 1152 / 1280 / 1366:
nothing past either edge, the rail auto-folding at 1152, and the real CIC Invitation Letter
rendering in the pane on both tabs.

> A note for whoever hits this next: a long-running dev backend was returning **500 on every page
> render** while every other route worked, including routes added the same day. The same code in a
> freshly started process rendered every page fine. If the pane says a page could not be rendered,
> restart the backend before debugging the frontend.

## 11. Price and Offer (Series P, 2026-08-01)

The two steps the handoff never drew, and the last open item in the backlog. Their backend had
worked from the beginning — `/estimate/run`, the .xlsx workbook, the offer-letter draft — so this
was only ever a missing screen. Designed here from the handoff's own rules.

### Price — the trace is the point

`CostLine` carries a full, hand-recomputable trace: quantity, the productivity conversion when
there is one, the rate, **where the rate came from**, and the amount. That is not incidental — it
is why the estimate is deterministic code rather than a model call, and the screen would be
dishonest if it showed only totals. So every activity opens to its resource lines, and each line
shows `BOOK` / `INLINE` / `MISSING` beside the rate.

**A missing rate prices at zero.** The backend refuses to guess one, which is only safe if the hole
is impossible to miss, so `MISSING` is red on the line, red on the activity, counted in the rail,
and filterable. The indirects show the arithmetic the backend wrote for exactly this purpose —
`8000.0 per week × 20.0 weeks = 160000.0` — so a reader can check a number without leaving the
page.

**The margin is a readout, not a verdict.** `margin_amount` is price less cost and the backend
deliberately declines to call it healthy or thin. The screen says so in as many words rather than
adding a judgement the product has spent its whole design avoiding.

The five rule flags each carry their *consequence*, not just their name: what the flag means for
the number standing beside it. A flag never blocks a price — it marks what to look at before
signing one.

### Offer — authorship, line by line

Appendix A is the one place two authorships sit side by side, so it is where the distinction is
drawn hardest: **from the register** (a confirmed departure, carried verbatim — navy) above
**drafted from the scope** (an AI proposal — brass), each labelled and counted. On the real fixture
that is 4 confirmed against 3 drafted. On a page that becomes a contract, a decision a person took
and a sentence a model wrote must never look alike.

Sections carry the same distinction: `INJECTED FROM THE ESTIMATE` on the pricing schedule and the
price, `AI DRAFTED` on the prose. The price is never written by a model; the prose is never a
number.

The two companion documents open as **internal working papers**, with the reason stated on screen
rather than assumed — both reference tenders warn that qualifying a bid "may cause the tender to be
disqualified", so the submission versions are opt-in. And nothing sends the letter: this product
has no transmit path at all, which is more honest said plainly than implied by a disabled button.

### The bug the new tabs exposed

`usePanes` held its container in a plain `useRef`. Price returns a "Reading the estimate…" panel
while it loads, so on the first render the container did not exist, the refit effect ran against
`null` and bailed — and then never re-ran, because nothing in its dependency list changed when the
div finally mounted. The layout was therefore **never measured at all** on exactly the tabs that
load something first, which is the right-hand overflow §10 exists to prevent. The container is now
a callback ref held in state, so the effect re-runs the moment the node attaches. Worth remembering:
a `useRef` in an effect's dependency list is a lie — it never changes, so the effect never re-runs.

## 12. The schedule, and what the first live run found (Series S, 2026-08-01)

### The door that was never built

Checked step by step against what the UI sends, three of the five were ready for a real API key.
The fourth could never have worked: `/estimate/run` requires `margin_pct` **and** a structured
`schedule` in LIVE, DEMO filled both from a fixture, and there was nowhere in the app to type a
bill of quantities. `CONTEXT.md` had said from the start that quantities are *given* — "no take-off
in this slice" — so the schedule was always meant to arrive from outside. Nobody built the door.

`client_boq_schedules` stores it per tender (retyping a bill for every re-run is not a workflow, and
a corrected quantity or an edited rate is exactly what causes a re-run). `/estimate/run` is
untouched: the frontend sends what it persisted, so the contract that was already tested still is.

### The editor does not price as you type, deliberately

The obvious build shows a running total. That means re-implementing the cost build-up in
TypeScript — productivity conversion, inline-over-book precedence, missing-rate-to-zero, rounding —
and a pricing screen whose total disagrees with the server's is worse than one showing no total at
all. So the editor shows **inputs and the book's rate**, both facts a person can check, and the
arithmetic happens once, on the server, where it is tested. A `resource_ref` that names nothing in
the rate book is marked `NOT IN BOOK` while you type, because that line will price at zero and be
flagged, and finding that out before the run is the whole point of showing the rate.

### The letterhead comes from what is already stored

Company name, address, contact and phone are app-wide (`letter.*` settings) — the same on every
tender. The client and the project come from that tender's own desk card, and the date is stamped
at run time. Nothing is typed twice, and the Offer tab says when the letterhead is still the
built-in placeholder rather than quietly sending a letter as "SiteSource Contracting Ltd".

### The first live run, and the bug it exposed

The provider probe passed both ways in seconds. The workflow then failed on its first real call:

```
purpose=client_boq-ingest-plan-split        ms=76835  in=901  out=8000
purpose=client_boq-ingest-plan-split-retry  ms=79251  in=935  out=8000
-> 1 validation error for PlannedSplit: Invalid JSON: EOF while parsing at line 1 column 0
```

Exactly 8,000 output tokens — the ceiling — twice, and an empty string both times. Measured
directly against the API: **`deepseek-v4-flash` is a reasoning model.** At `max_tokens=600` it
produced 2,175 characters of `reasoning_content`, `content=''`, `finish_reason='length'`; the same
prompt at 8,000 used 3,240 tokens and answered correctly.

So `DEFAULT_MAX_TOKENS` had quietly changed meaning. It was written when a completion budget was a
budget for the **answer**; on a reasoning model it must also cover the thinking, which is billed as
completion tokens and never appears in `content`. A hard prompt spends the whole allowance
thinking, and the caller receives `''` — which surfaces as "Invalid JSON: EOF while parsing", a
completely true statement about a string that was never the problem. Worse, `complete_json`'s
corrective retry re-sends the same budget, so it fails identically and costs a second call.

Two fixes, both in `pipeline/llm_client.py` (the shared chassis — the second documented change to
it, and like the first it is procurement-neutral):

- `DEEPSEEK_MIN_MAX_TOKENS` (default 32,000, env-overridable) as a floor on the DeepSeek path.
  Reasoning headroom, not generosity: it makes a documented budget mean the same thing on both
  providers. It never lowers a caller's explicit ask. The review's first chunk then used **19,801**
  output tokens — it could not have completed under the old ceiling.
- `CompletionTruncated`, raised when content is empty and `finish_reason == 'length'`. A
  configuration fault must not be mistaken for an answer, and must not be retried as if it were bad
  formatting — the same rule as `OcrEngineUnavailable` (trap 1b), for the same reason.

### The split the model proposed, and why the gate exists

With the ceiling fixed the run completed end to end. The planner's split was still wrong: two parts
**both covering page 1** of a 12-page document. Everything downstream then read the title page —
identical summaries on both parts, no strategy flags, empty register lines, no citations.

The deterministic layer had measured all of it:

```
coverage : 2 of 12 pages
overlaps : p.1 claimed by parts [1, 2]
tier     : 4 — "no bookmarks, contents page, or divider pages found"
```

This is the design working, not failing. A measurement outranked a model proposal, the manifest
gate is a **human** gate, and the Documents tab shows that coverage bar precisely so a person does
not approve a split covering one page in twelve. The probe script approved it blindly, which no
operator would. Re-running with an edited manifest — the designed path, `POST /ingest/manifest/approve`
with a corrected parts list — put the whole document in front of the review.

Tier 4 is also honest about the input: a 12-page slice cut out of a binder has no bookmarks,
contents page or dividers, so the planner had nothing structural to work from. The full binder
reaches tier 1.

## 13. Reading the live register: the false alarms, and the highlighter (2026-08-02)

### Ten citations "failed" with nothing wrong with them

The live review reported 10 of 75 lines as citing a clause "not in the document set". None of them
was wrong. Three separate causes, all in how a reference was *written* rather than whether the
clause exists:

| Cause | Example | Why it missed |
|---|---|---|
| a document-name prefix | `CIC Conditions of Tender, Clause 4.13` | the index is keyed `4.13` |
| several clauses in one string | `8.1; 2.3; 10.1` | a finding about a CONFLICT cites them all |
| a sub-clause limb | `4.4(b)`, `1.2(d)` | s01 indexes at the numbered level: `4.4`, `1.2` |

The proof it was formatting and not a missing clause: **the same clause 4.13 resolved from the
criteria stage's `'4.13'` and failed from the programme stage's prose form, in one register.**

`clause_candidates()` now expands a reference into every id it might mean, most specific first, and
`resolve_clauses()` returns all of them that the index holds. Deterministic — no model, no
guessing at meaning, only at *format*.

### The half that actually catches a lie, and why it had to change too

Fixing the lookup alone moved nothing: all ten then failed the containment check instead. A finding
about a conflict quotes a fragment from each clause it cites, joined by an ellipsis:

```
clause : 1.2(d); 2.1; 4.3
quote  : "The tender documents consist of: … d) Assignment Brief and its Annexes;
          … Tenderers are invited … to submit proposal and bid for Design…"
```

Asking whether all of that sits inside any ONE clause has no possible right answer — the fragments
came from three. So the check now splits the quotation on the ellipsis and requires **each fragment
to appear in the combined text of the clauses that line actually cites**.

This is not a loosening. An invented fragment is in none of the cited clauses and still fails —
which is the thing the guard exists to catch. It only stops failing honest quotations for a reason
unrelated to whether they are true. `citation_failed` on the live register fell **10 → 3**, and the
three that remain name the exact fragment that is missing.

One bug found in the fix itself, worth keeping: the first ellipsis pattern allowed whitespace
between the dots, so `"cost incurred. … There shall be"` split into `"cost incurred"` and
`". There shall be"` — the stray leading period then failed containment. It accounted for 2 of the
4 lines still failing at that point. The dots must be contiguous.

### A highlighter, not a box

The mark was a 70%-opaque fill with a hard 2px brass ring. Over a dense clause that washes the text
out to pale grey and chops the sentence into boxes, one per word rectangle.

`.cb-mark` uses `mix-blend-mode: multiply`. That is the whole trick, not merely a lower alpha:
multiplying the fill into the page leaves every glyph fully black underneath, so the mark can be
lighter **and** more legible at the same time — which is what makes the border unnecessary rather
than merely absent. Verified side by side against the real page at 200 dpi.

The arrival pulse had to change with it: `cbFlash` animated a 2px ring, which would have put the
border straight back on every citation click. It now pulses the fill (`cbMarkFlash`, 0.85 → 0.42).

**Dismissal** is local to `PageView`: Escape on the scroll container, or a `Clear` chip that appears
in the toolbar only while there is something to clear. It resets whenever a new citation or search
arrives, because a mark that stayed hidden would read as "nothing was found".

That reset is keyed **by value, not by array identity** — the Register tab builds its highlights
inline (`[...(citation?.highlights ?? []), ...located]`), so the array is a fresh object every
render and an identity-based dependency would have fired continuously, making Clear appear to do
nothing on the one tab where citations matter most.
