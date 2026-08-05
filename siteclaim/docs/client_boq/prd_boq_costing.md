# The costing model: a real Bill of Quantities, priced, and revised

What is being built, why, what the evidence says, and how it is put together.

Companion to `estimating_process.md` (the domain spec, written from general practice). This document is
written from **one real tender** — CEDD contract ND/2025/04, *Ground Investigation Works for Development
of San Tin Technopole (Phase 2)* — because the general spec does not say what a bill of quantities
physically is, and the physical facts turn out to decide the design.

Every number and every quotation below is measured from the issued package. Where a document does not
answer a question, this says so rather than filling the gap.

---

## 1. The problem

### 1.1 What the app models today

`EstimateSchedule` is a flat list:

```
EstimateSchedule(duration_weeks, items[])
  └─ ScheduleItem(item_id, description, category, unit, lines[], basis, amount, rate, pct)
       └─ ResourceLine(description, resource_ref, inline_rate, qty, unit, productivity)
```

You invent the activities. There is no bill, no section, no item numbering, no client quantity, and no
unit rate — `CostActivity` carries `activity_total` and nothing per-unit. There is one estimate per
document set (`client_boq_estimates.set_id PRIMARY KEY`), so re-pricing overwrites and nothing survives
a revision.

### 1.2 What a tender actually hands you

Nine bills, 166 items, quantities already measured, in a Microsoft Excel workbook you are required to
price *in place*:

> **GCT Appendix A ¶9** — "For the avoidance of doubt, bill of quantities shall **only** be submitted in
> Editable File format, i.e. the Microsoft Excel format."
>
> **¶10** — "Tenderers shall prepare the electronic files for bill of quantities **using the electronic
> files in Microsoft Excel format in the Tender Documents provided by the Client. Tenderers shall not
> modify cells that are locked and protected, failing which shall constitute a qualified tender.**"

and *"Any qualification of the tender may cause the tender to be disqualified"* (GCT 9). So the
deliverable is not a workbook we generate — it is **their** workbook with our rates in it.

### 1.3 The gap, stated once

| | missing today | what it costs |
|---|---|---|
| **above the cost engine** | the bill: item refs, headings, units, client quantities, and a **rate per unit** | the app cannot produce the one number the tender asks for |
| **below the cost engine** | the production assumptions that generate `qty` and `productivity` | you type "1,920 hours" and nothing records why — and that number *is* the estimate |
| **across time** | any revision axis on a price | an addendum destroys the prior estimate |

`CONTEXT.md` decision 1 already anticipated the first of these: quantities come *"from a **BOQ** or manual
entry"*. `estimate/s02_schedule.py:9` marks itself the seam. The door was specified and never built.

---

## 2. The evidence

### 2.1 The workbook

`E-ND_2025_04_BQ-0.xlsx` (Rev 0), `-BQ-1.xlsx` (Rev 1, Tender Addendum No. 1), `-BQ-2.xlsx` (Rev 2,
Tender Addendum No. 2). 11 sheets each, same names and order in all three: `Index`, `Grand Summary`,
`Bill No.1` … `Bill No.9`. No sheet was ever added, removed, renamed or hidden.

Fixed columns on every bill sheet:

| col | content |
|---|---|
| A | item reference |
| B / C / D | description — **the column is the indent level** |
| E | quantity |
| F | unit |
| G | rate (HK$) |
| H | amount (HK$) |

### 2.2 An item's description is a chain, not a string

There is no description column. Item 2.9 reads, in the cell, `"maximum depth not exceeding 3.00m"` —
which is meaningless. Its actual meaning is assembled by reading up the captions:

```
SECTION 2 - GROUND INVESTIGATION          B5    bold + underline
  Trial Pits and Inspection Pits          B29   bold + underline
    Extra over for excavation in rock     B37   bold + underline
      maximum depth not exceeding 3.00m   C38   17 m3
```

The General Preambles make this contractual, not cosmetic:

> **General Preambles ¶2** — "the **headings, sub-headings**, item descriptions and the matters listed
> against the relevant marginal headings 'Item coverage' … identify the work covered by the respective
> items, **but such descriptions or identifications may not be exhaustive**."

### 2.3 One bill line averages over many different holes

The measurement rules slice drilling four ways, because each slice costs differently:

| dimension | rule | values |
|---|---|---|
| material | S02 ¶2.12 Group IV | "material other than rock, boulder or artificial hard material" / "rock" / "artificial hard material and boulder" |
| hole size | S02 ¶2.12 Group III | "Drilling size H or N" |
| depth stage | S02 ¶2.12 Group V (added by TA1) | "In first stage of drillhole **not exceeding 20m** in length" / "In second stage … exceeding 20m but not exceeding 40m **and so on in stages of 20m**" |
| site class | S02 ¶2.06 Group II (added by TA1) | "For moving rigs in different **Classes of site**" |

with the datum fixed: *"the different length stages … shall be measured **from the existing ground level**"*
(¶2.11A).

Bill 2 then says `2,300 m` soil, `600 m` rock, `100 m` artificial hard material. It does **not** say which
holes those metres come from. The consultant's quantity surveyor took the drawings off hole by hole and
*summed*. To price it you must run that backwards.

The evidence for running it backwards is in the package:

- **33 drawings** (job 60740338, prefix GI): every proposed borehole and trial pit as a numbered station
  with coordinates (GI/200–205 engineering `CE19-BH`; GI/301–303 environmental `AEDH`; GI/210 and GI/310
  the coordinate tables), the working areas (GI/000–016), and **GI/100** carrying tentative in-situ test
  quantities that cross-check the bill.
- **Site Information Annex 1**: existing borehole logs from **14 past ground investigations** on the same
  ground — the only evidence of how much of those metres will be soft going.

**That assumed mix is the estimate.** One rate covers a 5 m hole in easy access and an 18 m hole in
Class B, and deep metres are slower metres. Assume 20% hard going where it proves to be 40% and the rate
is wrong for all 2,300 m — and under NEC Main Option B (remeasurement) wrong for the whole contract.

This is **not take-off**. Take-off derives the quantity; the client already did that and we may not
change it. What is modelled here is the *distribution* of a quantity we were given. The total never
moves — only its shape.

### 2.4 What every rate must carry even without a line

General Preambles ¶2 lists 22 deemed-included heads, (i)–(xxii), ending *"(xxii) establishment charges,
overheads and profit"*. Particular Preambles ¶¶7–10 insert (i)A and (xxiii)–(xxxi), taking it to 31.
Then the sweeper:

> **Particular Preamble ¶12, adding Part IV ¶4A** — "The item coverage … **is not meant to be a
> comprehensive or exhaustive list** covering all costs in relation to work of that item. … **Any item
> missed out from the item coverage shall not be measured** unless it is expressly required to be
> measured under other provisions in the Method of Measurement."

and named "there is no item for this, spread it" instructions: GP ¶6 (unpriced items), PP ¶11/¶2A (site
uniform: *"There shall be no measurement or separate payment"*), NTT C2 (Subcontractor Management Plan),
NTT C14, NTT C25 (Pay for Safety Scheme to subcontractors).

GP ¶6 is the trap with teeth:

> **General Preambles ¶6** — "**Items against which no rate is entered shall be deemed to be covered by
> the other rates in the bill of quantities.**"

A blank rate is not an omission you can fix later. It is a zero rate you are bound to for the life of the
contract. The tender-examination side agrees: *"the rate shall therefore be marked as zero"*
(GCT App C 2.2(iii)).

### 2.5 The revision behaviour

| | Rev 0 → 1 (TA1) | Rev 1 → 2 (TA2) |
|---|---|---|
| items added | 3 (`2.2a`, `2.2b`, `3.2a`) | 1 (`1.61A`) |
| items deleted | 0 | 0 |
| quantity changed | 5 | 0 |
| description changed | 0 | 3, plus **1 caption** |
| unchanged | 157 | 162 |
| **renumbered** | **0** | **0** |
| rows physically moved | 35 | 2 |

**The item reference is a stable primary key; the row number is volatile.** Both insertion mechanisms
prove it:

- splitting `2.2` (91 nr) kept `2.2` as a caption and put bare `a` (80 nr) and `b` (11 nr) beneath it;
  `2.3`–`2.26` moved down a row each and **kept their references**;
- the new signboard item was numbered **`1.61A`** — a suffix letter, stored as the string `'1.61A'` —
  precisely so `1.62` and `1.63` would not have to be renumbered. They moved 7 rows and kept their refs.

So identity is `(bill_no, item_ref)`. Never `(sheet, row)`.

### 2.6 Nothing in the workbook marks what changed

Checked exhaustively across all three revisions:

| probe | result |
|---|---|
| filled cells | **0** — every one of 1,226 / 1,234 / 1,239 non-empty cells has `fill_type = None` |
| font differences on changed rows | none — identical `Times New Roman 11` regular |
| cell comments | 0, in every sheet of every revision |
| defined names | none |
| tracked changes (`xl/revisions/`) | absent |
| `"ddendum"` anywhere in the XML | Rev 0: 0 hits · Rev 1: 3 hits, all `<oddFooter>` · **Rev 2: 0 hits** |

Rev 1 carries a **sheet-level print footer** on Bills 2, 3 and 6 (one with a typo, `Tender Addendum No, 1`).
Being sheet-level it cannot point at a row, and it marks unchanged pages of those bills too. **Rev 2's
spreadsheet carries no revision marking at all** — its PDF twin does, page by page, so the two
deliverables disagree with each other.

Which leaves the largest price movement in the tender announced as seven words:

> **Tender Addendum No. 1, Bill No. 6** — *"Updated the quantities of item nos. 6.4 – 6.6."*

| item | Rev 0 | Rev 1 | | per instrument |
|---|---|---|---|---|
| 6.4 Standpipe, recording | 1,128 nr-wk | **2,451** | ×2.17 | 24.0 wk → 52.1 wk |
| 6.5 Piezometer, recording | 1,623 nr-wk | **3,546** | ×2.18 | 23.9 wk → 52.1 wk |
| 6.6 AGMD, recording | 2,760 nr-wk | **5,996** | ×2.17 | 24.0 wk → 52.1 wk |

Six months of groundwater monitoring per instrument becoming twelve — three unmarked cells mid-page
(`Bill No.6!E19`, `E21`, `E23`, with no row movement at all). It is the answer to Tender Clarification
No. 1 Item 2: *"The monitoring work shall last for at least 12 months after installation of the
piezometer/standpipes."* The tenderer asked for one extra week to reprice; refused (TC2 Item 7).

### 2.7 The addendum's own summary is disclaimed, and is wrong

Both addenda work purely by **page replacement**. Neither contains a single "delete item X, substitute Y"
instruction. Both say:

> "(2) The remarks (Columns B) only briefly describe the amendments made in the tender addendum. **The
> descriptions are neither exhaustive nor guaranteed to be accurate.** The tenderer is required to
> ascertain the amendments himself from the contents of the tender addendum documents."

And TA1's remark for Bill No. 3 — *"Updated item no. 3.2 to form item nos. 3.2a and 3.2b"* — is factually
wrong. Only `3.2a` exists, in both spreadsheets and both PDFs. There is no `3.2b`.

**Design consequence: trust the documents, never the summary of them.** This is the same rule
`ingest/s03_map_changes.py` already applies to part mapping.

### 2.8 A caption change is a scope change

TA2's second BQ change was one cell: `Bill No.1!C22`, `"Maintain marine traffic flow"` →
`"Maintain land traffic flow"`. Items 1.5, 1.6 and 1.7 beneath it were not edited at all. But by GP ¶2
the sub-heading identifies the work, so those three items now import the land-traffic item coverage of
SMM S01 ¶¶1.14/1.15 — a Traffic Consultant, temporary street lighting, tow-truck and emergency telephone
provision — instead of marine.

The client's own addendum identifies the change *by the items it governs*: *"above item nos. 1.5-1.7"*.

An item-row diff would report "nothing changed" here. **The caption chain must be diffed.**

### 2.9 The client publishes the re-pricing rules

Because an addendum binds whether or not you pick it up, the tender examiner has published rules for
carrying your rates across. They are the correct default because they are what will happen to your bid
anyway.

> **GCT Appendix C 2.1** — "**Under no circumstances can the tendered rates be changed.**"
>
> **2.2(v)** — "Should there be a tender addendum introducing changes to the bill of quantities but the
> changes have not been incorporated into the bill of quantities by a tenderer, then the changes as
> required by the tender addendum shall be incorporated into the tenderer's bill of quantities and the
> rates for those new items or modified items shall be determined as follows:"

| situation | rule (verbatim) |
|---|---|
| new item introduced | "Rate for the new item shall be marked as zero and the price of the item shall be deemed to have been allowed for in rates entered elsewhere … **unless it is an item pre-priced by the Client. For a pre-priced item, the same rate in the addendum shall be used.**" |
| item description and/or quantity changed | "**If a rate has been entered against the original item of work, the same rate shall be used.**" |
| item deleted | "That item shall be deleted in accordance with the addendum." |
| measurement unit modified | "If a rate has been entered against the original item of work, **the rate shall be adjusted to fit in with the new unit.**" |

Note the asymmetry these produce. On TA1's quantity doubling the rule is adverse to a careless tenderer
(same rate × double quantity). On TA2's Bill 4 narrowing — items 4.18–4.20 went from *"test for soil and
ground water"* to *"test for soil"* at unchanged quantity — it is adverse to the Employer.

### 2.10 The reader's landmines

**Item references are stored as floats.** Excel strips the trailing zero, so item **1.20** is stored as
`1.2` — which is also item **1.2**. There are **12 raw-value collisions** in Rev 2:

```
Bill No.1: 1.2 at rows [12, 98]  1.3 at [14,143]  1.4 at [18,171]  1.5 at [23,219]  1.6 at [25,265]
Bill No.2: 2.1 at rows [9, 43]   2.2 at [11, 77]
Bill No.3: 3.1 at rows [8, 42]
Bill No.4: 4.1 at rows [9, 28]   4.2 at [11, 62]
Bill No.9: 9.1 at rows [8, 45]
```

The **only** thing separating them is `cell.number_format` — `General` vs `'0.00'`. Read `cell.value`
alone and you silently merge items that carry different rates. Two refs are stored as strings (`'1.10'`,
`'1.61A'`); one is a data-entry error (`2.244`, format `'0.00'`, printing as "2.24").

**`Bill No.4` is structurally corrupt.** `ws.dimensions` reports `A1:XFD167`, `max_column = 16384`. There
are ~76,500 stray non-empty cells past column H — a page-header block fill-right-dragged across the whole
sheet, reading `'Bill No. 1'` inside Bill No.4 — and **9,963 merged ranges** (other sheets have 9–57).
It prints fine because the print area is clamped. openpyxl raised `MemoryError` materialising Rev 2's.
Every read must clamp to column H.

**Page references exist only as geometry.** `BQ/2/1` appears nowhere in any cell. It is derived from
`ws.row_breaks`, yet the `Index`, the `Grand Summary` and both addenda all cite it.

**Other measured facts the reader must handle:**

- 60 of 162 items are lump: `E = '-'` (a literal hyphen string), `F = 'item'` or `'sum'`, `G = '-'`, only
  `H` priced. Distinct from item 3.10 `Water sample`, a genuine `0 nr` that still needs a rate.
- 15 raw unit strings normalise to 14: `'item'` / `'item '` / `'Item'`; `'nr'` / `'nr.'` / `'nr. '`.
- Multi-line descriptions are author-hard-wrapped continuation rows carrying **semantically necessary**
  leading/trailing spaces (`' than 7 seats excluding driver'`). Longest observed: 5 rows.
- Item 1.16's quantity sits on the **caption row above** its item row (rows 84/85) — the only such case.
- 12 rows are pre-priced by the client: all of Bill No.9 (HK$429,810.00 total, the Pay for Safety Scheme)
  plus item 8.2 at HK$15,400.00/mth. `GCT App C 2.2(vi)` reinstates them if a tenderer alters them.
- **Only 16 formulas exist in the entire workbook**, 14 of them in Bill No.9. Every page total,
  collection line and Grand Summary line the tenderer must fill is an empty cell with no formula. There
  is no sheet protection and no data validation anywhere.

### 2.11 The Grand Summary

```
Bills 1–9 …………………………………………………………………………
Sub-total above                                                  (A)
Tendered total of the Prices = (A)   [carried to the Form of Tender and Contract Data Part two,
                                      subject to the correction rules in Clause GCT 11]
Contingency sum for Defined Cost for compensation events*        (B)   4,342,620.00   [client]
Contingency sum for Fee for compensation events*                 (C) = (B) × direct fee percentage
Provisional sum for price adjustment for inflation, X1*          (D)   1,550,000.00   [client]
Provisional sum for PFSPMS performance-tied payment, X20*        (E)     609,370.00   [client]
Sub-total of contingency and provisional sums*                   (F) = (B)+(C)+(D)+(E)
Forecast total of the Prices for tender evaluation*              (G) = (A)+(F)
```

> \*"The contingency sums, provisional sums and forecast total of the Prices **shall not form part of
> this contract**." (ACC Clause II:4; GCT 36)

(A) is contractual; (G) exists only for scoring — *"60 × lowest forecast total ÷ this tenderer's forecast
total + 40 × performance ratio"* (NTT Appendix A). So the direct fee percentage — a Contract Data entry,
not a bill rate, floored and capped by SCT 19 — feeds (C) → (F) → (G) and is directly price-competitive.

There is **no Daywork bill and no Provisional & Prime Cost Sums bill** in this contract: Particular
Preamble ¶5 replaces the SMM's standard bill list with Bills 1–9, and Particular Preamble ¶2 deletes the
SMM's own definitions of *"daywork"* and *"provisional item"* outright. Under Option B, change is a
compensation event valued at Defined Cost plus the fee percentage.

---

## 3. The workflow

```
   the client's documents                    an addendum arrives
            │                                        │
      [ingest: split, interpret]  ← BUILT      [receive: propose, commit nothing]  ← BUILT
            │                                        │
      [review: register, gate]    ← BUILT      [approve: append a revision]        ← BUILT
            │                                        │
      [scope: freeze gate]        ← BUILT      [clause verdicts reopened]          ← BUILT
            │                                        │
            ▼                                        ▼
    ┌───────────────────┐                   ┌──────────────────────┐
    │  IMPORT the bill  │                   │   DIFF the two bills │
    │  reader.py        │                   │   diff.py            │
    └─────────┬─────────┘                   └──────────┬───────────┘
              │                                        │
              │                              ┌─────────▼──────────┐
              │                              │  CARRY the rates   │
              │                              │  carry.py — App C  │
              │                              └─────────┬──────────┘
              │                                        │
              │                              ┌─────────▼──────────┐
              │                              │  re-price worklist │
              │                              │  GATE: needs_review│
              │                              └─────────┬──────────┘
              ▼                                        │
    ┌───────────────────────────────────────────────────────────────┐
    │  PRICE each item                                              │
    │    production.py  condition mix → shifts, crew-hours          │
    │    s03_cost_buildup  resources × rate book       ← BUILT      │
    │    pricing.py     ÷ quantity = UNIT RATE, spread pool, roll-up│
    └─────────────────────────────┬─────────────────────────────────┘
                                  ▼
                        ┌───────────────────┐
                        │  CHECK checks.py  │  GP 6 · App C · GCT 14 · SCT 19
                        └─────────┬─────────┘
                                  ▼
                        write-back into the client's workbook   ← NOT BUILT
```

---

## 4. The data model

### 4.1 The bill

```python
class BillItem(BaseModel):
    bill_no: str          # "1".."9"
    item_ref: str         # the FORMATTED reference — "1.20", "2.10", "1.61A"
    sub_ref: str          # "a" / "b" for a lettered variant, else ""
    full_ref: str         # "2.2a", or == item_ref
    heading_path: list[str]   # the caption chain, outermost first
    description: str      # the item's own text, continuation rows joined verbatim
    unit_raw: str         # exactly as it appears: "item ", "Item", "nr."
    unit: str             # normalised: "item", "nr"
    qty: float | None     # None for a lump item; 0.0 is a real quantity
    lump: bool            # E == "-"
    client_rate: float | None
    client_amount: float | None
    pre_priced: bool
    page_ref: str         # "BQ/2/1", derived from row_breaks
    sheet: str
    row: int              # volatile — a write-back anchor only, never an identity
    notes: list[str]      # honest degradations, never silent
```

`full_ref` is the identity. `row` exists solely so a future write-back knows which cell to fill.

```python
class ClientBill(BaseModel):
    set_id: str
    rev: int
    source_file: str
    items: list[BillItem]
    summary: list[GrandSummaryLine]
    notes: list[str]      # workbook-level anomalies
```

### 4.2 Storage — three tables, append-only

```sql
client_boq_bill_revisions  (set_id, rev, doc_id, source_file, bill_json, read_notes, created_at,
                            PRIMARY KEY (set_id, rev))
client_boq_bill_rates      (set_id, rev, full_ref, rate, amount, buildup_json, basis, badge,
                            needs_review, updated_by, updated_at,
                            PRIMARY KEY (set_id, rev, full_ref))
client_boq_item_assumptions(set_id, rev, full_ref, assumption_json, basis, badge,
                            source_part_id, source_page, updated_by, updated_at,
                            PRIMARY KEY (set_id, rev, full_ref))
```

The operative revision is **derived** as `MAX(rev)`, never stored as a flag — the same rule
`store.load_parts()` uses, for the same reason: a stored flag can drift out of step with the rows.

Rates and assumptions are keyed **per revision**, so pricing Rev 2 leaves Rev 1's prices intact. Locked
decision 6: nothing is ever destroyed.

`source_part_id` / `source_page` point at a drawing already in the set, so an assumption cites its
evidence exactly as a departure cites a clause, and `GET /ingest/parts/{sid}/{pid}/page/{n}.png` renders
it without a new endpoint.

### 4.3 The assumption

```python
class ConditionShare(BaseModel):
    label: str            # "soil, 0-20m, Class A"
    qty: float            # metres in this condition
    output: float         # metres per shift here
    crew_ref: str         # a rate_id
    plant_ref: str
    shift_hours: float = 8.0

class ItemAssumption(BaseModel):
    full_ref: str
    conditions: list[ConditionShare]
    basis: str            # free prose: why you believe this
    badge: str            # "ai" | "user"
    source_part_id: str
    source_page: int
```

`Σ condition.qty` must equal the item's quantity. Checked, never normalised — a mix that does not add up
is a mistake, and silently scaling it would hide the mistake behind a plausible rate.

---

## 5. The costing model

### 5.1 The two layers

The resource → cost engine already in `estimate/s03_cost_buildup.py` is correct and is reused unchanged.
What is added is a layer below it (where the resource quantities come from) and a step above it (the
division that yields a rate).

**Worked example — Bill 2 item 2.4, 2,300 m of soil drilling.**

Assume the mix:

| condition | metres | output | shifts |
|---|---|---|---|
| soil, 0–20 m, Class A | 1,800 | 12 m/shift | 150.0 |
| soil, 0–20 m, Class B | 300 | 8 m/shift | 37.5 |
| soil, 20–40 m, Class A | 200 | 6 m/shift | 33.33 |
| | **2,300** | | **220.83** |

`production.expand()` turns that into resource lines the existing engine costs:

```
crew   220.83 shifts × 8 h = 1,766.64 h   @ LAB-03
rig    220.83 shifts                      @ PLT-11
```

`s03_cost_buildup.build_cost()` prices them exactly as it does today. Then:

```
unit_rate = money(activity_total / qty)          # ← the number the tender asks for
amount    = money(qty * unit_rate)
```

Change one output figure and you can see precisely what it does to the rate. That is the point: the
assumption is the estimate, so the assumption is what must be editable and visible.

### 5.2 Lump items

For `lump` items (`unit` = `item` or `sum`, quantity `'-'`) the build-up total **is** the amount and
there is no rate. The SMM says so:

> **Corrigendum 1/2007, Part III ¶3** — "If it is intended that an item of work is to be paid as a lump
> sum, 'item' shall be used as the unit of measurement … The symbol '-' shall be inserted against the
> rate and quantity columns … Notwithstanding the above, **the amount inserted by the tenderer … shall be
> deemed to be the rate** inserted against such item of work."

Payment is by instalment, not on completion:

> **SMM S01 ¶1.01A** — "payment against those items in this Section where the unit of measurement is
> 'item' shall be made **by monthly instalments at rates to be determined by the Project Manager**."

### 5.3 The spread pool

Costs that must be carried but have no bill item (§2.4) go into a pool and are allocated across the
priced items pro-rata on value. The allocation is stored per item so the trace is visible, and the
rounding residue lands on the largest-value item and is **named**, not absorbed.

After allocation, `Σ extensions == total cost × (1 + margin) ` to the cent.

*What belongs in the pool* is not decided by this build — §7 defers it to an AI-augmented reading of the
preambles. The mechanism ships now; the checklist that fills it comes next.

### 5.4 Rounding

Unchanged: `estimate.money()` — `round(x, 2)`, half-to-even, applied at every step so displayed lines
re-add by hand.

---

## 6. The checks

Each guard enforces a clause, and each carries that clause in its message so the flag explains itself.

| check | enforces | why it matters |
|---|---|---|
| `unpriced_item` | GP ¶6 · GCT App C 2.2(iii) | a blank rate becomes a **zero rate you are bound to**, permanently. The most expensive available mistake, and it looks like nothing |
| `pre_priced_mismatch` | GCT App C 2.2(vi) | Bill 9 and item 8.2 are the client's figures; altering them gets them reinstated anyway |
| `extension_error` | GCT App C 2.2(i) | the examiner recomputes every extension and page cast |
| `casting_error` | GCT App C 2.2(i), 2.3 | page → collection → bill total → (A) must agree |
| `provisional_sum_altered` | GCT App C 2.5 | (B), (D), (E) are reinstated if wrong |
| `erratic_pricing` | GCT 14 | *"the Client may regard a tender as not being the most advantageous, irrespective of whether or not it is the lowest"* |
| `fee_percentage_out_of_range` | SCT 19 · App C 2.4 | omitted or out of range is corrected to the **minimum**, and it feeds the evaluation total |

A check surfaces; it never blocks and never edits. The one thing that blocks is the re-price gate (§7.2).

---

## 7. Buckets

In the format of `client_boq_layer_mapping.md`. **Det** deterministic · **Rule** a coded rule ·
**AI** a model proposes · **Gate** a human decides.

| step | bucket | where |
|---|---|---|
| read the workbook into items | Det | `boq/reader.py` |
| report every anomaly instead of guessing | Det | `reader.py` `notes` |
| diff two revisions incl. the caption chain | Det | `boq/diff.py` |
| carry rates forward | Rule | `boq/carry.py` (GCT App C 2.2(v)) |
| decide a carried rate is still right | **Gate** | the re-price worklist |
| the condition mix | **Gate** (typed) → AI later | `boq/production.py` |
| expand a mix into resources | Det | `production.py` |
| price resources against the rate book | Det | `estimate/s03_cost_buildup.py` *(existing)* |
| unit rate, spread pool, roll-up | Det | `boq/pricing.py` |
| the seven guards | Rule | `boq/checks.py` |
| what goes in the spread pool | **AI later** | reads the preambles, proposes a checklist |
| draft a condition mix from the drawings | **AI later** | the vision path, into `ItemAssumption` |

### 7.1 The one principle, unbent

> The LLM reads, structures, proposes, and drafts — it never writes a decision value.

**No model call exists anywhere in this build.** Every file is deterministic, which is exactly what makes
the whole thing testable offline. When a model is added later it will propose an `ItemAssumption` or a
spread-pool line; it will never write a rate.

### 7.2 The gate

Mirroring locked decision 7 — *a revision reopens the verdicts that depended on it* — a bill revision
**reopens the rates that depended on it**. A revision cannot be approved for pricing while any
`needs_review` item is unconfirmed, and the 409 names them.

`needs_review` is raised by `carry.py` where the arithmetic carry is legal but the estimate is now
suspect: a changed description, or a quantity move past a threshold. Carrying a 24-week rate onto a
52-week quantity is *permitted by GCT App C* and *wrong as an estimate*. The rule exists for exactly
the Bill 6 case.

---

## 8. Phases

| phase | contents | state |
|---|---|---|
| **1 — this build** | reader · diff · carry · production · pricing · checks · storage · routes · tests | shipping |
| 2 | the UI: bill grid, build-up panel, revision/re-price worklist | next |
| 3 | write-back into the client's workbook, with byte-level verification and a paste-the-rates fallback | after 2 |
| 4 | AI: the spread-pool checklist read from the preambles; a condition mix drafted from the drawings | after 3 |
| never | take-off from drawings; a model writing a price | locked decision 1; the one principle |

Backend before UI because the logic is provable in tests and the screen is not — this repo has no
frontend test runner at all.

---

## 9. Risks

**openpyxl round-trip on Bill No.4.** 9,963 merged ranges and ~76,500 stray cells; `MemoryError` on Rev 2
during analysis. Reading is solved by clamping to column H. *Writing* is not, which is why write-back is
phase 3 with its own verification pass rather than a footnote here. If round-trip proves unsafe, the
fallback is a rates-to-paste sheet — worse, but honest.

**Item-ref collisions.** Handled by rendering through `number_format`, but the formats are manually and
inconsistently assigned in the source (`Bill No.4` alternates `General` and `'0.00'` arbitrarily between
items 4.16 and 4.26). Any ref that survives formatting as a bare float is recorded in `notes`.

**Scale.** 166 items is small. A building contract runs to thousands, and there is no virtualised list in
the frontend. A phase-2 concern, noted now.

**The synthetic fixture is not the real file.** Tests run against a generated workbook reproducing each
measured trap; an optional test runs against the real ND/2025/04 workbooks when present on disk and skips
otherwise. Client tender data does not enter the repo.

**The mix is a guess, and the app must not make it look like a measurement.** `basis` is free prose and
required to be worth reading; the badge and the drawing citation exist so it is always clear this is
someone's judgment, not a fact extracted from a document.

---

## 10. What this does not do

- **Measure anything off a drawing.** Locked decision 1. The client counts the quantities; we split a
  quantity we were given.
- **Read the drawings.** GI/100's test-quantity table and GI/210 / GI/310's coordinate tables are exactly
  what `documents.to_images` plus the vision route handle, and would give a first draft of the mix.
  `production.expand()` takes an `ItemAssumption` as an argument, so that proposer slots in front of it
  without reshaping storage — the same seam `s02_schedule.py` left. Deferred: a proposer with nothing to
  propose into cannot be tested.
- **Catch a specification change that costs money without touching the bill.** TA1 ¶12 added *"the
  vegetation survey must be carried out by a qualified ecologist"* — new staffing cost against BQ item
  1.63, whose quantity never moved. Genuinely hard, and the natural sequel to the spread-pool reading.
- **Write into the client's workbook.** Phase 3.
- **Track addendum acknowledgement**, required by GCT 15 and a tender-box checklist item at NTT A5(1)(b).
  Small, unbuilt.
