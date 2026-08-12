"""BOQ — the deterministic guards on a priced bill.

Bucket: **Rule**. Each check enforces a clause of the tender documents and carries that clause in
its message, so a flag argues its own case instead of asking to be believed.

Every one of these is something the tender examiner does to your bid after you have submitted it,
when it is too late to change anything:

    GCT App C 2.1     "Under no circumstances can the tendered rates be changed."
    GCT App C 2.2(i)  extensions and page casts are corrected and carried to the Grand Summary
    GCT App C 2.2(iii) an unpriced item's "rate shall therefore be marked as zero"
    GCT App C 2.2(vi) a pre-priced item a tenderer got wrong "shall be correctly reinstated"
    GCT App C 2.5     an altered contingency or provisional sum is reinstated
    GCT App C 2.4     a fee percentage outside its range is corrected — to the MINIMUM if omitted
    GCT 14            an erratically priced bid may be rejected even if it is the lowest

A check surfaces; it never blocks and never edits. Nothing here decides whether to submit — that is
a person's call, and the only thing in this package that actually blocks is the re-price gate.

THE ONE THAT MATTERS MOST IS THE DULLEST
----------------------------------------
``unpriced_item``. Leaving a rate blank feels like leaving a decision open. It is not:

    General Preambles 6: "Items against which no rate is entered shall be deemed to be covered by
    the other rates in the bill of quantities."

You have agreed to do that work, at no charge, for the life of a remeasured contract. It is the most
expensive mistake available anywhere in this process and it looks exactly like an empty cell.
"""

from __future__ import annotations

from typing import Optional

from client_boq.estimate import money
from client_boq.models import BillItem, ClientBill, EstimateFlag, PricedBill

# How far a rate may sit from the median of comparable items before it is worth a second look.
# "Comparable" is same bill, same unit — the only grouping the bill itself supplies. Wide, because
# this is a prompt to check, not an accusation: work genuinely varies within a unit.
ERRATIC_BAND = 4.0
# Below this many comparable items a median means nothing and the check stays quiet.
ERRATIC_MIN_PEERS = 4

CENT = 0.005


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def unpriced_items(priced: PricedBill, bill: ClientBill) -> list[EstimateFlag]:
    """Every item with no rate behind it. See the module docstring — this is the expensive one."""
    index = bill.index()
    flags: list[EstimateFlag] = []
    for entry in priced.items:
        item = index.get(entry.full_ref)
        if item is None or item.pre_priced:
            continue
        if entry.unit_rate is None and entry.amount == 0:
            flags.append(EstimateFlag(
                kind="unpriced_item", item_id=entry.full_ref,
                message=(f"{entry.full_ref} {entry.description[:60]!r} carries no rate. General "
                         f"Preambles 6 deems an unpriced item 'covered by the other rates', and "
                         f"GCT App C 2.2(iii) marks the rate as zero at examination — so this "
                         f"becomes work you have agreed to do for nothing"),
            ))
    return flags


def spread_reaches_the_rates(priced: PricedBill) -> list[EstimateFlag]:
    """The sweep pool against the sum of the shares that actually landed on items.

    A cost routed to SPREAD has already been decided: it is real, it is yours, and the contract
    orders it into the rates instead of measuring it —

        PP 11/2A (site uniform), NTT C2 (Subcontractor Management Plan), NTT C25 (Pay for Safety to
        subcontractors): "There shall be no measurement or separate payment."

    But ``_allocate`` spreads pro rata on build-up value, and returns **nothing at all** when no
    priceable item has a build-up. ``PricedBill.spread_total`` still reports the pool, so the screen
    shows the money as handled while no rate carries a penny of it, and ``tendered_total`` — the sum
    of the extensions — leaves it out entirely. That is the recurring shape: the number is right and
    the population was never checked.

        Particular Preamble 4A — "Any item missed out from the item coverage shall not be measured."
        General Preambles 6 — an item with no rate is "deemed to be covered by the other rates".

    Both point one way: a cost that reaches no rate is a cost given away.
    """
    pool = money(priced.spread_total or 0.0)
    if pool <= 0:
        return []
    landed = money(sum(entry.spread for entry in priced.items))
    if abs(pool - landed) <= CENT:
        return []
    if landed <= 0:
        return [EstimateFlag(
            kind="spread_unallocated", item_id="(spread)",
            message=(f"{pool:,.2f} of swept cost was routed into the rates and reached none of "
                     f"them. The pool is spread pro rata on build-up value, and no item in this "
                     f"bill has a build-up yet — so the whole pool is shown as handled and is in "
                     f"no rate and in no tendered total. Price at least one item and it lands"),
        )]
    return [EstimateFlag(
        kind="spread_unallocated", item_id="(spread)",
        message=(f"{money(pool - landed):,.2f} of the {pool:,.2f} swept into the rates reached no "
                 f"item — {landed:,.2f} was allocated. A cost the contract orders into the rates "
                 f"and that lands in none of them is work you have agreed to do for nothing"),
    )]


def platform_cost_unconsumed(total: float) -> list[EstimateFlag]:
    """A platform cost typed on the groups that no engine consumes. The amount, named.

    The Site Groups screen collects "platform build" per group (`HoleGroup.access_build_cost`) and
    `groups.access_build_total()` sums it — and nothing in either pricing engine reads that sum.
    An estimator who typed HK$120,000 of Class B platforms has recorded a judgement that reaches
    no rate, no total and no tender, and every screen reads as if it were handled.

        SMM S02 ¶2.08(h) puts access scaffolding in the item coverage for moving rigs, measured
        per hole (¶2.03) — so it belongs inside the Class B rig-move rate, not nowhere.

    A GUARD, not the wiring: routing it into a per-class rig-move basis is the basis-table
    redesign (plan Phase 3), and must not happen as the side effect of a leak fix. Until then the
    money is visible, which is the difference between a cost somebody will carry and one nobody
    knows is missing.
    """
    if total <= 0:
        return []
    return [EstimateFlag(
        kind="platform_cost_unconsumed", item_id="(groups)",
        message=(f"{total:,.2f} of platform build cost is typed on the Site groups and nothing "
                 f"prices it — it is in no rate and no total. SMM S02 ¶2.08(h) puts access "
                 f"scaffolding in the moving-rigs item coverage, so make sure it is inside your "
                 f"2.2b build-up, or route it as a cost on the sweep, until the engine carries "
                 f"it itself."),
    )]


def orphan_priced_items(priced: PricedBill, bill: ClientBill) -> list[EstimateFlag]:
    """Priced lines whose reference is in no item of the client's bill.

    THE SHAPE THAT MAKES THIS THE WORST KIND OF MISS. Every check that reasons about a rate looks
    the item up first and skips a miss: ``unpriced_items``, ``pre_priced_mismatch`` and
    ``erratic_pricing`` all begin ``if item is None: continue``. But ``casting_errors`` sums
    ``priced.items`` directly, so an orphan's money DOES reach the bill total and the Grand Summary.
    It counts where it helps and vanishes where it would be caught — an unpriced orphan is never
    flagged as unpriced, a wrong one is never compared with the client's rate, and a wild one never
    enters a peer group.

    It happens the ordinary way: a reference typed with a different suffix, a revision that renamed
    an item, a build-up keyed to a ref the current bill no longer has. That is Class 2 — written
    under one identity, read under another — and the only defence is to say so.
    """
    known = set(bill.index())
    flags: list[EstimateFlag] = []
    for entry in priced.items:
        if entry.full_ref in known:
            continue
        flags.append(EstimateFlag(
            kind="orphan_priced_item", item_id=entry.full_ref,
            message=(f"{entry.full_ref} carries {entry.amount:,.2f} but is in no item of the "
                     f"client's bill at this revision. Its money reaches the bill total and the "
                     f"Grand Summary, and every rate check skips it — so nothing else here will "
                     f"ever tell you it is wrong. Either the reference is mistyped or the item was "
                     f"renamed in a revision and the rate was not moved with it"),
        ))
    return flags


def duplicate_bill_refs(bill: ClientBill) -> list[EstimateFlag]:
    """Two items sharing one reference. ``ClientBill.index()`` keeps ONE of them.

    ``index()`` is "the identity map every downstream stage keys on", and it is a dict comprehension
    over ``full_ref`` — so a repeated reference silently collapses and the loser disappears from
    every lookup in this module, from the coverage checklist and from the rate carry. The reader
    already notes a duplicate WITHIN one bill; a reference repeated across two bills was noted
    nowhere, because the reader's own key includes the bill number and ``index()``'s does not.
    """
    seen: dict[str, list[str]] = {}
    for item in bill.items:
        seen.setdefault(item.full_ref, []).append(f"Bill No.{item.bill_no} row {item.row}")
    flags: list[EstimateFlag] = []
    for ref, places in sorted(seen.items()):
        if len(places) > 1:
            flags.append(EstimateFlag(
                kind="duplicate_bill_ref", item_id=ref,
                message=(f"{ref} appears {len(places)} times ({', '.join(places)}). The identity "
                         f"map every stage keys on holds one item per reference, so all but one of "
                         f"these are invisible to the coverage checklist, the rate carry and every "
                         f"check here. Neither is assumed correct"),
            ))
    return flags


def pre_priced_mismatch(priced: PricedBill, bill: ClientBill) -> list[EstimateFlag]:
    """A client-inserted rate or amount we have not carried through exactly."""
    index = bill.index()
    flags: list[EstimateFlag] = []
    for entry in priced.items:
        item = index.get(entry.full_ref)
        if item is None or not item.pre_priced:
            continue
        if item.client_rate is not None and entry.unit_rate != item.client_rate:
            flags.append(EstimateFlag(
                kind="pre_priced_mismatch", item_id=entry.full_ref,
                message=(f"{entry.full_ref} is pre-priced by the client at {item.client_rate:,.2f} "
                         f"but carries {entry.unit_rate}. GCT App C 2.2(vi) reinstates the client's "
                         f"figure anyway; these items exist so nobody can compete on them"),
            ))
    return flags


def extension_errors(priced: PricedBill) -> list[EstimateFlag]:
    """Amounts that are not quantity x rate. The examiner recomputes all of them (App C 2.2(i))."""
    flags: list[EstimateFlag] = []
    for entry in priced.items:
        if entry.unit_rate is None or entry.lump or entry.qty is None:
            continue
        expected = money(entry.qty * entry.unit_rate)
        if abs(expected - entry.amount) > CENT:
            flags.append(EstimateFlag(
                kind="extension_error", item_id=entry.full_ref,
                message=(f"{entry.full_ref}: {entry.qty:,g} x {entry.unit_rate:,.2f} is "
                         f"{expected:,.2f}, but the amount reads {entry.amount:,.2f}. The examiner "
                         f"corrects the extension and carries the corrected figure up (App C "
                         f"2.2(i)); the rate itself can never be changed (App C 2.1)"),
            ))
    return flags


def casting_errors(priced: PricedBill) -> list[EstimateFlag]:
    """Page totals, bill totals and (A) that do not agree with the items beneath them."""
    flags: list[EstimateFlag] = []
    by_bill: dict[str, float] = {}
    for entry in priced.items:
        by_bill[entry.bill_no] = money(by_bill.get(entry.bill_no, 0.0) + entry.amount)

    for bill_no, total in sorted(by_bill.items()):
        stated = priced.bill_totals.get(bill_no)
        if stated is None or abs(stated - total) > CENT:
            flags.append(EstimateFlag(
                kind="casting_error", item_id=f"Bill No.{bill_no}",
                message=(f"Bill No.{bill_no} totals {total:,.2f} from its items but is carried as "
                         f"{stated if stated is not None else 'nothing':}. Every collection and the "
                         f"Grand Summary is recast at examination (App C 2.2(i), 2.3)"),
            ))

    grand = money(sum(by_bill.values()))
    if abs(grand - priced.tendered_total) > CENT:
        flags.append(EstimateFlag(
            kind="casting_error", item_id="(A)",
            message=(f"the bills total {grand:,.2f} but the tendered total of the Prices reads "
                     f"{priced.tendered_total:,.2f}. (A) is what goes on the Form of Tender and the "
                     f"Contract Data, and the Grand Summary prevails over both (App C 2.3A)"),
        ))
    return flags


def provisional_sums_intact(bill: ClientBill, issued: Optional[dict[str, float]] = None
                            ) -> list[EstimateFlag]:
    """The contingency and provisional sums the client inserted, still exactly as issued.

    (B), (D) and (E) are not ours. ACC Clause II:4 puts them outside the contract entirely — they
    are "allowed as contingencies for the purpose of internal administration of the Client under the
    Stores and Procurement Regulations only" — but they still feed the forecast total the bid is
    SCORED on, so a wrong one moves your ranking without moving your price.
    """
    if not issued:
        return []
    current = {line.code: line.amount for line in bill.summary if line.code}
    flags: list[EstimateFlag] = []
    for code, expected in sorted(issued.items()):
        actual = current.get(code)
        if actual is None or abs(actual - expected) > CENT:
            flags.append(EstimateFlag(
                kind="provisional_sum_altered", item_id=f"({code})",
                message=(f"Grand Summary ({code}) reads "
                         f"{actual if actual is not None else 'nothing'} against the "
                         f"{expected:,.2f} the client inserted. GCT App C 2.5 reinstates it; it "
                         f"feeds the forecast total the tender is scored on"),
            ))
    return flags


def erratic_pricing(priced: PricedBill, bill: ClientBill) -> list[EstimateFlag]:
    """Rates far out of line with comparable items in the same bill.

    GCT 14(2) defines erratic pricing as "significant and unjustified ... inconsistency, irregularity
    or non-uniformity as compared with item or items of the same or similar nature in the same bill
    of quantities", and 14(1) lets the client set a tender aside for it "irrespective of whether or
    not it is the lowest tender or the tender with the highest overall score".

    This flags; it does not judge. Front-loading can be entirely deliberate and defensible — the
    point is to know which lines would be asked about.
    """
    index = bill.index()
    groups: dict[tuple[str, str], list[tuple[str, float]]] = {}
    for entry in priced.items:
        item = index.get(entry.full_ref)
        if item is None or item.pre_priced or entry.unit_rate is None or entry.lump:
            continue
        if entry.unit_rate <= 0:
            continue
        groups.setdefault((entry.bill_no, entry.unit), []).append((entry.full_ref, entry.unit_rate))

    flags: list[EstimateFlag] = []
    for (bill_no, unit), entries in sorted(groups.items()):
        if len(entries) < ERRATIC_MIN_PEERS:
            continue
        middle = _median([rate for _, rate in entries])
        if middle <= 0:
            continue
        for ref, rate in entries:
            factor = rate / middle
            if factor > ERRATIC_BAND or factor < 1 / ERRATIC_BAND:
                flags.append(EstimateFlag(
                    kind="erratic_pricing", item_id=ref,
                    message=(f"{ref} is priced at {rate:,.2f} per {unit}, {factor:.1f}x the median "
                             f"{middle:,.2f} of the {len(entries)} items in Bill No.{bill_no} "
                             f"measured in {unit}. GCT 14 lets the client set aside a tender for "
                             f"pricing 'significant and unjustified' against items of similar "
                             f"nature, even the lowest one"),
                ))
    return flags


def fee_percentage_in_range(fee_pct: Optional[float], minimum: float, cap: float
                            ) -> list[EstimateFlag]:
    """The direct fee percentage against its floor and cap.

    SCT 19: it "shall be within a range from the minimum fee percentage to the cap ... as stated in
    the Contract Data Part two". It is not a bill rate, but it is priced: the Grand Summary sets
    (C) = (B) x the fee percentage, (C) feeds (F) feeds (G), and (G) is what the 60-point price
    score is computed on. Omit it and GCT App C 2.4 corrects it to the MINIMUM, which quietly
    improves your score and binds you to the lowest markup you could have offered.
    """
    if fee_pct is None:
        return [EstimateFlag(
            kind="fee_percentage_out_of_range", item_id="(C)",
            message=(f"no direct fee percentage. GCT App C 2.4 corrects an omitted one to the "
                     f"minimum, {minimum:g}% — you would be bound to the lowest markup available "
                     f"and never asked"),
        )]
    if fee_pct < minimum or fee_pct > cap:
        return [EstimateFlag(
            kind="fee_percentage_out_of_range", item_id="(C)",
            message=(f"the direct fee percentage {fee_pct:g}% is outside the {minimum:g}%-{cap:g}% "
                     f"range of SCT 19; it is corrected to the nearer bound at examination, and it "
                     f"feeds the forecast total the tender is scored on"),
        )]
    return []


def run_checks(priced: PricedBill, bill: ClientBill, *,
               issued_sums: Optional[dict[str, float]] = None,
               fee_pct: Optional[float] = None,
               fee_range: tuple[float, float] = (5.0, 30.0)) -> list[EstimateFlag]:
    """Every guard, in the order an estimator would want to read them: what is missing, then what
    is wrong, then what will be asked about."""
    flags = [
        # Identity first: a line nothing can find, and a reference two lines share. Both make every
        # check below them read a population that is not the bill's.
        *duplicate_bill_refs(bill),
        *orphan_priced_items(priced, bill),
        *unpriced_items(priced, bill),
        *spread_reaches_the_rates(priced),
        *pre_priced_mismatch(priced, bill),
        *extension_errors(priced),
        *casting_errors(priced),
        *provisional_sums_intact(bill, issued_sums),
        *erratic_pricing(priced, bill),
    ]
    # THE TRIGGER IS THE BILL'S OWN (C) LINE, not a proxy. This used to run only when a fee was
    # supplied OR the bill had client-inserted provisional sums — and those are different things:
    # (B), (D) and (E) are contingencies outside the contract, (C) is the direct fee. A bill with a
    # fee line and no contingencies therefore skipped the check entirely, which is exactly the case
    # it exists for: GCT App C 2.4 corrects an OMITTED fee to the minimum, binding you to the
    # lowest markup available without ever asking.
    has_fee_line = any(line.code == "C" for line in bill.summary)
    if fee_pct is not None or has_fee_line:
        flags.extend(fee_percentage_in_range(fee_pct, *fee_range))
    return flags
