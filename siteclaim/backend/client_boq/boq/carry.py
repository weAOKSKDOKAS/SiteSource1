"""BOQ — carry rates across a revision of the bill.

Bucket: **Rule**. The rules are not ours; they are published by the client, and they are applied to
your tender whether or not you apply them yourself.

    GCT Appendix C 2.2(v): "Should there be a tender addendum introducing changes to the bill of
    quantities but the changes have not been incorporated into the bill of quantities by a tenderer,
    then the changes as required by the tender addendum shall be incorporated into the tenderer's
    bill of quantities and the rates for those new items or modified items shall be determined as
    follows:"

        new item introduced          "Rate for the new item shall be marked as zero and the price of
                                      the item shall be deemed to have been allowed for in rates
                                      entered elsewhere in the bill of quantities, unless it is an
                                      item pre-priced by the Client. For a pre-priced item, the same
                                      rate in the addendum shall be used."
        description and/or           "If a rate has been entered against the original item of work,
        quantity changed              the same rate shall be used."
        item deleted                 "That item shall be deleted in accordance with the addendum."
        measurement unit modified    "If a rate has been entered against the original item of work,
                                      the rate shall be adjusted to fit in with the new unit."

    under the cardinal rule, GCT Appendix C 2.1: "Under no circumstances can the tendered rates be
    changed."

So this module reproduces the tender examiner's arithmetic. That is the safe default: it is what
happens to the bid anyway.

WHAT IS OURS, AND IS NOT IN THE CLIENT'S RULES
----------------------------------------------
``needs_review``. A carry can be perfectly legal and completely wrong as an estimate. The reference
addendum multiplied three groundwater-monitoring quantities by 2.17 — 24 weeks per instrument
becoming 52 — and App C 2.2(v) says to carry the old rate onto the new quantity without comment. The
rate that was right for six months of monitoring is not obviously right for twelve: the standing
plant, the visit pattern and the reporting load all move.

Equally, a description narrowed from "test for soil and ground water" to "test for soil" at an
unchanged quantity means the same rate now buys half the medium it did — which the same rule carries
forward silently.

So anything whose quantity moved beyond a threshold, or whose wording or unit changed, is carried
AND flagged, and the revision cannot be signed off until a person has looked. This mirrors what the
review side already does when an addendum rewrites a clause somebody had approved: the approval is
torn up rather than quietly inherited.

A unit change is never converted automatically. "Adjust the rate to fit the new unit" is trivial for
m → mm and meaningless for nr → m, and a factor invented here would be indistinguishable, downstream,
from one somebody checked.
"""

from __future__ import annotations

from typing import Optional

from client_boq.models import (
    CARRY_DELETED,
    CARRY_NEEDS_HUMAN,
    CARRY_NEW_ZERO,
    CARRY_PRE_PRICED,
    CARRY_SAME_RATE,
    CHANGE_ADDED,
    CHANGE_DELETED,
    CHANGE_DESCRIPTION,
    CHANGE_HEADING,
    CHANGE_QTY,
    CHANGE_UNIT,
    BillDiff,
    CarriedRate,
    ClientBill,
)

# How far a quantity may move before the carried rate has to be looked at again. 10% is a judgement
# call, deliberately low: the cost of a needless second look is a minute, and the cost of missing a
# 117% move is the contract.
QTY_REVIEW_BAND = 0.10

RULE_NEW = ('GCT App C 2.2(v): "Rate for the new item shall be marked as zero and the price of the '
            'item shall be deemed to have been allowed for in rates entered elsewhere in the bill '
            'of quantities"')
RULE_PRE_PRICED = ('GCT App C 2.2(v): "unless it is an item pre-priced by the Client. For a '
                   'pre-priced item, the same rate in the addendum shall be used."')
RULE_SAME = ('GCT App C 2.2(v): "Where the item description and/or quantity is changed — if a rate '
             'has been entered against the original item of work, the same rate shall be used."')
RULE_DELETED = 'GCT App C 2.2(v): "That item shall be deleted in accordance with the addendum."'
RULE_UNIT = ('GCT App C 2.2(v): "Where the measurement unit is modified — if a rate has been entered '
             'against the original item of work, the rate shall be adjusted to fit in with the new '
             'unit."')
RULE_UNCHANGED = 'GCT App C 2.1: "Under no circumstances can the tendered rates be changed."'


def _changes_by_ref(diff: BillDiff) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for change in diff.changes:
        out.setdefault(f"{change.bill_no}:{change.full_ref}", []).append(change.kind)
    return out


def _qty_move(before_qty: Optional[float], after_qty: Optional[float]) -> Optional[float]:
    """The proportional move in a quantity, or None when it cannot be expressed as one."""
    if before_qty is None or after_qty is None or before_qty == 0:
        return None
    return (after_qty - before_qty) / before_qty


def carry_rates(diff: BillDiff, before: ClientBill, after: ClientBill,
                priced: dict[str, Optional[float]]) -> list[CarriedRate]:
    """Propose a rate for every item of the NEW revision.

    ``priced`` maps ``full_ref`` → the rate held against the OLD revision (None where unpriced).
    Nothing here writes anything: these are proposals, and a person confirms them. Every result
    names the rule that produced it, so the proposal explains itself rather than asking to be
    trusted.
    """
    kinds = _changes_by_ref(diff)
    old_index = {f"{i.bill_no}:{i.full_ref}": i for i in before.items}
    out: list[CarriedRate] = []

    for item in after.items:
        key = f"{item.bill_no}:{item.full_ref}"
        item_kinds = set(kinds.get(key, []))
        previous = old_index.get(key)
        old_rate = priced.get(item.full_ref)

        if item.is_parent:
            continue                       # a parent carries no rate; its variants do

        if item.pre_priced:
            out.append(CarriedRate(
                full_ref=item.full_ref, rate=item.client_rate, basis=CARRY_PRE_PRICED,
                rule=RULE_PRE_PRICED,
                reason="the client's own rate; altering it only gets it reinstated (App C 2.2(vi))",
            ))
            continue

        if CHANGE_ADDED in item_kinds or previous is None:
            out.append(CarriedRate(
                full_ref=item.full_ref, rate=None, basis=CARRY_NEW_ZERO, rule=RULE_NEW,
                needs_review=True,
                reason=(f"new item, {item.description[:60]!r}. Left unpriced it is not free — "
                        f"General Preambles 6 deems it covered by the other rates, so it becomes "
                        f"work you have agreed to do for nothing"),
            ))
            continue

        if CHANGE_UNIT in item_kinds:
            out.append(CarriedRate(
                full_ref=item.full_ref, rate=old_rate, basis=CARRY_NEEDS_HUMAN, rule=RULE_UNIT,
                needs_review=True,
                reason=(f"the unit changed from {previous.unit!r} to {item.unit!r}. The rule says "
                        f"to adjust the rate to fit the new unit, but only a person can say whether "
                        f"a conversion exists — it is arithmetic for m to mm and meaningless for "
                        f"nr to m"),
            ))
            continue

        if old_rate is None:
            out.append(CarriedRate(
                full_ref=item.full_ref, rate=None, basis=CARRY_NEW_ZERO, rule=RULE_NEW,
                needs_review=bool(item_kinds),
                reason="nothing was priced against this item in the previous revision",
            ))
            continue

        move = _qty_move(previous.qty, item.qty)
        review, reason = False, ""

        if CHANGE_QTY in item_kinds and move is not None and abs(move) > QTY_REVIEW_BAND:
            review = True
            reason = (f"the quantity moved {move * 100:+.0f}% ({previous.qty:,.0f} → "
                      f"{item.qty:,.0f} {item.unit}). Carrying the rate is what the rule says and "
                      f"may still be the wrong estimate — the resourcing behind a rate does not "
                      f"always scale with the quantity")
        elif CHANGE_QTY in item_kinds:
            review = True
            reason = (f"the quantity changed ({previous.qty} → {item.qty} {item.unit}) in a way that "
                      f"cannot be expressed as a proportion, so it has to be read")
        elif CHANGE_DESCRIPTION in item_kinds:
            review = True
            reason = (f"the wording changed at an unchanged quantity, so the same rate now covers "
                      f"different work: {previous.description[:70]!r} → {item.description[:70]!r}")
        elif CHANGE_HEADING in item_kinds:
            review = True
            reason = ("the heading above this item changed. Its own row is untouched, but a heading "
                      "is part of what the item covers (General Preambles 2), so its scope moved")

        out.append(CarriedRate(
            full_ref=item.full_ref, rate=old_rate, basis=CARRY_SAME_RATE,
            rule=RULE_SAME if item_kinds else RULE_UNCHANGED,
            needs_review=review, reason=reason,
        ))

    for change in diff.changes:
        if change.kind == CHANGE_DELETED:
            out.append(CarriedRate(
                full_ref=change.full_ref, rate=None, basis=CARRY_DELETED, rule=RULE_DELETED,
                reason=(f"the item is gone from revision {diff.to_rev}; any rate held against it "
                        f"has nowhere to go"),
            ))

    return out


def pending_review(carried: list[CarriedRate]) -> list[CarriedRate]:
    """The re-price worklist — what a person has to look at before this revision can be signed off."""
    return [c for c in carried if c.needs_review]
