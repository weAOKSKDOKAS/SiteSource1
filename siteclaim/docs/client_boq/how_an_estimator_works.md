# How an estimator actually works

A walkthrough of one real tender, from drawings to a submitted price — the flow `estimating_process.md`
describes in the abstract, done concretely on CEDD contract ND/2025/04 (San Tin Technopole Phase 2,
Ground Investigation Works).

Every figure below is read out of the issued documents. Where something is inference rather than fact,
it says so.

---

## 0. The question that reshapes everything: who owns the quantities?

`estimating_process.md` lists it almost in passing, under Terms of the Offer — *"Who owns the
quantities (client BOQ vs contractor take-off)"*. It is not a detail. It decides what you do for the
next three weeks and which risks you carry.

| | **Route A — the client measured** | **Route B — you measure** |
|---|---|---|
| you receive | a bill of quantities, already itemised and counted | drawings and a specification |
| you produce | rates against a fixed list | quantities **and** rates |
| quantity risk | the client's (if remeasured) | **yours** |
| rate risk | yours | yours |
| the mistake that kills you | a wrong rate, repeated across every unit | a missed quantity, unpaid forever |
| Technopole | **this one** | — |

Technopole is Route A under **NEC Main Option B** — a priced contract with bill of quantities,
remeasured. That combination has a specific consequence people get backwards:

> The bill quantities are the client's *estimate*. Work is remeasured as actually built and paid at
> **your tendered rates**. So if the client says 2,300 m and it turns out to be 4,000 m, you are paid
> for 4,000 m. Quantity risk is genuinely theirs.
>
> **But your rate is fixed for the life of the contract.** Get it wrong and you are now wrong 4,000
> times instead of 2,300. Remeasurement does not reduce rate risk — it *amplifies* it.

So on Route A the estimator's whole job collapses to one thing: **get the rates right**, and put them
in the right places.

---

## 1. The chain: drawings → rules → take-off → BOQ

This is the part you asked about, and it has four links, not two.

```
  DRAWINGS                 what and where          GI/000-016 working areas
     │                                             GI/200-205, 301-303 every station + coordinates
     │                                             GI/100 termination criteria, tentative test counts
     ▼
  SPECIFICATION            to what standard        PS7 geotechnical, PS31 lab, PS1 general
     │
     ▼
  METHOD OF MEASUREMENT    how to slice it into    SMM 1992 + General Preambles
  (the SMM + Preambles)    billable items          + Particular Preambles Section 2
     │
     ▼
  TAKE-OFF                 measure per the rules   dimension → timesing → squaring → abstract
     │
     ▼
  BILL OF QUANTITIES       the finished list       9 bills, 166 items, Grand Summary
```

**The middle link is the one people skip, and it is the one that does the work.** Drawings do not
produce a bill. *Rules applied to drawings* produce a bill. Two quantity surveyors measuring the same
drawing under different rules produce different bills — which is exactly why a standard method exists.

### The grammar: how a rule becomes an item description

The SMM gives each work section a **Group Feature table**. Section 2's drilling items use:

| Group | Features |
|---|---|
| III | hole or core size — "Drilling size H or N" |
| IV | 1. material other than rock, boulder or artificial hard material · 2. rock · 3. artificial hard material and boulder |
| V *(added by Addendum No. 1)* | 1. "In first stage of drillhole not exceeding 20m in length" · 2. "In second stage … exceeding 20m but not exceeding 40m **and so on in stages of 20m**" |

and one rule governs how they combine (Part II General Principles ¶3, as replaced by Corrigendum
1/2007):

> "Each item description used in the Bills of Quantities is to be **consistent with and be compounded
> from one or more of the descriptive features listed in the itemisation groups** in the various
> sections of Part V, as many of these groups or features being used as may be necessary to identify
> the work required, **but not more than one feature from any one group** may be represented in any one
> item description."

So the item

> **2.4** *Drilling size H or N · vertically downwards · material other than rock, boulder or
> artificial hard material* — **2,300 m**

is literally one feature from Group III plus one from Group IV. The groups define the *possible*
items; the take-off decides which ones actually exist and how much of each.

**That is the whole answer to "how does take-off become a BOQ".** You measure each hole, tag every
metre with its group features (what size, what material, what depth band, which class of site), then
sort and total by tag. Each distinct combination that has a non-zero total becomes a line.

### Where the scope enters

The take-off gives you the *quantity*. It does not give you the *obligation*. That comes from the
Scope, and the Preambles say so in terms:

> **General Preambles ¶2** — "The exact nature and extent of an item of work **must be ascertained by
> reference to the Drawings and Specification**, and to the conditions of contract, as not all
> requirements may be stated in the item description or its item coverage … the item of work described
> is deemed to include for all requirements shown on all Drawings and/or Specification pertaining to
> that item of work **irrespective of whether or not the Drawing and/or Specification is stated** in
> the item description or item coverage."

So "a metre of drilling" is not a metre of drilling. Reading Section 2's item coverage, one metre of
item 2.4 is really:

> a metre of **logged, stabilised, cased, traffic-managed** drilling, *including* reaming of casing,
> disposal of surplus material, taking and submitting the routine small disturbed samples, taking
> readings, and supplying the logs and records of the hole.

Price the metre and forget the logging, and you have priced 60% of an item you are contractually bound
to deliver in full.

---

## 2. What an estimator actually does, in order

Ten stages. `estimating_process.md` has six; the four extra ones are the ones that only show up when
you watch someone do it for real.

### Stage 0 — bid / no-bid

Before anyone opens a drawing. Do we want it, can we resource it, who else is bidding, what is our
appetite. This is `estimating_process.md` §2.2 — and it is a *decision*, minuted, not a mood.

### Stage 1 — read the contract, not the drawings

Counter-intuitive, and universal among good estimators. The first documents open are the conditions of
tender and the preambles, because **those decide what a rate must carry** and there is no point
measuring anything until you know that.

What you extract on Technopole, in about half a day:

| finding | where | why it matters on day one |
|---|---|---|
| Option B, remeasured | CDP1 | quantity risk is the client's; rate risk is yours, forever |
| 31 heads deemed included in every rate | GP ¶2 (i)–(xxii) + PP ¶¶7–10 | most of your cost has no line to sit on |
| "Any item missed out from the item coverage **shall not be measured**" | PP ¶12 / ¶4A | there is no later claim for a forgotten cost |
| unpriced item = deemed covered by the other rates | GP ¶6 | a blank cell is free work, permanently |
| Bill 9 pre-priced at HK$429,810 | BQ | you cannot compete on safety; do not touch it |
| fee percentage floored and capped | SCT 19 | and it is **price-scored** — see §3.4 |
| queries close 7 days before tender | SCT 23 / NTT A4 | your query window is shorter than the tender |
| alteration → disqualification; qualification → disqualification; editing a locked cell → qualification | GCT 6, GCT 9, App A ¶10 | how to lose without being outbid |
| change is valued at Defined Cost + fee, not bill rates | NEC core | there is no daywork bill and no provisional-sum bill here |

### Stage 2 — the scope read, and the query list

Now the Scope, the Particular Specification and the drawings. Everything ambiguous becomes one of two
things: **a query** (if there is time) or **a priced assumption** (if there is not).

Queries are a commercial instrument, not admin. On Technopole, 24 questions went out across two
clarification rounds. Three outcomes, all of them money:

- **A cost removed.** TC1 Q9 asked whether the comprehensive utility survey in PS 1.67 was really
  required. Addendum No. 1 changed that clause to "Not Used" — a whole survey deleted from scope
  because somebody asked.
- **A cost confirmed.** TC1 Q4 argued the Contractor designs nothing, so Category I/II/III geotechnical
  supervision should not apply. Refused: *"the Contractor shall propose his site supervision plan …"*
  That is now a known, priced cost rather than a discovered one.
- **A cost created.** TC1 Q13 asked what qualifications the vegetation-survey ecologist needed. The
  answer added PS 25.31(4) requiring a **qualified ecologist** — new staffing cost, against a bill item
  whose quantity never moved.

That last one is worth sitting with. **A scope change can raise your cost without touching a single
number in the bill.** Nothing in a quantity diff would ever show it.

### Stage 3 — take-off, or *reverse* take-off

Route B: you measure everything. Route A (Technopole): the measuring is done, so you do the opposite —
you **de-aggregate**, reconstructing what the client's single numbers are made of, because you cannot
price 2,300 m without knowing what shape it is. §3 below does this on the real figures.

### Stage 4 — method and programme, **before** pricing

You cannot rate an item until you know how you will do the work: how many rigs, what type, crew size,
shift pattern, sequence, access.

This is the step most descriptions omit, and it is load-bearing, because:

> **The programme and the estimate are the same calculation done twice.**

Drilling output → shifts → rigs → weeks on site → duration → and duration is what the time-related
preliminaries are priced on. Directs drive duration; duration drives indirects. That is why
`estimating_process.md` puts indirects at Step 4, *after* the cost build-up.

On Technopole you can check your programme against the client's, because theirs is legible in the bill
(§3.3).

### Stage 5 — the cost build-up

For each item: gang, plant, materials, output → cost per unit.

```
resources                     →  hours / shifts  →  ×  all-in rates  →  cost  ÷  quantity  =  RATE
```

The two inputs that are genuinely yours — nobody else in the market has them — are your **outputs**
(how fast your crews actually work) and your **all-in rates** (what a crew-hour really costs you once
on-costs are in). Everything else is arithmetic.

### Stage 6 — preliminaries and indirects

Split by how they behave over time, not by what they are:

- **fixed / one-off** — set-up, take-over, dismantling. Technopole bills these as unit `item`.
- **time-related** — running costs. Technopole bills these as `mth`, `wk`, `nr-wk`, `nr-mth`.

With a sting specific to this contract: even the fixed `item` charges are **not** paid on completion —

> **SMM S01 ¶1.01A** — "payment against those items in this Section where the unit of measurement is
> 'item' shall be made **by monthly instalments at rates to be determined by the Project Manager**."

So you cannot front-load your set-up cost to fix early cash flow. That is a financing cost you carry.

### Stage 7 — risk, and the spread

Two different things, often confused.

**Risk allowance** is money against identified, uncertain events — you keep a register, you price the
ones you are carrying, you note the ones you are qualifying out.

**The spread** is money against *certain* costs that have nowhere to go. Site uniform (PP ¶11/¶2A:
*"There shall be no measurement or separate payment"*), the Subcontractor Management Plan (NTT C2), Pay
for Safety to subcontractors (NTT C25). These are real costs with no bill line, and they must be
buried inside other rates. Forget them and you have simply lost the money.

### Stage 8 — review, then **settlement** (two different meetings)

`estimating_process.md` Step 5 covers the first. In a real contractor there are two:

- **The technical review** — scope coverage, arithmetic, quantity sense-checks, rate benchmarking
  against your own completed jobs. Estimator-led. Produces a defensible **cost**.
- **The settlement / adjudication meeting** — directors. Margin, risk appetite, market read, how badly
  we want it. Produces a **price**.

The distinction matters: **the estimator produces a cost; management produces a price.** When the
number gets cut to win the job, that is a commercial decision taken with eyes open — not an estimating
error, and it should never be smuggled back into the rates as optimism.

### Stage 9 — commercial shaping

Now that you know the total, decide *where* to put it. Under remeasurement this is a real skill:

- a quantity you believe will **increase** → load the rate (more units, at more each)
- a quantity you believe will **decrease** → shave the rate, and move that money onto the increasing
  items

The total is unchanged; the outcome is not. GCT 14 polices the extreme version — "erratic pricing"
that is *"significant and unjustified"* — and lets the client set aside even the lowest tender for it.
So this is played within limits, and the limits are written down.

You can see a tenderer doing exactly this on Technopole. TC1 Q11 **and** Q17 both challenged BQ item
3.6's 65 m³ of inspection pits as too large for 9 environmental holes. The answer both times was
*"considered appropriate"*. That tenderer now believes an over-measured item is in front of them —
under remeasurement they will be paid for what they actually dig — so the correct play is to **shave
3.6 and load elsewhere.** Asking twice was not pedantry; it was building a commercial position.

### Stage 10 — submission

Fill **their** Excel (GCT App A ¶9–10, and do not touch a locked cell), the Form of Tender, Contract
Data Part two, the fee percentage, the JV proforma if applicable, and the acknowledgements for every
addendum. Then check the arithmetic, because:

> **GCT App C 2.1** — *"Under no circumstances can the tendered rates be changed."*

The examiner will recompute every extension and every page cast (App C 2.2(i)) and carry the corrected
figures up. Your rates stand as typed, errors and all.

---

## 3. Reading the client's mind out of their own bill

This is the part that separates estimators. The bill is not just a list — it is a **record of the
client's assumptions**, and you can recover them with division.

### 3.1 How many holes, and how deep

Moving rigs is measured per hole:

> **SMM S02 ¶2.03** — "The measurement for moving rigs shall correspond to **the number of boreholes,
> drillholes and probeholes** shown on the Drawings or ordered by the Project Manager."

and the bill says:

```
2.2a  Moving rigs, in Class A of site      80 nr
2.2b  Moving rigs, in Class B of site      11 nr
                                        ───────
                                           91 holes
```

Total drilling: 2,300 + 600 + 100 = **3,000 m**. So:

```
3,000 m ÷ 91 holes  =  33.0 m average hole depth
```

Nobody wrote 33 m anywhere. It is the single most useful number for pricing this job, and it fell out
of two lines of the bill.

Cross-checks that agree: standing time 455 h ÷ 91 = **exactly 5.0 hours per hole** (a designed
allowance, not a coincidence). Samples from drillholes 1,138 + 104 + 272 + 8 = 1,522 ÷ 91 ≈ **17 per
hole**.

### 3.2 The client's ground model, and whether you believe it

```
material other than rock  2,300 m   77%
rock                        600 m   20%
artificial hard material    100 m    3%
```

and in the pits: 187 m³ of trial and inspection pits, with 17 m³ "extra over for excavation in rock"
and 17 m³ "extra over … in artificial hard material" — i.e. **9% each**.

**That is the client's geological assumption, stated in money.** Your own view comes from the borehole
logs of **14 past investigations** disclosed in the Site Information. If you read those and conclude
the site is 35% rock, not 20%, then under remeasurement the rock metres will overrun and the soil
metres will fall short — and Stage 9 says load 2.5, shave 2.4. Same total, different outcome.

This is the single clearest illustration of the whole chain: *scope → drawings → measurement rules →
bill → your reading of the ground → your rates → remeasurement → money.*

### 3.3 The programme, hiding in the units

```
Bill 1  Project Manager's Site Office, Servicing        28 mth
Bill 1  Smart Site Safety System components             20 mth  (a run of them)
Bill 1  Servicing of core and sample store              87 wk   ≈ 20 months
Bill 6  recording, per instrument                       52 wk   (see below)
```

The recurring **20 months** is the client's assumed working period; the 28-month PM office is the
longer envelope around it. So: build your own programme from your own outputs, then compare. **If your
programme says 26 months, you are being paid 20 months of preliminaries.** That gap is either a
qualification, a query, or six months of unpaid site management.

### 3.4 What Addendum No. 1 actually did to Bill 6

```
                        Rev 0            Rev 1
6.1 standpipes  47 nr   1,128 nr-wk  →   2,451 nr-wk    ÷ 47  =  24.0 wk  →  52.1 wk
6.2 piezometers 68 nr   1,623 nr-wk  →   3,546 nr-wk    ÷ 68  =  23.9 wk  →  52.1 wk
6.3 AGMD       115 nr   2,760 nr-wk  →   5,996 nr-wk    ÷ 115 =  24.0 wk  →  52.1 wk
```

Divide and it is unmistakable: **six months of monitoring per instrument became twelve.** It is the
answer to TC1 Q2 — *"The monitoring work shall last for at least 12 months after installation of the
piezometer/standpipes"* — arriving as a quantity change rather than as a sentence.

The addendum described all of that as: *"Updated the quantities of item nos. 6.4 – 6.6."*

And note what it does to your *programme*, not just your price: 230 instruments monitored for a year
each, with recording measured only **after the completion date** (S02 ¶2.28A as amended by TA1). Your
site presence now outlives your drilling by a year.

### 3.5 One thing that does not add up — and what an estimator does with it

Addendum No. 1 **added Group V to the Section 2 Group Feature table**: drilling is to be itemised by
depth stage, in 20 m bands measured from existing ground level (¶2.11A).

But the operative Rev 2 bill still prices drilling as three single lines — 2.4, 2.5, 2.6 — with **no
depth-stage split at all**. And §3.1 puts the average hole at 33 m, so most holes cross the 20 m
boundary and a second stage genuinely exists.

Deep metres are slower metres. So either every metre is deemed first-stage (one blended rate covers
everything — workable, and you must price the blend, not the shallow case), or the measurement rules
and the bill disagree, and at remeasurement there could be a stage the bill has no rate for.

The honest reading is that GP ¶3 says features are used "as may be necessary", so aggregating is
defensible — but TA1 deliberately *added* the depth group, which points the other way.

**What an estimator does with it:** raise it as a query before the deadline, and if the answer is
unsatisfactory, price the blended average across the depth profile and record the assumption in the
qualifications. What they do **not** do is price the easy first 20 m and hope.

That is the whole discipline in one example: read the rules, read the bill, notice they disagree, and
turn the disagreement into either an answer or a stated assumption — never a silent hope.

---

## 4. Five distinct ways scope moves the price

Worth separating, because they behave differently and only one of them is visible in a bill diff.

1. **Scope decides which items exist.** PS7 → Bills 2/3/6. PS31 → Bills 4/5. PS27 → Bill 9. Change the
   specification section and lines appear or vanish.
2. **Scope decides what a rate must cover** beyond the item text (GP ¶2). Same quantity, more
   obligation, higher rate.
3. **Scope creates cost with no item at all** → the spread (PP ¶4A, NTT C2/C14/C25).
4. **Scope drives duration, and duration is priced** — the `mth` and `nr-wk` items. Extend the works
   and the time-related preliminaries follow; §3.4 is exactly this.
5. **Scope can change without the bill changing.** TA1's qualified-ecologist requirement added staffing
   cost against an item whose quantity never moved. **No quantity diff will ever show this** — you have
   to read the specification revision.

---

## 5. The terminology, and what each term does to your money

Grouped by the job each does, not alphabetically.

### Measuring

| term | what it means | what it does to you |
|---|---|---|
| **Take-off** | measuring quantities off drawings, per the rules | on Route B it is yours and a miss is unpaid; on Route A it is done |
| **Method of Measurement / SMM** | the published rulebook for slicing design into billable items | makes tenders comparable, and settles "was that in the rate?" by rule instead of argument |
| **Preambles** (General / Particular) | this contract's amendments and additions to the SMM | where the deemed-inclusions live; **Particular beats General beats SMM** |
| **Item coverage** | the SMM's list of what an item includes | expressly **not** exhaustive here (¶2, ¶4A) — treat it as a floor, never a ceiling |
| **Deemed to be included** | in the rate whether or not it is mentioned | 31 heads on this job, ending at *"establishment charges, overheads and profit"* |
| **Net measurement** | quantities computed net off the drawing, no waste added | waste, bulking and shrinkage go in the **rate** (GP ¶2(viii)), not the quantity |
| **Remeasurement** | recounting as actually built, paid at tendered rates | quantity risk moves to the client; rate risk stays with you for the whole job |
| **Extra over** | the *difference* only, on work already measured | 17 m³ "extra over for rock" is inside the 187 m³, not additional to it — price the increment, not the whole |

### The bill's own furniture

| term | what it means |
|---|---|
| **Item / Sum** | a lump-sum item: quantity and rate print `-`, only the Amount is priced. "The amount inserted … shall be deemed to be the rate" |
| **Extension** | quantity × rate = amount, per line |
| **Casting** | adding a page up |
| **Collection** | the page that gathers a bill's page totals ("Brought Forward from Page BQ/2/1") |
| **Grand Summary** | where bill totals become the tender total (A) |
| **Rate / Amount / Price** | rate is per unit; amount is one line's extension; **the Prices** is the NEC term for the whole priced bill |
| **Preliminaries** | Bill 1 — the cost of *being there* rather than of doing the work |

### Money the client put there

| term | who prices it | on this job |
|---|---|---|
| **Pre-priced item** | the client | all of Bill 9 (HK$429,810, Pay for Safety) and item 8.2. Alter one and it is reinstated (App C 2.2(vi)) |
| **Contingency sum** | the client | (B) HK$4,342,620 — **expressly not part of the contract** (ACC II:4) |
| **Provisional sum** | the client | (D) inflation HK$1,550,000, (E) safety incentive HK$609,370 — likewise outside the contract |
| **Provisional quantity** | — | **not used on this job** |
| **Prime Cost (PC) sum** | — | **not used on this job**; no PC bill, no nominated subcontractors |
| **Dayworks** | — | **not used on this job** — Particular Preamble ¶2 deletes the SMM's own definition. Change is a compensation event instead |

That last row matters more than it looks: with no dayworks and no provisional sums to price change
against, **the only priced mechanism for change on this contract is your fee percentage.**

### NEC vocabulary you cannot price without

| term | meaning | consequence |
|---|---|---|
| **Option B** | priced contract with bill of quantities, remeasured | §0 |
| **Compensation event** | the change mechanism | valued at Defined Cost + Fee, *not* at bill rates |
| **Defined Cost + Fee** | actual cost components plus your quoted markup | so the fee percentage is your entire margin on all change |
| **Fee percentage** | Contract Data Part two, floored and capped by SCT 19 | and it is **price-scored**: Grand Summary (C) = (B) × your fee %, feeding (F) → (G), and (G) is what the 60-point price score uses. A fat fee percentage hurts your ranking without changing your contract price. Omit it and App C 2.4 corrects it **to the minimum** |
| **Scope** (NEC) / Works Information | what to provide and how | the source of every deemed inclusion |
| **Site Information** | what is known about the ground | the baseline for "worse than expected" claims — and your evidence for §3.2 |

### Yours, and nobody else's

| term | meaning |
|---|---|
| **Output / production rate / constant** | how much your gang does per shift. The number that actually differentiates two bidders |
| **All-in rate** | true cost of a labour hour: wage + on-costs, insurance, leave, travel, welfare, supervision share |
| **Gang / crew** | the priced team — 1 driller + 2 labourers, not "labour" |
| **Direct cost** | traceable to an item: labour, plant, materials, subcontract |
| **Indirect cost** | not traceable to one item: supervision, temporary works, overheads, risk |
| **Loading / front-loading / unbalanced bid** | putting the same total in different places for cash-flow or remeasurement advantage — legitimate until GCT 14 says otherwise |
| **Class of estimate / variability** | the ± band around the number. A tender estimate is not a feasibility estimate, and two identical prices can carry very different confidence |
| **Adjudication / settlement** | the meeting where cost becomes price |
| **Qualification** | a stated departure from the tender terms. On this job *"may cause the tender to be disqualified"* (GCT 9) — so it is a last resort, not a habit |

---

## 6. One item, priced both ways

**Bill 2 item 2.4 — drilling size H or N, vertically downwards, material other than rock, 2,300 m.**

### Route B — if we had to produce the quantity ourselves

```
1. read GI/201-205, list every station                      91 boreholes
2. read GI/100 for termination criteria                     how deep each goes
3. per hole, tag each metre by Group III/IV/V features       size, material, depth band
4. abstract and total by tag                                 2,300 m soil · 600 m rock · 100 m AHM
5. write the description from the group features             the item text above
```

The client's QS did exactly this, and then discarded the working — which is why step 3's tags are
invisible to you, and why Route A starts by rebuilding them.

### Route A — pricing the 2,300 m we were handed

```
1. reconstruct the shape          91 holes, 33 m average (§3.1)
                                  77% soil, and the depth profile crosses 20 m (§3.2, §3.5)
2. choose a method                rotary rig, 1 driller + 2 labourers, 8-hour shift
3. state the mix, and defend it   from the drawings and the 14 historical logs
```

| condition | metres | output | shifts |
|---|---:|---:|---:|
| soil, 0–20 m, Class A | 1,800 | 12 m/shift | 150.00 |
| soil, 0–20 m, Class B (poor access) | 300 | 8 m/shift | 37.50 |
| soil, 20–40 m, Class A (deeper is slower) | 200 | 6 m/shift | 33.33 |
| | **2,300** | | **220.83** |

```
4. resource it     crew  220.83 × 8 h = 1,766.64 h @ 850   = 1,501,644
                   rig   220.83 shifts          @ 3,200    =   706,656
                                                      cost = 2,208,300
5. add the spread  this item's share of the no-line costs
6. add margin      cost × 1.15
7. DIVIDE          2,539,545 ÷ 2,300 m       =  HK$1,104.15 per metre
```

Step 7 is the step the software did not previously have, and step 1 is the step it had nowhere to
record. Everything between them was already arithmetic.

**Sanity check before it goes anywhere:** 2,300 m ÷ 220.83 shifts = **10.4 m a shift blended**. If
nothing your rigs have ever done on this ground beat 9 m a shift, the mix is wrong — and you know that
before you look up a single rate.

---

## Where this lands in the app

| stage above | in the software |
|---|---|
| 1 — read the contract | REVIEW: `s01`–`s08`, the departure register, the human gate |
| 2 — scope read and queries | the RFI loop; the scope of record and its freeze gate |
| 3 — reverse take-off | `boq/reader.py`, then `ItemAssumption` (the condition mix) |
| 4 — method and programme | **not built.** Duration is a typed number, not a derived one |
| 5 — cost build-up | `boq/production.py` → `estimate/s03_cost_buildup.py` → `boq/pricing.py` |
| 6 — preliminaries | priced as ordinary bill items, because on this job that is what they are |
| 7 — risk and the spread | `SpreadLine`; *what belongs in the pool* is still a human's list |
| 8 — review, settlement | `boq/checks.py` for the technical half; the settlement is a meeting, not a feature |
| 9 — commercial shaping | **not built.** `erratic_pricing` marks the boundary, nothing helps you play inside it |
| 10 — submission | the letter and companion documents; **write-back into the client's workbook is not built** |

The honest summary: the app is strong on stages 1–2, now has a spine for 3 and 5, and does nothing for
4, 9 and the second half of 10.
