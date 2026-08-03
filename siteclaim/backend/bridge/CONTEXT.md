# Bridge — the join (client_boq review → routing fork → the right engine)

Belongs to neither product. `client_boq` ingests a binder, reviews it, and produces a departure
register a human approves. The procurement pipeline splits a bill by trade, routes each package
self-perform or sublet, and sources subcontractors. This package is the spine that carries ONE
tender from the approved review, through a human bill-part confirmation and a scope split, into
the routing decision — without either side learning about the other.

## Inputs
- A `client_boq` `set_id` whose review register is **approved** (`store.review_is_approved`).
- That set's parts — `store.load_parts(conn, set_id)` → `[(PartSpec, pdf_path, PartContext)]` at
  the latest revision. `pdf_path` may be `""` and is filtered.
- A human confirmation of which part(s) are the priced bill.

## Process
1. **identity** — `set_id` *is* `run_ref`. Both sides derive it from `pipeline.workspace.tender_slug`
   over the project name, so no translation layer exists or may be added. The `unified_projects`
   umbrella is registered on this side; nothing is written to any `client_boq_*` table.
2. **parts** — propose every part whose `category` is `pricing`; a human confirms the **set**
   (several are legitimate: a bill of quantities *and* a daywork or provisional-items schedule).
   Stored in `bridge_bill_parts`, UNIQUE on `(set_id, part_id)`.
3. **scope** — the confirmed parts' text (read from each part's OWN pdf, so the 200-page
   extraction cap applies per part, not per binder) becomes `doc_text`, joined in the
   `=== label ===` convention `api.py` uses. Every OTHER part contributes `context_text` built
   from its interpreted `PartContext` card — not its raw text, which a 6000-char hard truncation
   would reduce to "part 1 and a fragment of part 2". `ingest_tender` is then called **unmodified**,
   and the promoted provenance quarantine runs over the bill's own section headers.
4. **routing gate** — routing sits BEHIND the review gate and both forks inherit it: you cannot
   decide self-perform vs sublet without knowing the contract terms, and you should not send an
   RFQ on terms nobody has read. `/bridge/{set_id}/route/analyze` 409s until the register is
   approved, then calls the existing `route_units()` / `package_signal()` / `recommend_routes()`
   unchanged.
5. **decisions** — the Layer-4 gate records the human's route per package in
   `bridge_route_decisions`, UNIQUE on `(set_id, package_key)`, and **seeds no estimate on either
   side** (see below).

## Outputs
- `ScopePackages` for the set (persisted, re-readable).
- A route proposal per package, then the confirmed self-perform / sublet split.

## Boundaries that are not negotiable
- **`client_boq` is read-only.** Every interaction is a Python import of `store.get_conn`,
  `store.load_parts`, `store.review_is_approved`, `store.load_register`. Nothing under
  `backend/client_boq/`, `frontend/src/client_boq/` or `docs/client_boq/` is created, edited,
  moved or deleted.
- **Nothing is seeded here.** `client_boq_estimates` is keyed by `set_id` — ONE estimate per
  tender — and that is correct: a main contractor submits one priced bill with a single tendered
  total, and every item is priced. The route decision changes only where each item's *rate* comes
  from (own build-up vs a subcontractor's quote), never which items appear. Seeding one estimate
  per self-perform package would create N documents where the tender needs one.
- **The procurement `/route/confirm` is untouched.** It seeds only when a `scope` is supplied; the
  bridge's own confirm passes none, so the standalone procurement path keeps working exactly as
  it does today with no edit to `api.py`.
- **An open query never blocks.** A client's unanswered RFI does not move the submission deadline,
  so the open-query count rides on the response for a human to see — it never refuses.

## Known-next (deliberately not built)
- ZIP upload and the folder-tree ingest tier.
- Streaming the upload and download instead of buffering in memory.
- The `SorItem` → `EstimateSchedule` adapter (the self-perform costing join).
- Any frontend work.
- Any Excel bill reader.
