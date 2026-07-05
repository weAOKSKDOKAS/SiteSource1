# SiteSource — Benchmark Estimator (product architecture)

> Status: **Phase B1 (the variance spine)** is the first cut of this design. The estimator
> itself (Phase B2) is **not** built yet — it activates only once a real archive of confirmed
> variance records exists. This document is the authoritative design; the B1 build prompt is
> its Phase B1 cut. Where the B1 prompt and this document differ, this document governs the
> schema and vocabulary and is kept in sync with the code.

## 1. What this is

For each **completed** project, capture the **priced tender** (what we bid) against the
**actual outturn** (the final account), **item-matched with a human gate**, into queryable
**variance records**. Over a series this becomes a proprietary, evidence-linked benchmark of
how our prices move between tender and outturn — the grounding corpus a future estimator
(B2) uses to price the next tender with cited precedent.

The moat is the same one the sourcing side has: **deterministic Layer-1 math + a human gate
+ a private corpus a generic chatbot cannot access.** The LLM never invents a number, a
match, or a reason — Layer 1 computes variance, the human confirms every match and every
reason code, and the corpus is local.

## 2. Pilot shape (decided)

- **Trade:** Ground Investigation (GI) specialist. HK government SoR item codes (e.g.
  `A1a(a)`, `M2`, `BA1`) **recur across a series of term contracts**, so **exact `item_ref`
  matching across projects is the primary retrieval and it is deterministic** — no model in
  the hot path.
- **No real archive exists yet.** B1 ships a clearly-fictional **demo** benchmark scenario so
  the flow can be pitched offline, and a **clean empty live** profile ready for real data.

## 3. Confidentiality posture (decided)

**Cost data never leaves the machine by default.**

- Storage is **local SQLite** (the same file the rest of SiteSource uses; new tables
  alongside the existing ones). Nothing is sent anywhere.
- **Actuals ingestion is deterministic-only** — our authored template xlsx parsed with
  openpyxl — **unless `ACTUALS_PDF_PARSE=true`**, which enables the chunked LLM parse
  fallback for a scanned/PDF final account. **Default off.** With it off, a PDF actuals
  upload is rejected with a clear message telling the operator to use the template.
- The LLM is only ever consulted for: the opt-in actuals-PDF parse (`actuals-parse`),
  Tier-2 match *suggestion* (embedding similarity — deterministic in DEMO, never a write),
  and an optional reason *pre-suggestion* (`match-suggest` / reason hint). **No LLM output is
  ever written** to a variance record without the human's confirmation.

## 4. Data model (§4)

Six new SQLite tables, alongside the existing SiteSource tables, created by the same
`schema.sql` rebuild. **Provenance columns** (`source`, `source_doc`, `tagged_by`,
`confirmed_at`) record where every row came from and who confirmed it. A project-level
`provenance` (`demo` | `live`) separates the fictional pitch scenario from real data so demo
rows **never** count in `/benchmark/summary`.

### `projects`
| column | type | notes |
| --- | --- | --- |
| `id` | INTEGER PK | the `{project}` path id |
| `name` | TEXT NOT NULL | e.g. "DEMO — Illustrative GI Term Contract" |
| `trade` | TEXT | canonical taxonomy key (e.g. `ground_investigation`) |
| `client` | TEXT | |
| `contract_ref` | TEXT | HK contract number, e.g. `GE/2026/14` |
| `status` | TEXT NOT NULL DEFAULT 'open' | `open` \| `closed` |
| `provenance` | TEXT NOT NULL DEFAULT 'live' | `demo` (fictional scenario) \| `live` (real). **The summary discriminator.** |
| `source` | TEXT | how captured: `tender-upload` \| `pipeline-link` \| `manual` \| `demo` |
| `notes` | TEXT | |
| `created_at` | TEXT | ISO-8601 UTC |
| `closed_at` | TEXT | set on close |

### `tender_items` (the priced tender snapshot)
| column | type | notes |
| --- | --- | --- |
| `id` | INTEGER PK | |
| `project_id` | INTEGER NOT NULL → projects(id) | |
| `item_ref` | TEXT NOT NULL | the SoR code — **primary cross-project match key** |
| `description` | TEXT | optional (scanned/rate-only lines) |
| `unit` | TEXT | optional |
| `qty` | REAL | **optional** — rate-only SoRs are first-class |
| `rate` | REAL | the priced tender rate (kept when the ingest returns a priced tender) |
| `amount` | REAL | optional — extended amount where computable |
| `section` | TEXT | SoR section label |
| `source` | TEXT | `tender-pdf` \| `tender-xlsx` \| `pipeline-link` |
| `source_doc` | TEXT | original filename |
| `created_at` | TEXT | |

### `actual_items` (the outturn / final account)
Same shape as `tender_items` plus **`granularity`**:
| extra column | type | notes |
| --- | --- | --- |
| `granularity` | TEXT NOT NULL DEFAULT 'item' | `item` \| `section` \| `project` — a final account may be item-by-item, section-totals-only, or a single project total |
| `source` | TEXT | `actuals-xlsx` \| `actuals-pdf` |

A `section`- or `project`-granularity actual produces a section/project-level variance
record — **never a fabricated item row**.

### `variance_records` (the confirmed variance — **written only by the confirm gate**)
| column | type | notes |
| --- | --- | --- |
| `id` | INTEGER PK | |
| `project_id` | INTEGER NOT NULL → projects(id) | |
| `tender_item_id` | INTEGER → tender_items(id) | NULL ⇒ arrived-unpriced (Tier-3) |
| `actual_item_id` | INTEGER → actual_items(id) | NULL ⇒ omission-at-tender (Tier-3) |
| `item_ref` | TEXT | the resolved ref (for query) |
| `granularity` | TEXT NOT NULL DEFAULT 'item' | inherits the actual's granularity |
| `match_tier` | INTEGER | 1 (exact) \| 2 (embedding) \| 3 (unmatched) |
| `tender_rate` / `actual_rate` | REAL | |
| `tender_qty` / `actual_qty` | REAL | |
| `tender_amount` / `actual_amount` | REAL | |
| `rate_delta` | REAL | `actual_rate − tender_rate` when both exist |
| `rate_delta_pct` | REAL | |
| `amount_delta` | REAL | only where both amounts computable |
| `amount_delta_qty` | REAL | qty-driven component (see §6) |
| `amount_delta_rate` | REAL | rate-driven component |
| `reason_code` | TEXT → reason_codes(code) | NULL until the human tags it |
| `reason_note` | TEXT | |
| `tagged_by` | TEXT | **provenance** — who set the reason |
| `confirmed_at` | TEXT | **provenance** — when the match was confirmed |
| `source` | TEXT | `demo` \| `confirm-gate` |
| `created_at` | TEXT | |

### `reason_codes` (the controlled vocabulary — **ten codes**, seeded in every profile)
| column | type |
| --- | --- |
| `code` | TEXT PK |
| `label` | TEXT NOT NULL |
| `description` | TEXT |
| `category` | TEXT (`ground` \| `time` \| `quantity` \| `rate` \| `scope` \| `commercial`) |

The ten GI-pilot codes:

1. `ground_conditions` — unforeseen ground / rock / obstructions (harder strata than tendered).
2. `standing_time` — plant/rig standing idle (waiting, breakdown, instruction).
3. `weather` — inclement weather / typhoon standing.
4. `access_restriction` — restricted or delayed site access.
5. `quantity_remeasure` — remeasured quantity differs from the tendered quantity.
6. `rate_reprice` — rate corrected or renegotiated against the tendered rate.
7. `scope_variation` — client-instructed variation / additional scope.
8. `omission_at_tender` — an item required on site but missing from (or not required by) the priced tender.
9. `additional_testing` — extra in-situ / laboratory testing instructed.
10. `provisional_sum_adjustment` — provisional / prime-cost sum reconciled at final account.

### `rubric_items` (evidence-linked estimating guidance — **ships EMPTY**)
The B2 estimator's curated guidance, each entry backed by a real `variance_record`. Because
an entry cannot exist without real evidence, **`rubric_items` ships empty in the live profile**
(and the B1 demo does not fabricate any). B1 creates the table only.
| column | type | notes |
| --- | --- | --- |
| `id` | INTEGER PK | |
| `trade` | TEXT | |
| `item_ref` | TEXT | the pattern the guidance applies to |
| `guidance` | TEXT | |
| `evidence_variance_id` | INTEGER → variance_records(id) | the citation |
| `source` | TEXT | |
| `created_at` | TEXT | |

## 5. Flow

### 5a. Capture the tender
Upload the old priced tender (PDF → reuse stage-01 ingest internals; or xlsx in our SoR-sheet
layout → deterministic parse) → `tender_items` with rates preserved and quantities optional.
Or **link** a tender already run through the sourcing pipeline (capture its scope into
`tender_items`) — the compounding loop (§10).

### 5b. Capture the actuals
Download the authored **Final Account template** (`item_ref | description | unit | qty | rate |
amount | section`), pre-filled with the project's tender item refs/descriptions so the operator
only types the actual numbers. Upload it → openpyxl parse (tolerant of blank cells, text
numbers, missing qty) → `actual_items` with granularity detected. Wrong layout → clean 400.
PDF → 400 unless `ACTUALS_PDF_PARSE=true`.

### 5c. Match (tiered) + confirm gate
- **Tier 1 — exact `item_ref`.** Deterministic; the primary retrieval. Confirm-all allowed.
- **Tier 2 — embedding similarity** on description (reuse `db/embeddings.deterministic_embedding`,
  cosine ≥ threshold) for lines whose refs did not match exactly. Suggestion only; individual
  confirm/repair.
- **Tier 3 — unmatched**, both directions: a **tender line with no actual** (omission
  candidate) and an **actual line with no tender** (arrived-unpriced). Individual confirm/repair.

`GET /benchmark/{project}/matches` returns the tiered proposal. **`POST
/benchmark/{project}/matches/confirm` is the ONLY writer of `variance_records`** — the Layer-4
gate. Confirm-all is allowed for Tier 1; Tier 2/3 are confirmed/repaired individually.

### 5d. Reason + query
`POST /benchmark/{project}/variance/{id}/reason` sets `reason_code` (one of the ten) + a note;
a model pre-suggestion is allowed behind the existing text-call routing but **the write
requires the human's code**. `GET /benchmark/{project}/variance` is the table;
`GET /benchmark/summary` reports projects / record counts / coverage by trade and granularity,
**counting the live profile only** (`provenance='live'`) — demo fixtures never leak in.

## 6. Variance math (§6, rate-primary — mirrors `computable_amount`)

The same rate-primary discipline as the leveling engine:

- **`rate_delta` always** when both a tender rate and an actual rate exist.
- **Amount deltas only where computable** — an amount exists when both qty and rate are present
  (or an amount was stated). **Never fabricate an amount for a rate-only line.**
- When **both sides have qty + rate**, decompose `amount_delta = actual_qty·actual_rate −
  tender_qty·tender_rate` into:
  - **qty-driven** `amount_delta_qty = (actual_qty − tender_qty) · tender_rate`
  - **rate-driven** `amount_delta_rate = actual_qty · (actual_rate − tender_rate)`
  (so `amount_delta_qty + amount_delta_rate = amount_delta`, exactly).
- **Section/project-granularity actuals** produce section/project-level records (amount deltas
  only) — never fake item rows.

## 7. Layering (unchanged principle)

- **Layer 1** — `rules_engine/variance.py`: pure, deterministic variance math (the decomposition
  above). No LLM.
- **Layer 2** — the matcher's Tier-2 suggestion and the optional reason hint (text routing),
  and the opt-in actuals-PDF parse. Suggestions only; never a write.
- **Layer 3** — `db/benchmark_store.py`: the six tables, reads and gated writes (local SQLite).
- **Layer 4** — the confirm gate (`/matches/confirm`) and the reason write. The human owns
  every match and every reason.

## 8. Profiles (demo / live)

Following the existing `SITESOURCE_DB` profile discipline: the fictional demo scenario is seeded
**only into the demo profile**; the **live profile ships with empty benchmark tables** (plus the
ten `reason_codes`, which are a controlled vocabulary, not data). `reason_codes` seed in both
profiles; `rubric_items` empty in both; the demo project carries `provenance='demo'` so
`/benchmark/summary` (which counts `provenance='live'`) stays **zero** on the live profile.

## 9. What B1 is NOT

The estimator (B2) — pricing the next tender from the corpus with cited precedent — is out of
scope. It activates only once a real archive exists. B1 builds the spine that fills the archive.

## 10. The compounding loop

Every tender the sourcing pipeline runs can be **linked** into a benchmark project (its scope →
`tender_items`); when that project completes, its actuals close the loop into variance records.
So the sourcing side feeds the estimating side, and the estimating corpus grows with normal
operation — the compounding advantage.
