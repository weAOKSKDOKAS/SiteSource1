"""Node 43 — one tender total from two engines, with every gap and double-count named.

The offer's price today is only the self-perform estimate; the sublet packages Track A levels and
awards were never combined in, so the price on the Offer, the approval and the submission described
HALF the tender. This module is the seam that joins them:

    reads   the ROUTE DECISIONS   (bridge/decisions — which package is self-perform vs sublet)
            the PRICED BILL       (the costing engine's per-item amounts — the self-perform side)
            the AWARDS            (bridge/award — the levelled total of each sublet package)
    yields  ONE total, composed:  Σ self-perform item amounts  +  Σ awarded sublet totals

**The two errors it exists to catch, checked by construction:**

* a GAP — a routed package priced by neither side: a sublet package with no recorded award is
  named, and its items' estimate amounts are NOT quietly left in the total as a stand-in;
* a DOUBLE-COUNT — a package priced by both: a sublet package's items are excluded from the
  self-perform sum by construction, and the displaced amount is SHOWN, so "what the estimate would
  have charged" and "what the sub charges" sit side by side instead of being added together. An
  award whose package is no longer routed sublet is stale — named and not counted.

**What this deliberately does NOT do (fork 5 — report-and-stop):** normalise. Whether the levelled
sub totals are ex-GST like the offer, whose mobilisation a sublet package carries when the sub's
return has its own, and how Bill 1 time-related preliminaries split when part of the work is sublet
— those are domain rules nobody has stated, so the composition is presented RAW with the questions
on the payload. Nothing here rewrites the offer letter's price; the combined figure stands beside
it with the difference named.

Ownership: genuinely shared — it reads Track A and Track B and feeds the offer surface, so it lives
in ``bridge/`` beside the other tender-level seams, inside neither engine.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

# Fork 5's open questions, stated once. On the payload verbatim — the surface shows them beside
# the total so the raw composition cannot read as a settled number.
OPEN_QUESTIONS = [
    "GST: the offer is stated 'excluding GST' — confirm every levelled sublet total is ex-GST "
    "before this figure goes near the letter.",
    "Mobilisation: a sublet package's award may include the sub's own mob/demob while the "
    "self-perform estimate carries a mobilisation for the whole spread — whose is counted, once?",
    "Preliminaries: Bill 1 time-related items are priced self-perform for the whole contract "
    "period — decide whether any share belongs to the sublet packages before comparing margins.",
]


class SideLine(BaseModel):
    """One package's contribution, from whichever side prices it."""

    package_key: str
    side: str                       # "self_perform" | "sublet"
    amount: Optional[float] = None
    items: int = 0
    firm_name: str = ""             # sublet only
    displaced_estimate: Optional[float] = None    # sublet only: what the estimate would have said
    note: str = ""


class CombinedPricing(BaseModel):
    """The whole composition — every number beside where it came from."""

    set_id: str
    routed: bool = False
    self_perform_total: Optional[float] = None
    sublet_total: Optional[float] = None
    combined_total: Optional[float] = None
    lines: list[SideLine] = Field(default_factory=list)
    unrouted_amount: Optional[float] = None       # items in no package: self-perform by default
    unrouted_items: int = 0
    displaced_estimate_total: float = 0.0         # what the estimate said for the sublet items
    letter_price: Optional[float] = None
    gaps: list[str] = Field(default_factory=list)
    double_counts: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)


def compose(set_id: str, *, priced_rows: list[dict], units: list[dict],
            sublet_packages: list[str], self_perform_packages: list[str],
            awards: list[dict], letter_price: Optional[float] = None) -> CombinedPricing:
    """The pure composition — every input handed in, nothing loaded, fully testable.

    ``priced_rows``: the costing engine's rows (``full_ref``, ``amount``). ``units``: the routed
    units (``package_key`` and the item refs it carries).
    """
    result = CombinedPricing(set_id=set_id, letter_price=letter_price,
                             open_questions=list(OPEN_QUESTIONS))
    amounts = {row["full_ref"]: row.get("amount") for row in priced_rows}
    items_of = {u["package_key"]: list(u["item_refs"]) for u in units}
    award_by_key = {a["package_key"]: a for a in awards}

    result.routed = bool(sublet_packages or self_perform_packages)
    if not result.routed:
        result.notes.append(
            "no routing confirmed — the whole bill reads self-perform and this is simply the "
            "priced bill's total")

    # A stale award: recorded for a package the routing no longer sends out. Named, never counted —
    # counting it beside the estimate's own pricing of the same items is the double-count itself.
    for key, record in sorted(award_by_key.items()):
        if key not in sublet_packages:
            result.double_counts.append(
                f"award for {key!r} ({record['firm_name'] or record['firm_id']}, "
                f"{record['total'] if record['total'] is not None else 'no total'}) but that "
                f"package is not routed sublet — not counted; re-route or clear the award")

    sublet_refs: set[str] = set()
    sublet_sum = 0.0
    sublet_priced = False
    for key in sublet_packages:
        refs = items_of.get(key, [])
        sublet_refs.update(refs)
        displaced = _sum_known(amounts, refs)
        record = award_by_key.get(key)
        if record is None:
            result.gaps.append(
                f"sublet package {key!r} has NO recorded award — priced by neither side. Its "
                f"{len(refs)} item(s) are excluded from the total rather than quietly carried at "
                f"the estimate's numbers; award it (or re-route it) to close the gap")
            result.lines.append(SideLine(package_key=key, side="sublet", amount=None,
                                         items=len(refs), displaced_estimate=displaced,
                                         note="no award recorded — a gap, not a zero"))
            continue
        if record["total"] is None:
            result.gaps.append(
                f"sublet package {key!r} is awarded to "
                f"{record['firm_name'] or record['firm_id']} with no total recorded — the award "
                f"exists but carries no money, so the combined total cannot include it")
            result.lines.append(SideLine(package_key=key, side="sublet", amount=None,
                                         items=len(refs),
                                         firm_name=record["firm_name"] or record["firm_id"],
                                         displaced_estimate=displaced,
                                         note="award has no levelled total"))
            continue
        sublet_priced = True
        sublet_sum += record["total"]
        if displaced is not None:
            result.displaced_estimate_total += displaced
        result.lines.append(SideLine(
            package_key=key, side="sublet", amount=record["total"], items=len(refs),
            firm_name=record["firm_name"] or record["firm_id"], displaced_estimate=displaced))

    # Self-perform: the priced bill, MINUS the items the sublet packages carry. Exclusion by
    # construction is what makes a double-count impossible rather than merely checked-for.
    self_sum: Optional[float] = 0.0
    for key in self_perform_packages:
        refs = items_of.get(key, [])
        amount = _sum_known(amounts, refs)
        unpriced = [r for r in refs if amounts.get(r) is None]
        note = (f"{len(unpriced)} item(s) unpriced in the costing engine" if unpriced else "")
        if unpriced:
            result.gaps.append(
                f"self-perform package {key!r}: {len(unpriced)} item(s) carry no amount in the "
                f"priced bill ({', '.join(unpriced[:4])}{'…' if len(unpriced) > 4 else ''}) — "
                f"the package is under-priced until they are")
        result.lines.append(SideLine(package_key=key, side="self_perform", amount=amount,
                                     items=len(refs), note=note))
        if amount is not None and self_sum is not None:
            self_sum += amount

    routed_refs = {r for refs in items_of.values() for r in refs}
    unrouted = [ref for ref, amount in amounts.items()
                if ref not in routed_refs and amount is not None]
    result.unrouted_items = len(unrouted)
    result.unrouted_amount = _sum_known(amounts, unrouted) if unrouted else 0.0
    if result.routed and unrouted:
        result.notes.append(
            f"{len(unrouted)} priced item(s) sit in no routed package — counted on the "
            f"self-perform side by default, because unrouted work is work we do")

    result.self_perform_total = (self_sum or 0.0) + (result.unrouted_amount or 0.0)
    # None when sublet packages exist and not one is priced — a column of pure gaps must not
    # read as "$0 of subcontract"; with no sublet packages at all, zero is the honest number.
    result.sublet_total = (sublet_sum if sublet_priced
                           else (0.0 if not sublet_packages else None))
    if result.gaps:
        result.notes.append(
            f"the combined total EXCLUDES the {len(result.gaps)} gap(s) above — it is a floor, "
            f"not the tender price, until every routed package is priced by exactly one side")
    result.combined_total = result.self_perform_total + sublet_sum

    if letter_price is not None and result.combined_total is not None:
        delta = result.combined_total - letter_price
        if abs(delta) > 0.005:
            result.notes.append(
                f"the offer letter currently says {letter_price:,.2f} — the combined figure "
                f"differs by {delta:+,.2f}, because the letter's price is the self-perform "
                f"estimate alone (fork 5 is open; nothing rewrites the letter from here)")
    return result


def _sum_known(amounts: dict, refs) -> Optional[float]:
    known = [amounts[r] for r in refs if amounts.get(r) is not None]
    return sum(known) if known else None


def combined_pricing(set_id: str, rev: Optional[int] = None) -> CombinedPricing:
    """Load every side from where it already lives, then :func:`compose`.

    Imports client_boq's costing assembly (ours to work) rather than re-implementing the pricing
    pipeline — a second implementation of the priced bill is a second source of truth, which is
    the exact failure this seam exists to close.
    """
    from client_boq import store as cb_store
    from client_boq.router import _costing
    from pipeline.routing.split import route_units

    from bridge import award, decisions, scope as scope_mod
    from bridge.identity import bridge_conn, run_ref_for

    ref = run_ref_for(set_id)
    state = decisions.stored_decisions(ref)
    awards = award.load_awards(ref)

    no_bill_reason = ""
    conn = bridge_conn()
    try:
        split = scope_mod.load_scope_on(conn, ref)
        letter = cb_store.load_letter(conn, ref)
        try:
            priced = _costing(conn, ref, rev)["priced"]
            priced_rows = [{"full_ref": r.full_ref, "amount": r.amount} for r in priced.rows]
        except Exception as exc:  # noqa: BLE001 — no bill imported yet is a state, not a crash
            priced_rows = []
            no_bill_reason = str(exc)
    finally:
        conn.close()

    units = []
    if split is not None:
        units = [{"package_key": u["package_key"],
                  "item_refs": [it.item_ref for it in u["package"].sor_items]}
                 for u in route_units(split)]

    result = compose(
        ref, priced_rows=priced_rows, units=units,
        sublet_packages=state.get("sublet_packages", []),
        self_perform_packages=state.get("self_perform_packages", []),
        awards=awards, letter_price=(letter.price if letter else None))
    if not priced_rows:
        result.notes.append(
            "no priced bill for this tender yet — the self-perform side is empty, so the combined "
            "figure below is the sublet awards alone"
            + (f" ({no_bill_reason})" if no_bill_reason else ""))
    if split is None and result.routed:
        result.notes.append(
            "routing decisions exist but no scope split is stored — packages cannot be decomposed "
            "into items, so the self-perform side cannot be separated from the sublet items")
    return result
