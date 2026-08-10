# The walkthrough — SiteSource walked as an estimator, 2026-08-10

*The UX mega-task's §2 deliverable: before changing anything, walk the app the way its user would
and write down what happens. This walk was done for real — backend in DEMO on :8000, the Vite dev
build on :5173, a scripted browser driving the actual screens with `Belvidere.pdf` (the real 6 MB
sample tender), every screen captured as a screenshot and a text dump. Nothing below is inferred
from the code alone; where a finding was then traced INTO the code, the file and line are given.*

**The measure being scored, from the brief:** at every moment the estimator can answer —
**Q1** Where am I? · **Q2** What's my decision right now? · **Q3** Why is that greyed out, and
what unlocks it? · **Q4** What happens if I press this?

---

## 1. What was walked

1. First open of `#/tender` with nothing on the shelf; the "Who are you?" join.
2. Upload of `Belvidere.pdf`; the ingest; landing on Documents.
3. **The lost-user probes:** every tab opened *before* anything had run.
4. The pipeline in order: approve manifest → split → run review → close register → bid brief →
   draft scope → route (confirm bill → split → propose → confirm) → sourcing/price/offer/closeout
   in their after-states.
5. **The wrong-order probes:** re-running the split after routing was confirmed; confirming again.

What could **not** be walked in DEMO, honestly noted: the route **stale-packages** card cannot
fire, because the DEMO split is deterministic — re-running it yields identical packages, and the
staleness machinery (correctly) sees nothing stale. The card and the backend check exist
(`Route.tsx` renders `proposal.stale_packages` before the confirm; `bridge/decisions.py` refuses a
stale confirm); what §1 of the brief observed predates that card. Verified by code-trace instead.
Sourcing's inner steps (shortlist → dispatch → level → award) and the priced Offer were walked only
to their entry states — they need a bill workbook and dispatch plumbing DEMO does not stage.

## 2. What the walk broke — fixed before this document was written

Pressing **Run the split** on Route crashed the server request and the screen said
**"Failed to fetch."** The DEMO branch of the bridge split passed no `demo_fixture`, so the
extraction reached the model seam bare — which DEMO refuses by design — and the unhandled 500
bypassed the CORS middleware, leaving the browser with a no-noun error. The suite never saw it
because every test stubs the model seam. Fixed with a fixture + three tests (commit `6926112`).
Two lessons stay on the friction list: crashes must never surface as "Failed to fetch" (F1), and
the walk is the test the suite isn't.

## 3. The walk, screen by screen

Scores are 1–5 per question; the sentence after is the reason.

| Screen | Q1 | Q2 | Q3 | Q4 | The reason, honestly |
| --- | --- | --- | --- | --- | --- |
| Desk, first open | 5 | 4 | – | 4 | Excellent empty state: "Drop the binder anywhere on this page and the split starts…". The join modal says what attribution is for. Counts row (LIVE TENDERS 0…) reads clean. |
| Documents after ingest | 4 | 4 | 3 | 3 | The manifest card says what approval does ("Locking freezes the parts"). But `TIER 4 · NO STRUCTURE FOUND — SPLIT BY HAND` is an unexplained jargon chip, and two buttons both say "split" ("Download split ZIP" / "Split into parts") — the walker itself clicked the wrong one, exactly as a hurried person would. |
| Register, before manifest | 4 | – | 4 | – | "The register waits on the manifest — every finding cites a page…" names the why. **No way to get there from here** — the sentence knows the unlock and doesn't offer it. |
| Register, manifest approved but NOT split | 4 | 2 | 2 | 2 | Says **"The parts are split and ready"** while Documents says `PARTS · 0` (`Register.tsx:495` keys on the manifest gate alone). Pressing Run here 409s. The screen contradicts the state — the §1.3 class, live. |
| Register, after run | 4 | 4 | 3 | 3 | The rail's CHECKS/FROM breakdown is informative but mixes authorship ("rules engine", "claude") with failure states ("citation failed", "uncovered clause") in one count column. The closing action is called **"Close register & unlock scope"** while every downstream chip says **"WAITS ON THE REGISTER"** — a person hunting the word "approve" finds nothing. |
| Bid | 5 | 5 | – | 4 | The frame is right ("The decision is yours"). But every signal's provenance line is **raw internals on screen**: `client_boq_set_meta.close_date`, `client_boq_rfi_items with an open status (store.open_rfi_count)`, `client_boq/boq/coverage.py::bill_summary` — and the deadline explains itself by quoting an enum: "the close date's status is 'not_found'". |
| Scope | 4 | 4 | 3 | 4 | Straightforward run → freeze. Freeze wording states the consequence. |
| Site | 4 | – | 4 | – | "NO TAKE-OFF YET" chip; tab explains the schedule hasn't been read. Fine. |
| Route | 4 | 4 | 3 | 3 | The three-stage layout (bill → split → route) is legible; the bill picker is honest ("No part is categorised 'pricing'… Choose the priced bill yourself"). But: the footer says "the human decision (**decided-by, decided-at**) is the record of truth" — developer hyphenation on screen; one package title rendered as **"Field Installations · Photos ……… 14"** (a table-of-contents line leaked into a section title); and **Confirm routing records every untouched default** — see F7. |
| Sourcing, early | 4 | – | 5 | – | "Sourcing works from the packages routed to sublet. Propose and confirm the routing on the Route tab first" — the best blocked-state sentence in the app. Still no button to go there. |
| Sourcing, after routing | 5 | 4 | – | 4 | "3 sublet packages… ranks deterministically. [Run the shortlist]". Header count agrees with the cards on this walk. |
| Price | 3 | 3 | 2 | 3 | Two absences, two vocabularies: the strip chip says `WAITS ON THE SCOPE` / `NOT YET RUN` while the tab says "**No bill of quantities yet**… Import the client's workbook by hand" — which of the two do I do? And the mode toggle reads `COSTING` / `ESTIMATE (OLD)` — "(OLD)" is not a word to ship. |
| Offer, early | 5 | – | 5 | – | "The letter is assembled from the priced estimate… Run the estimate on the Price tab and it appears here." Names the unlock; needs the button. |
| Closeout, early | 5 | – | 5 | – | "WAITS ON SUBMISSION" + a clear explanation. |

**The app bar on every tender screen** prints `set_id · belvidere` (`App.tsx:515`) — an internal
key, labelled as such, in the chrome the user never escapes. Q1 is answered by the *name* beside
it; the chip answers a question nobody asked.

**The step strip** answers Q1 well (ten steps, chips, "OPEN · SHOWN") and Q3 badly-but-honestly:
`WAITS ON THE REGISTER` names the blocker, never the way there — the chips are not buttons to the
blocking tab, and the strip scrolls horizontally at 1440px, hiding the tail of the journey.

**After a run finishes**, the strip says "Finished. Open the tab that started it to see the
result" — it knows which tab that is and doesn't say. (The `nextUp` offer in `App.tsx::noteJob`
does name it for four job kinds when it fires; the generic sentence is the fallback that showed.)

## 4. The ranked friction list

Ranked by *how badly a real estimator gets stuck*, not by effort to fix. Each carries its §6
build step.

| # | Friction | Evidence | Fix direction | Step |
| --- | --- | --- | --- | --- |
| **F1** | **A server failure reads as "Failed to fetch"** — no noun, no next move; the person concludes the software is broken (they were right, but couldn't know why). Any unhandled 500 loses its CORS headers and every future crash will read the same. | Observed on Route; root cause fixed, surface remains | Catch-all exception handler in `api.py` returning JSON 500 *with* CORS headers and a plain sentence; frontend maps residual network errors to "The server didn't answer — the run may still be going. Reload before retrying." | 2 |
| **F2** | **Raw internals as user-facing provenance and refusals.** Bid signal sources (`client_boq_set_meta.close_date`, `store.open_rfi_count`, `coverage.py::bill_summary`), enum-quoting ("status is 'not_found'"), `set_id ·` in the app bar, "(decided-by, decided-at)", and every backend refusal that says `POST /bridge/{ref}/route/analyze` / "run /ingest/upload first" / "POST /client-boq/boq/import first" (`bridge/decisions.py:26,123,189,502,519`, `bridge/scope.py:441`, `bridge/award.py:91`, `bridge/router.py:181`, `client_boq/router.py:750,3147–3148,3343`, `client_boq/estimate/run.py:56`). | On screen throughout | Plain-language pass over every user-visible string, backend and frontend; sources say *where in the work* a number came from, not which table. | 2 |
| **F3** | **A screen contradicting the state**: Register says "The parts are split and ready" when nothing is cut; pressing the button it offers 409s. | `Register.tsx:495`; observed live | Three-way conditional: not approved / approved-but-not-cut ("Split it on Documents first — [Open Documents]") / cut. | 3 |
| **F4** | **Blocked states name the unlock and never offer it.** Every WAITS-ON chip and gate sentence ends without the action it names ("…on the Route tab first" — no way there). | Register-early, Sourcing-early, Offer-early, Price, strip chips | Every blocked state carries the unlocking navigation inline; strip chips become links to the blocking tab. | 3 |
| **F5** | **No "what now?" anywhere.** Status everywhere, next action nowhere; after a finished run the strip withholds the tab name it knows. | Whole walk | One next-action line per screen, computed from the same state as the chips, with the button attached. Never auto-advances a gate. | 4 |
| **F6** | **Two vocabularies for one thing.** "WAITS ON THE REGISTER" vs "Close register & unlock scope"; Price's chip (scope gate) vs Price's body (bill import); "register"/"review" interchangeable. | Register footer, Price | One vocabulary per object, stated once and reused; Price says which of its two absences bites first. | 2, 3 |
| **F7** | **Confirm routing records untouched defaults as the human's decision.** Toggles seed from the recommendation and one click records all of them (`chosen[key] ?? recommended_route`), with no statement of how many were never touched. The gate survives in letter, not in spirit. | `Route.tsx:189,281`; walker recorded 3 decisions touching none | The confirm states what it will record ("Record 3 routes — 3 of 3 as recommended, none changed by you") and the record keeps whether each was touched. No silent wholesale adoption of brass. | 5 |
| **F8** | **Staleness is invisible outside Route.** The route stale card exists (good, untestable in DEMO); nothing else marks predates-the-re-run data — interpreted cards after a re-split, doc-index-derived counts. | Code-trace | Generalise the stale badge pattern where re-runs invalidate display; each badge carries its own re-run action. | 5 |
| **F9** | **Number/label hygiene.** A package titled "Field Installations · Photos ……… 14" (TOC artifact in a section title); `TIER 4 · NO STRUCTURE FOUND — SPLIT BY HAND` unexplained; `ESTIMATE (OLD)`. | Route, Documents, Price | Strip TOC dot-leaders/page numbers from section titles at source; tier chip gets a plain sentence; rename the Price toggle. | 5, 6 |
| **F10** | **Consequence and reversibility unstated.** "Approve", "Close register & unlock scope", "Confirm routing", "Submit" — which of these can be undone? (Documents' "Reopen" proves the app knows how to say it.) | Whole walk | Every consequential button states reversibility before the click, in one consistent form. | 6 |
| **F11** | **Two buttons named "split" on one screen** — "Download split ZIP" above "Split into parts"; the walker clicked the wrong one, as would anyone scanning. | Documents | The download is an export affordance, not a headline button — demote and rename ("Download parts as ZIP"). | 6 |
| **F12** | **Authors and failure states in one count list** ("rules engine 5 · citation failed 1 · claude 2 · uncovered clause 1"). | Register rail | Authorship (navy/brass) and failed-checks (red) are different axes — separate them visually. | 6 |

Environment notes, not product defects: the profile chip reset mid-walk when the backend was
restarted (scratch-DB team lost, localStorage id kept); the full test suite fails 6 tests if run
while a dev server shares the scratch DB — stop the server first.

## 5. What must not be lost while fixing this

The walk also found things that are *right* and load-bearing: the desk's teaching empty state; the
join modal's honesty ("Not a login — a name"); gates that state their consequence before the click
("Locking freezes the parts", "Closing injects the N confirmed positions…"); the bill picker that
refuses to guess; the DEMO banner; the step strip's refusal to padlock tabs (open-and-explain
beats disabled-and-mute). The fixes above must extend this voice, not replace it.
