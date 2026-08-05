"""BOQ — what changed between two revisions of the client's bill.

Bucket: **Deterministic**. Pure comparison of two ``ClientBill`` objects; no model, no heuristics.

This module exists because the workbook itself says nothing. Measured across all three revisions of
the reference bill: every one of 1,239 non-empty cells has no fill, changed rows carry the same font
as unchanged rows, there are no cell comments, no defined names and no tracked changes, and Rev 2
does not even carry the addendum footer that Rev 1 did. The client's own summary of the change is
disclaimed in writing — "neither exhaustive nor guaranteed to be accurate" — and one of its three
bill remarks is factually wrong.

So the largest price movement in that tender reached the tenderer as seven words, "Updated the
quantities of item nos. 6.4 - 6.6", covering three cells that took groundwater monitoring from
24 weeks per instrument to 52. Comparing two workbooks by eye, under deadline, across 166 items, is
the only defence the paper process offers. This is the defence the software offers instead.

Two rules make the output worth reading:

**Identity is the item reference, never the row.** Between Rev 0 and Rev 1 of the reference bill,
35 items moved rows and 0 were renumbered. Reporting a move as a change would bury the five real
changes under thirty-five false ones, which is exactly how a safeguard gets ignored.

**A caption change is an item change.** The second addendum edited one cell — "Maintain marine
traffic flow" to "Maintain land traffic flow" — and touched none of the three items beneath it. But
General Preambles 2 makes a sub-heading part of what an item covers, so those three items moved from
marine to land traffic scope. An item-row diff reports "nothing changed" there. This one does not.
"""

from __future__ import annotations

from typing import Optional

from client_boq.models import (
    CHANGE_ADDED,
    CHANGE_DELETED,
    CHANGE_DESCRIPTION,
    CHANGE_HEADING,
    CHANGE_PRE_PRICED,
    CHANGE_QTY,
    CHANGE_UNIT,
    BillDiff,
    BillItem,
    ClientBill,
    ItemChange,
)


def _key(item: BillItem) -> str:
    """The identity a diff is keyed on. Qualified by bill because the lettered variants are stored
    as a bare "a" — Bill No.2's "a" and Bill No.3's "a" are different items."""
    return f"{item.bill_no}:{item.full_ref}"


def _num(value: Optional[float]) -> str:
    if value is None:
        return "—"
    return f"{int(value):,}" if float(value).is_integer() else f"{value:,.2f}"


def _qty_text(item: BillItem) -> str:
    if item.lump:
        return "- (lump)"
    return f"{_num(item.qty)} {item.unit}".strip()


def _qty_change(before: BillItem, after: BillItem) -> Optional[ItemChange]:
    if before.lump == after.lump and before.qty == after.qty:
        return None
    detail = f"quantity {_qty_text(before)} → {_qty_text(after)}"
    if before.lump != after.lump:
        detail += (" — the item changed between a lump sum and a measured quantity, which changes "
                   "how it is paid, not just what it costs")
    elif before.qty and after.qty and before.qty > 0:
        factor = after.qty / before.qty
        detail += f" (×{factor:.2f})" if factor >= 1 else f" (×{factor:.2f}, a reduction)"
    return ItemChange(kind=CHANGE_QTY, bill_no=after.bill_no, full_ref=after.full_ref,
                      before=_qty_text(before), after=_qty_text(after), detail=detail)


def _heading_change(before: BillItem, after: BillItem) -> Optional[ItemChange]:
    """A change to the captions above an item. The item's own row may be untouched and its scope
    still moved — General Preambles 2: the headings and sub-headings "identify the work covered by
    the respective items"."""
    if before.heading_path == after.heading_path:
        return None
    was = " / ".join(before.heading_path)
    now = " / ".join(after.heading_path)
    pairs = [(b, a) for b, a in zip(before.heading_path, after.heading_path) if b != a]
    if pairs and len(before.heading_path) == len(after.heading_path):
        edited = "; ".join(f"{b!r} → {a!r}" for b, a in pairs)
        detail = (f"the heading above this item changed: {edited}. The item's own row is unchanged, "
                  f"but a heading is part of what the item covers, so its scope moved")
    else:
        detail = f"the heading chain changed: {was!r} → {now!r}"
    return ItemChange(kind=CHANGE_HEADING, bill_no=after.bill_no, full_ref=after.full_ref,
                      before=was, after=now, detail=detail)


def _split_change(before: BillItem, after: BillItem,
                  variants: list[BillItem]) -> Optional[ItemChange]:
    """An item that became a parent — its quantity moved down into lettered variants.

    Reported as one change rather than as "quantity 91 → nothing" plus "unit 'nr' → ''", which is
    literally true and tells the estimator nothing. The variants' quantities are added up and
    compared against what the parent used to carry, because a split that does not reconcile is a
    different and much more serious event than a split that does.
    """
    if not (after.is_parent and not before.is_parent):
        return None
    total = sum(v.qty for v in variants if v.qty is not None)
    listed = ", ".join(f"{v.full_ref} {_qty_text(v)}" for v in variants) or "no variants found"
    detail = (f"item {after.full_ref} was split into priced variants: {listed}. It keeps its own "
              f"number and is no longer priced itself")
    if before.qty is not None:
        if abs(total - before.qty) < 1e-9:
            detail += f"; the variants add back to the {_num(before.qty)} {before.unit} it carried"
        else:
            detail += (f"; WARNING the variants total {_num(total)} against the "
                       f"{_num(before.qty)} {before.unit} it carried")
    return ItemChange(kind=CHANGE_QTY, bill_no=after.bill_no, full_ref=after.full_ref,
                      before=_qty_text(before), after=listed, detail=detail)


def _compare(before: BillItem, after: BillItem, variants: list[BillItem]) -> list[ItemChange]:
    changes: list[ItemChange] = []

    split = _split_change(before, after, variants)
    if split is not None:
        return [split]

    qty = _qty_change(before, after)
    if qty is not None:
        changes.append(qty)

    if before.description.strip() != after.description.strip():
        changes.append(ItemChange(
            kind=CHANGE_DESCRIPTION, bill_no=after.bill_no, full_ref=after.full_ref,
            before=before.description, after=after.description,
            detail=(f"description {before.description!r} → {after.description!r}; the quantity did "
                    f"not move, so the same rate now covers different work"
                    if before.qty == after.qty else
                    f"description {before.description!r} → {after.description!r}"),
        ))

    if before.unit != after.unit:
        changes.append(ItemChange(
            kind=CHANGE_UNIT, bill_no=after.bill_no, full_ref=after.full_ref,
            before=before.unit_raw, after=after.unit_raw,
            detail=(f"unit {before.unit!r} → {after.unit!r}; a rate carried across this has to be "
                    f"converted, not copied (GCT App C 2.2(v))"),
        ))

    heading = _heading_change(before, after)
    if heading is not None:
        changes.append(heading)

    if (before.client_rate, before.client_amount) != (after.client_rate, after.client_amount):
        changes.append(ItemChange(
            kind=CHANGE_PRE_PRICED, bill_no=after.bill_no, full_ref=after.full_ref,
            before=_num(before.client_rate), after=_num(after.client_rate),
            detail=(f"the rate the client inserted changed, {_num(before.client_rate)} → "
                    f"{_num(after.client_rate)}. A pre-priced item is not ours to price: the "
                    f"addendum's figure is the one to use (GCT App C 2.2(v))"),
        ))

    return changes


def diff_bills(before: ClientBill, after: ClientBill) -> BillDiff:
    """Compare two revisions of the bill, keyed on the item reference.

    ``moved_only`` collects the items that are identical in every respect but sit on a different
    row. They are separated out rather than dropped so the diff can say, honestly, that it looked at
    them and found nothing — 35 of them in the reference bill's first addendum.
    """
    old = {_key(item): item for item in before.items}
    new = {_key(item): item for item in after.items}

    changes: list[ItemChange] = []
    moved_only: list[str] = []
    unchanged = 0

    for key in sorted(new.keys() - old.keys()):
        item = new[key]
        changes.append(ItemChange(
            kind=CHANGE_ADDED, bill_no=item.bill_no, full_ref=item.full_ref,
            before="", after=f"{item.description} — {_qty_text(item)}".strip(" —"),
            detail=(f"new item {item.full_ref}, {_qty_text(item)}. Unpriced it carries a rate of "
                    f"zero and is deemed covered by the other rates (GCT App C 2.2(v))"
                    if not item.pre_priced else
                    f"new item {item.full_ref}, pre-priced by the client at "
                    f"{_num(item.client_rate)}; use the addendum's rate"),
        ))

    for key in sorted(old.keys() - new.keys()):
        item = old[key]
        changes.append(ItemChange(
            kind=CHANGE_DELETED, bill_no=item.bill_no, full_ref=item.full_ref,
            before=f"{item.description} — {_qty_text(item)}".strip(" —"), after="",
            detail=f"item {item.full_ref} is gone; any rate held against it no longer has anywhere "
                   f"to go (GCT App C 2.2(v))",
        ))

    variants: dict[str, list[BillItem]] = {}
    for item in after.items:
        if item.sub_ref:
            variants.setdefault(f"{item.bill_no}:{item.item_ref}", []).append(item)

    for key in sorted(old.keys() & new.keys()):
        item_changes = _compare(old[key], new[key], variants.get(key, []))
        if item_changes:
            changes.extend(item_changes)
            continue
        unchanged += 1
        if old[key].row != new[key].row:
            moved_only.append(new[key].full_ref)

    return BillDiff(from_rev=before.rev, to_rev=after.rev, changes=changes,
                    moved_only=moved_only, unchanged=unchanged)
