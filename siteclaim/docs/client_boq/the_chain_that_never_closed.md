# The chain that never closed — research, and the shape I propose

**Status:** research complete. Written 2026-08-11, before building, as the brief asked.
**Subject:** the costing engine never reads a clause. Four seams were built, tested, and never wired.

---

## 0. What was found

Four dead seams, and two of them are strictly downstream of the other two.

| Seam | Built | Tested | Wired |
| --- | --- | --- | --- |
| `RateRecipe` → `price_item` → `blend` | yes | yes — the ten-rate regression, `test_boq_costing.py:129-135` | **no non-test caller** |
| `parse_index` → `client_boq_docmaps` | yes | yes — `test_boq_unbilled.py:75-124` | **zero writers; table verified 0 rows** |
| sweep SPREAD pool → `price_bill(spread=)` | yes — `_allocate` | yes — `test_boq_pricing.py:154-181` | **never passed a value** |
| `PricedItem.spread` → `trace_rate(spread_share=)` | yes | yes — `test_boq_coverage.py:202-207` | **hardcoded `0.0`, `router.py:4250`** |

---

## Q1 — What `RateRecipe` actually expresses

`boq/allocate.py:75-112`. It is a **declarative recovery plan for one bill line**, and it holds no
numbers of its own — every number comes from the `ResourceSheet` it is evaluated against. Its whole
content is the formula in its own module docstring:

```
rate  =  ( Σ terms )  ×  days  ×  markup  ÷  divisor
```

`terms` is a list of `RecipeTerm` (`allocate.py:62-72`), each naming a resource key and how many
units of it this item carries. **That is the "one BQ item, many costing items" expression**, and it
is the only one in the codebase: a drilling metre as rig time *plus* logging *plus* casing *plus*
disposal is exactly a list of terms.

What it was built to solve, in its tests' words (`test_boq_costing.py:1-11`):

> "the engine must reproduce a working estimator's own spreadsheet, **to the cent**. That is not a
> nicety. The product only earns its place if the person who can already do this work can check it
> faster than he can redo it… If our number and his number differ, the code is wrong; the
> spreadsheet is the specification."

and the blending problem (`allocate.py:28-37`): one bill rate must cover 2,300 m over 91 holes that
are not alike, so the model runs per hole group and the rate is the blend.

**Confirmed dead at both ends.** Built only by `tests/_hke_workbook.py:186-225` and three ad-hoc test
sites. Consumed by `price_item` (`allocate.py:135`) → `groups.blend` (`groups.py:354-367`) → tests
only. `router.py` imports `boq_groups` but calls `summarise`, `GroupPlan` and `band_calibration` —
never `blend`.

One consequence worth naming, because it is visible in the product today: `router.py:4239-4244`
hand-constructs a `RateBreakdown` from stored rate rows with **empty `terms` and empty `groups`**, so
the rate-trace screen renders a build-up node with no children. The tree the design advertises is
structurally present and empty.

**The live engine is a different one:** `boq/model.py` → `boq/programme.py` → `boq/buildup.py` →
`boq/costing.py::price`, wired at `router.py:4509-4537`. There, one bill item maps to **at most one
cost basis** (`ItemMapping.basis_key`), and the multiplicity lives *inside* the basis rather than in
a list of terms.

## Q2 — What is missing between a coverage head and a cost line

`CoverageHead` (`heads.py:59-69`) carries seven fields: `key`, `label`, `clause_ref`, `cites`,
`authored_by`, `scope`, `provenance`. **The `label` IS the clause's own words** — `smm_s01.py:79-101`
takes `text` verbatim from the PDF so the file can be diffed against the document line by line. So a
head is not a label pointing at text elsewhere; it is the text.

Four things are missing, and each is concrete:

1. **`CostLine` has no field for a head.** `models.py:836-849` — `item_id`, `description`,
   `resource_ref`, `qty`, `unit`, `productivity`, `hours`, `rate`, `rate_source`, `amount`. Its
   finest outward key is `item_id`, which is the granularity the tick already has.
2. **Nothing points back.** `CoverageEntry` (`coverage.py:987-1013`) carries page, provenance and
   tick state — nothing about what was priced.
3. **The store has no column for the join.** `client_boq_coverage_ticks` (`models.py:1690-1699`) is
   keyed `(set_id, rev, full_ref, head_key)` with a boolean and an actor. **A tick is a belief about
   an item, not a link to a cost.**
4. **The two are never in one object.** `GET /boq/{set_id}/priced` returns cost with no coverage;
   `GET /price/{set_id}/coverage/{full_ref}` returns coverage with no cost. Two endpoints over two
   disjoint models — and no frontend calls either (`grep "price/"` over `src/` returns nothing).

## Q3 — `client_boq_docmaps`

**One reader** (`router.py:4160-4169`), **zero writers.** Repo-wide grep returns exactly two hits:
the DDL and that SELECT. `store.py` has no docmap function at all. `parse_index` (`docmap.py:94-175`)
is called only from three test files. Verified empirically: `client_boq_demo.db` holds **0 rows**.

**Who was meant to write it** is nowhere stated in words. The strongest evidence is the DDL comment's
own column semantics (`models.py:1701-1706`): `source` is *"the part id the index was read from:
`04-PS`"* — a part id, which is **ingest's** identifier. That points at the specification-reading
side, not the coverage work and not the split. I am marking this an inference, not a documented
decision. The backlog has a row for the lookup (`E7`, done) and none for a writer.

The consequence is already handled honestly and is the only thing in the running system that reports
the gap — `coverage.py:1236-1237`, on every citing head:

```python
entry.unresolved = "the specification index has not been read for this set"
```

## Q4 — `spread_share`

**Derivable, not a judgement — and the judgement it depends on is already made elsewhere.**

The pool exists because the contract orders certain costs into the rates with no bill line
(`unbilled.py:29-32` — site uniform, PP ¶11/¶2A: *"There shall be no measurement or separate
payment"*). The **judgement** is upstream in `unbilled.py`: which believed costs exist and which of
four routes each takes, stamped with `decided_by`. Once a cost is routed SPREAD, the **distribution
is arithmetic**, and `pricing.py:61-89` already says what decides it:

> "Spread `total` across the priced items pro rata on their **build-up value**… because the pool is
> overheads and obligations that scale with the work, and value is the only proxy the bill itself
> supplies — an equal split would load a 1 nr signboard the same as 2,300 m of drilling."

Its output is already carried per item: `PricedItem.spread` (`models.py:1094`), set at
`pricing.py:131, 183`. **So `spread_share` for item X is `PricedItem.spread` for item X.** The engine
computes it; the trace endpoint does not ask for it.

The asymmetry at `router.py:4250` is the finding: `spread_total` is loaded from the real sweep and
`spread_share` is a literal `0.0`. Because `trace.py:147` guards on `if spread_share:`, the node is
never created — and `spread_total` is used *only inside that node's note*. **The endpoint reads the
pool from the database and discards it on every request.** No comment or TODO explains the zero.

## Q5 — `price_bill(spread=...)`

**Never given a value outside tests.** Both production call sites (`router.py:3535`, `router.py:3555`)
omit it. With `spread=None`: `spread_total → 0.0` → `_allocate` returns `({}, "")` → every
`PricedItem.spread == 0.0` → `PricedBill.spread_total == 0.0` → `tendered_total` omits the pool.

**The missing link is one converter.** `models.SpreadLine` — the type `price_bill` wants — is
constructed nowhere in production. The data that should fill it *is* persisted
(`client_boq_sweep_costs` → `store.load_sweep` → costs with `route == ROUTE_SPREAD`), and the fields
line up almost one-to-one (`UnbilledCost.label/amount/source` vs `SpreadLine.label/amount/reason`).
Nothing performs the mapping.

`UnbilledSweep.loadings()` has the same problem in a stronger form: `price_bill` has **no parameter
at all** for per-item loadings, so a cost routed LOAD to a named item cannot reach that item's rate.

---

## The shape I propose

### What I am NOT doing, and why

**Not wiring `RateRecipe` into the live path.** It is the richer expression and it should eventually
supersede the basis, but swapping the pricing engine to reach a reporting feature is a rewrite
wearing a fix, and its ten-rate regression pins it to a spreadsheet whose inputs the live engine does
not have. Reported, left standing, and named below as the thing this supersedes.

**Not inventing which heads a basis discharges.** That is a domain judgement — §0 says parameterise
and flag rather than encode a guess. So the mechanism ships with nothing claimed, and every head
reads as unaccounted until a person says otherwise.

### The change

**A tick stops being a belief and becomes a link.** Today a coverage tick says *"my build-up carries
this head"* and nothing checks it. One nullable column turns it into *"this head is carried by THIS
line of my build-up"*, and that is checkable:

| State | Meaning |
| --- | --- |
| **accounted, with cost** | ticked, and the named cost basis is one this item's rate actually draws on |
| **asserted, no cost named** | ticked, nothing named — a belief, exactly what a tick is today |
| **claimed against absent cost** | ticked against a basis this item's rate does **not** draw on — the obligation is claimed against money that is not in the rate |
| **unaccounted** | not ticked by anyone. **Visible, never assumed included** |

The third row is the find. It is deterministic, it needs no judgement from the engine, and it is
precisely *"a rate that omits a covered obligation is a rate that loses money silently"* — caught by
arithmetic instead of by a reader's memory.

Concretely: `client_boq_coverage_ticks` gains `basis_key TEXT NOT NULL DEFAULT ''` (additive — an
existing tick reads as *asserted, no cost named*); `CoverageEntry` gains the basis and how it is
evidenced; a pure rule in `coverage.py` classifies each head against the item's real
`ItemMapping.basis_key` and the build-up's rows; `ItemCoverage` reports the four counts;
`POST /price/coverage/tick` accepts the basis; and `GET /price/{set_id}/coverage/{full_ref}` returns
both the classification and the bases the item's rate actually draws on, so the choice is a pick
rather than a typed key.

**The loop, proved on one item:** a drilling item → its `ItemMapping.basis_key` → the build-up row
that basis names → the coverage heads a person has linked to it → and, for every head with no link,
a line saying so. That is bill item → cost → clause → back, end to end, with no step invented.

### Two smaller closures, both arithmetic

- **The spread converter.** `UnbilledCost` (route SPREAD) → `models.SpreadLine`, passed to
  `price_bill`. One mapping function; the allocator behind it is already written and tested.
- **`spread_share`.** Once the pool reaches `price_bill`, `PricedItem.spread` is the value
  `router.py:4250` should pass. Both are pure arithmetic downstream of a judgement already made and
  already stamped with a name.

### Left as reported, not built

- **`client_boq_docmaps` has no writer.** Writing one means reading a specification index at ingest
  time, which is a new stage rather than a wiring change. The system already says the right thing
  when the table is empty. Named here so the gap is a decision rather than an oversight.
