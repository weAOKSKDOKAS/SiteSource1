"""BOQ — price the bill: build-up to unit rate, the spread pool, and the roll-up.

Bucket: **Deterministic**. The resource arithmetic is not reimplemented here — it is
``estimate/s03_cost_buildup.build_cost``, unchanged, which already resolves an inline rate over the
book, converts by productivity, prices a missing rate at zero and marks it. What this module adds is
the two things a bill needs that a flat schedule did not:

**A rate per unit.** ``CostActivity`` gives a total. The box on the government's form wants a rate,
and under NEC Main Option B that rate is what every remeasured metre is paid at for the life of the
contract. So the last step is a division the app has never done.

**The spread pool.** General Preambles 2 lists 22 heads of cost every rate is deemed to include;
Particular Preambles 7-10 take it to 31; and 4A sweeps up the rest — "Any item missed out from the
item coverage shall not be measured". Several costs are then given no bill line at all and ordered
into the rates by name: site uniform (PP 11/2A, "There shall be no measurement or separate payment"),
the Subcontractor Management Plan (NTT C2), Pay for Safety to subcontractors (NTT C25). Those costs
are real, they are yours, and there is nowhere to put them except inside other rates. So they go in a
pool and are spread across the priced items pro rata on value, and the allocation stays on the item
where it can be seen.

TWO ROUNDING FACTS, BOTH DELIBERATE
-----------------------------------
1. The spread is allocated to the cent, and whatever will not divide lands on **one named item**
   (``spread_residue_ref``). Absorbing it invisibly across every rate would make the pool total
   disagree with the sum of its own allocations by a few cents, which is the kind of discrepancy
   that costs an hour to find.

2. ``tendered_total`` is the sum of the **extensions**, not the sum of the costs. Once a rate is
   rounded to the cent, quantity times rate is no longer exactly the cost that produced it — and it
   is the extension that is contractual. GCT Appendix C 2.2(i) has the examiner recompute every
   extension and page cast from the rates as submitted, and 2.1 forbids changing a rate to make the
   arithmetic tidier. So the figure carried to the Form of Tender is what the rates actually produce.
"""

from __future__ import annotations

from typing import Optional

from client_boq import rates as rates_mod
from client_boq.estimate import money
from client_boq.estimate.s03_cost_buildup import build_cost
from client_boq.models import (
    BillItem,
    ClientBill,
    CostLine,
    EstimateFlag,
    EstimateSchedule,
    PricedBill,
    PricedItem,
    RateRow,
    ScheduleItem,
    SpreadLine,
)

RATE_BUILT = "built"        # priced from a resource build-up
RATE_CARRIED = "carried"    # carried across a revision, not rebuilt
RATE_CLIENT = "client"      # the client's own figure; not ours to price
RATE_UNPRICED = "unpriced"  # nothing behind it — General Preambles 6 territory


def _allocate(items: list[BillItem], costs: dict[str, float], total: float
              ) -> tuple[dict[str, float], str]:
    """Spread ``total`` across the priced items pro rata on their build-up value.

    Returns the per-item allocation and the reference of the item carrying the residue. Pro rata on
    value because the pool is overheads and obligations that scale with the work, and value is the
    only proxy the bill itself supplies — an equal split would load a 1 nr signboard the same as
    2,300 m of drilling.
    """
    if total <= 0:
        return {}, ""
    priceable = [i for i in items if not i.is_parent and not i.pre_priced]
    base = money(sum(costs.get(i.full_ref, 0.0) for i in priceable))
    if base <= 0:
        return {}, ""

    allocation: dict[str, float] = {}
    for item in priceable:
        cost = costs.get(item.full_ref, 0.0)
        if cost > 0:
            allocation[item.full_ref] = money(total * cost / base)

    if not allocation:
        return {}, ""
    residue_ref = max(allocation, key=lambda ref: allocation[ref])
    residue = money(total - money(sum(allocation.values())))
    if residue:
        allocation[residue_ref] = money(allocation[residue_ref] + residue)
    return allocation, residue_ref


def price_bill(
    bill: ClientBill,
    build_ups: dict[str, ScheduleItem],
    *,
    rates: Optional[list[RateRow]] = None,
    spread: Optional[list[SpreadLine]] = None,
    margin_pct: float = 0.0,
    carried: Optional[dict[str, float]] = None,
) -> PricedBill:
    """Price every item of the bill.

    ``build_ups`` maps ``full_ref`` → the resource build-up behind that item (from
    ``production.expand`` or typed by hand). ``carried`` supplies a rate for items priced in an
    earlier revision and not rebuilt. Anything with neither is left **unpriced** — not zero — because
    the two are different facts and only one of them is a decision.
    """
    rate_rows = rates if rates is not None else rates_mod.load_rates()
    spread_lines = list(spread or [])
    carried_rates = dict(carried or {})
    flags: list[EstimateFlag] = []

    # 1. the resource build-up for every item that has one, through the existing engine
    schedule = EstimateSchedule(items=[build_ups[ref] for ref in build_ups])
    activities = {a.item_id: a for a in build_cost(schedule, rate_rows)}
    build_up_cost = {ref: activities[ref].activity_total for ref in activities}

    # 2. the pool of costs with no bill line, spread across the priced items
    spread_total = money(sum(line.amount for line in spread_lines))
    allocation, residue_ref = _allocate(bill.items, build_up_cost, spread_total)

    factor = 1 + margin_pct / 100.0
    priced: list[PricedItem] = []

    for item in bill.items:
        if item.is_parent:
            continue

        lines: list[CostLine] = list(activities[item.full_ref].lines) if item.full_ref in activities else []
        build_up = build_up_cost.get(item.full_ref, 0.0)
        share = allocation.get(item.full_ref, 0.0)
        cost = money(build_up + share)
        source, unit_rate = RATE_UNPRICED, None

        if item.pre_priced:
            # Bill 9 and item 8.2 arrive priced under the Pay for Safety Scheme. Altering them only
            # gets them reinstated (GCT App C 2.2(vi)), so they are carried through untouched.
            source = RATE_CLIENT
            unit_rate = item.client_rate
            amount = item.client_amount if item.client_amount is not None else money(
                (item.qty or 0) * (item.client_rate or 0))
            priced.append(PricedItem(
                full_ref=item.full_ref, bill_no=item.bill_no, description=item.description,
                unit=item.unit, qty=item.qty, lump=item.lump, build_up=0.0, spread=0.0,
                cost=money(amount or 0), unit_rate=unit_rate, amount=money(amount or 0),
                rate_source=source, lines=[],
            ))
            continue

        if item.full_ref in activities:
            source = RATE_BUILT
            priced_cost = money(cost * factor)
            if item.lump:
                # SMM Corrigendum 1/2007 Part III 3: for a lump item "the amount inserted by the
                # tenderer ... shall be deemed to be the rate", and the rate column prints "-".
                amount = priced_cost
            else:
                if item.qty:
                    unit_rate = money(priced_cost / item.qty)
                    amount = money(item.qty * unit_rate)
                else:
                    # A real zero quantity (the reference bill has one: a water sample kept at 0 nr
                    # so a rate exists if one is ordered). It still needs a rate; it earns nothing.
                    unit_rate = money(priced_cost) if priced_cost else 0.0
                    amount = 0.0
        elif item.full_ref in carried_rates and carried_rates[item.full_ref] is not None:
            source = RATE_CARRIED
            unit_rate = money(carried_rates[item.full_ref])
            amount = unit_rate if item.lump else money((item.qty or 0) * unit_rate)
        else:
            amount = 0.0
            flags.append(EstimateFlag(
                kind="unpriced_item", item_id=item.full_ref,
                message=(f"{item.full_ref} has no rate. General Preambles 6: an item against which "
                         f"no rate is entered is 'deemed to be covered by the other rates in the "
                         f"bill of quantities' — it becomes work done for nothing, for the life of "
                         f"the contract"),
            ))

        priced.append(PricedItem(
            full_ref=item.full_ref, bill_no=item.bill_no, description=item.description,
            unit=item.unit, qty=item.qty, lump=item.lump, build_up=build_up, spread=share,
            cost=cost, unit_rate=unit_rate, amount=amount, rate_source=source, lines=lines,
        ))

    # 3. the roll-up: page -> collection -> bill -> (A)
    page_of = {i.full_ref: i.page_ref for i in bill.items}
    page_totals: dict[str, float] = {}
    bill_totals: dict[str, float] = {}
    for entry in priced:
        page = page_of.get(entry.full_ref, "")
        page_totals[page] = money(page_totals.get(page, 0.0) + entry.amount)
        bill_totals[entry.bill_no] = money(bill_totals.get(entry.bill_no, 0.0) + entry.amount)

    return PricedBill(
        set_id=bill.set_id, rev=bill.rev, items=priced, spread=spread_lines,
        spread_total=spread_total, spread_residue_ref=residue_ref,
        bill_totals=bill_totals, page_totals=page_totals,
        total_build_up=money(sum(build_up_cost.values())),
        margin_pct=margin_pct,
        tendered_total=money(sum(entry.amount for entry in priced)),
        flags=flags,
    )
