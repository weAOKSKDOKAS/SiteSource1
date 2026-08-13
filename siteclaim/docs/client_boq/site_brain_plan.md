# The Site brain — plan of record

*Written 2026-08-12, after a five-surface inventory sweep (wireframe handoff, chat, maps,
operator journey, costing seams) and three decisions taken by the product owner. This is the
document to read before building any of it, and the record of why each piece has the shape it
has.*

---

## 1. The three decisions, taken and recorded

Asked explicitly, answered explicitly, and every phase below is designed to them:

1. **Chat reaches costing by propose-and-confirm.** Every Site discussion is persisted and
   surfaced at pricing time. When a discussion concludes something that changes money, the AI
   drafts it as a **proposed condition citing the discussion**; a person confirms it; the
   deterministic engine prices it. The AI never writes the number. This is the same
   propose-and-confirm channel every other surface already uses — the discussion becomes one more
   *source* of proposals, never a second pricing path.
2. **The brain is propose-only.** It reads everything, dispatches read/analyse/draft tasks to
   subagents, and queues **proposed next actions with reasoning** — and every approval, verdict
   and number stays a human click. It is structurally unable to open its own gates, exactly as
   `DepartureProposal` has no status field.
3. **Tender-side first.** v1 of the brain understands the client_boq side — legals/register,
   scope, site + mapping, BQ/costing, conditions — and READS route/sourcing state without driving
   procurement. The §4 boundary stays intact.

A fourth decision taken here rather than asked, because the codebase already answers it: **DEMO
stays fully offline.** The chat replays a canned transcript fixture; the brain's subagent calls
each carry a `demo_fixture`; anything whose call shape cannot be fixture-replayed is absent in
DEMO with an honest notice, never silently live.

## 2. What the sweep found (the short version)

The full findings are in the workflow transcript; what matters for the plan:

- **The design handoff is mostly built.** The six-step flow, the gates, the authorship triad, the
  Site screens, the sweep — all exist. The deltas that matter: the **§10 Derivation tree**
  ("the component that matters most in the whole app") is not built; **MapCrop runs on
  placeholder geometry** because sheet registrations are never persisted ("two typed coordinates
  turn it on" — `boq/georef.py`); and the design specifies **no chat surface** — the chat is the
  owner's addition on top of it.
- **Two silent money leaks clear the app's only hard stop:**
  - a cost routed **load onto 2.2b** satisfies the settle gate and is *never applied* —
    `sweep.loadings()` is computed and displayed by two endpoints and `price_bill` has no
    loadings parameter (same defect class as the spread pool closed in `edcb311`);
  - a **platform cost typed on a group** (`Site.tsx` "platform build", `HoleGroup
    .access_build_cost`) reaches no total — `groups.access_build_total()` has zero production
    callers, while its own docstring cites SMM S02 ¶2.08(h) putting it in the rig-move item's
    coverage.
- **The chat exists but forgets.** `/costing/ask` is grounded, citation-checked, and can propose
  a condition — but exchanges are not persisted, a confirmed condition does not cite the exchange
  that spawned it, and a later question cannot see earlier discussions or recorded conditions.
- **The map exists but is dark.** Access board, HK1980→WGS84, per-point links and the slippy map
  are built; the georef math is written and tested and waits on a table and a two-marks form.
  Vision photo observations are read and then discarded.
- **Journey dead ends** (curl-only or button-less): RFI letter export/answers, register re-run,
  unreadable-part upload, moving a hole between groups.

## 3. The phases

Ordered by blast radius, each one shippable alone. Phases 1–3 are pure closures of existing
intent; 4–5 are the owner's new surfaces.

### Phase 1 — stop the two leaks *(built with this document)*

1. `price_bill` gains `loadings=` and applies routed-LOAD costs to their target item's cost —
   the money an estimator explicitly routed reaching the rate it was routed to. A loading whose
   target is missing or client-priced is a **flag**, never a silent drop (GCT App C 2.2(vi)
   reinstates a client rate, so money loaded there is thrown away at examination).
2. A **guard** for the platform cost: typed on groups, consumed by nothing → a named flag with
   the amount and the clause, on the checks surface. The full wiring (a per-class rig-move basis
   so 2.2a/2.2b price their own moves and the platform lands in the Class B basis) is **Phase 3**
   work — it redesigns the basis table and must not be a side effect of a leak fix.

### Phase 2 — the site log: discussions that feed costing *(built with this document)*

The owner's chat ask, under decision 1. The pieces that already exist stay untouched — grounded
`RawAnswer` with no numeric field, citation stripping, the sole-writer condition confirm. What is
added:

- `client_boq_site_log` — every ask exchange persisted: question, answer, citations, figures
  used, stripped receipts, actor, timestamp. **The log is memory, not authority**: nothing prices
  from it, and it never appears in a build-up.
- **Provenance on the bridge**: a condition proposed from a discussion carries the log entry's id,
  so a confirmed condition can answer "why do we believe this?" with the conversation that
  decided it.
- **The ground includes the past**: `_ground_for` gains the recorded conditions and recent log
  entries, so a later discussion sees what was already discussed and decided — the "AI
  understands what is happening on site" loop.
- The Ask surface shows the persisted history per tender, and shows when a condition was born
  from an exchange.

### Phase 3 — the map earns its keep *(built with this document; decisions recorded below)*

- Persist `SheetRegistration` (one table), the two-grid-marks entry form, and MapCrop goes live
  on all 91 holes — the georef math is already written and tested.
- The per-class rig-move basis: 2.2a and 2.2b price their own move counts; group platform costs
  land in the Class B basis (SMM S02 ¶2.08(h), ¶2.03). The Phase 1 guard then goes quiet by
  construction.
- Route/access evidence: the road-access picker on the map; distances measured deterministically;
  the model contributes at most the design's brass **hint** line ("▪road 40 m — a hint, not a
  classification"), never a class. `proposed_class` stays empty by construction.

**Decisions taken in the build (3a/3b):**

1. **Sheet membership is computed by coordinates, never by name.** `Station.sheet` holds the
   SCHEDULE sheet the row was read from (GI/210); registrations are of the SITE-PLAN sheets
   (GI/201…). The two name families never intersect, so `access.board()` takes
   `located_stations` (computed via `georef.sheet_for`) and the old `located_sheets` name
   intersection is kept only for a caller that genuinely registered a schedule sheet.
2. **The class bases are DERIVED, not stored** (`model.class_variants`): present in
   `basis_index` so an item can be pointed at one, absent from `basis_rows` so nothing changes
   until one is claimed. This makes the feature available to every model ever saved, keeps the
   pinned default proposal byte-identical, and makes pointing 2.2a/2.2b at the variants (one
   click on the Costing screen) the entire activation act.
3. **The split is a partition and evaluates BOTH classes.** Claiming one variant still emits the
   other — the class nobody claimed holds real work-days and must flag on conservation as
   unclaimed rather than vanish. Class counts are the BILL's (80/11), because the divisor must
   equal the claiming item's quantity for conservation to balance.
4. **The platform joins only the Class B row, and only while the split is active.** Folding it
   into the pooled row would price Class A moves as if they needed platforms. A platform typed
   on an effective-Class-A group is never absorbed and stays flagged.
5. **The Phase-1 guard nets per-surface consumption, not a stored boolean:** the Class-B
   platform total when the split is active, plus any sweep cost routed LOAD onto a rig-move ref
   (the guard's own suggested interim route). Quiet means the remainder is genuinely 0.00.

### Phase 4 — the brain (propose-only, tender-side) *(built with this document; decisions below)*

Two layers, built in order:

1. **The whole-tender ground** — a deterministic assembly of everything the tender knows:
   register verdicts, part contexts, scope of record, site schedule + classes + groups,
   recorded conditions + site log, bill + rates + sweep state, gate states, RFIs. Pure reads,
   one module, no model. This pays for itself immediately (the chat's ground today is four
   truncated sources) and is the substrate every subagent reads.
2. **The orchestrator** — one strong model (the drawing-read stage pattern generalises: a
   `STAGE_BRAIN` with its own provider/model setting) that reads the ground, dispatches
   subagent reads (legals → register clauses; scope; site; BQ), and returns a **briefing**:
   what it understands, what disagrees with what, and a queue of **proposed actions** — each
   executable only through an existing gated endpoint by a person. It cannot call an approve
   endpoint: the action queue stores *references to* endpoints, and the UI renders them as
   buttons a human clicks. In DEMO it replays fixtures per subagent call.

**Decisions taken in the build (4):**

1. **The ground lives in `client_boq/ground.py` and the engine block is injected.** `_costing`
   stays the router's single whole-engine path; the ground module takes its output as a
   parameter rather than importing the router. The chat's `_ground_for` now delegates, so the
   chat and the brain read the SAME assembly — a fact one can see is never invisible to the
   other. Labels are typed by kind (`gate:`, `part:`, `scope:`, `rfi:`, `discussion:`…).
2. **Structural state rides along, never alone.** Gate states and the no-bill absence line are
   true of a tender nobody has touched, so they join the ground only once real content exists —
   otherwise the no-ground refusal would be defeated by its own scaffolding.
3. **Propose-only is enforced by shape, not prompt.** `RawBriefing` has no field for a verdict,
   a rate, a class or a gate flag; a proposed action is only an id into the fixed `ACTIONS`
   registry (screen + label), and `validate` strips unknown ids and ungrounded citations
   visibly. The Brain tab's buttons NAVIGATE; every consequential click stays on the screen
   that owns it.
4. **`STAGE_BRAIN` falls through to the app-wide default, not to ingest** — the brain reasons
   over what was read; it reads no pages. Same two-setting shape as the drawing read
   (provider + per-question model override).
5. **Briefings are append-only memory** (`client_boq_briefings`, seq like the site log), and
   the run is gated on a non-empty ground: a tender with nothing read is a 409, not a briefing
   about nothing.

### Phase 5 — the dead-ends purge + the Derivation tree *(built with this document)*

RFI export/answer surfaces, register re-run control, unreadable-part upload buttons, group
membership moves — each a verified curl-only workaround today. Then §10's Derivation tree, the
trust surface where an operator decides whether to believe a rate. The purge's filter is the
design's own governing rule: *if two good estimators would get the same answer it is clerical —
purge the friction; if they would disagree it is judgement — keep it.* Deliberate friction
(no pre-filled verdicts, the BASIS textarea, the sweep's hard stop) stays.

**Decisions taken in the build (5):**

1. **The Working screen renders ENGINE B** (`price_bill` over stored build-ups) as a third view
   inside Price — the engine the sweep's spread and routed loadings actually reach, whose whole
   surface was frontend-orphaned. The Costing view's engine is untouched; §10's open question 4
   is resolved the way the backend already pinned it: the spread is INSIDE the rate, on its own
   labelled line.
2. **The design's per-group soil-share rows are deferred, deliberately.** The group-blend engine
   has zero production callers, and a tree whose working does not reconcile with the price is
   the exact failure §10 exists to prevent (open question 3 is "a backend decision" the spec
   does not make). The tree shows the REAL derivation — the stored build-up's resource lines —
   and the group rows come when the blend engine actually prices something.
3. **Trace enrichment is display, never re-pricing:** the term children print the resource
   lines' own documented arithmetic; the divisor cites the bill's own page (in this engine the
   divisor IS the bill's quantity); the margin's owner is the model's PROVENANCE (this tender's
   model / the library model), because the app does not record which person set a model input;
   and each failing node carries its own `problem` in place so the failing line paints red.
4. **The membership move is two writes** (source loses the hole, target gains it) because the
   group's own station list is the membership authority — and the save endpoint now clears the
   secondary station link for holes that LEFT, class untouched.

## 4. What must survive every phase

The non-negotiables, restated so nobody discovers them by breaking one: no model writes a number,
a verdict, or a gate flag; the approve endpoints stay the only writers; DEMO stays offline; the
take-off stays a proposal until a person saves it; unread cells stay named, never zeroed;
absence never reads as health; and the §4 product boundary holds until the owner explicitly
relaxes it.
