"""BOQ — the derivation tree: how a rate was reached, down to the document it came from.

Bucket: **Deterministic presentation.** Nothing here computes a price. It restates one that
:mod:`client_boq.boq.allocate` already produced, as a tree a person can walk.

WHY A TREE RATHER THAN A NUMBER
-------------------------------
This is the module that decides whether the estimator trusts the app, and the argument is simple: he
can already do this work. He will only hand any of it over if checking the app is faster than doing
it himself. So a rate is never shown as a rate. It is shown as::

    RATE  1,104.15 / m
    = cost 2,539,545 ÷ 2,300 m                        ✓ extension checks
        cost = build-up 2,208,300 × 1.15 margin         ▸ change
        build-up = Σ groups
          ▸ Roadside  68 holes  1,780 m  1,540,200
          ▸ Hillside  23 holes    520 m    668,100
        2,300 m ← Σ soil depths, GI/210 · 91 stations  ▸ show me
        1.15    ← your margin, set 3 Aug by J. Dai     ▸ change

Three clicks and it is verified, or he has found where it is wrong. Both outcomes are worth more than
a number he has to take on faith.

THE RULE THAT MAKES IT WORK
---------------------------
**A leaf with no citation and no owner is a bug.** Every number at the bottom of the tree came from
exactly one of three places, and the node says which:

* a **document** — the drawing, the bill, the specification. It carries a page and opens.
* a **person** — the margin, an output, a class of site. It carries a name and a date.
* the **library** — a rate or a norm. It carries which, and whether this tender overrode it.

A node that cannot say which of those it is has no business standing behind a price.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from client_boq.boq.allocate import RateBreakdown
from client_boq.boq.groups import HoleGroup
from client_boq.boq.schedule import StationSchedule

# What a leaf rests on — and therefore what clicking it does.
FROM_DOCUMENT = "document"      # ▸ show me — opens the page, highlighted
FROM_PERSON = "person"          # ▸ change — it was somebody's decision
FROM_LIBRARY = "library"        # ▸ change — the book's, unless this tender overrode it
FROM_COMPUTED = "computed"      # a branch: it is the arithmetic over its children


class Citation(BaseModel):
    """Where to open. Empty fields mean the app does not know, which it says rather than guesses."""

    part_id: str = ""
    page: int = 0
    quote: str = ""
    label: str = ""             # "GI/210 · 91 stations"


class TraceNode(BaseModel):
    """One line of the derivation. Children are what it is made of."""

    label: str
    value: Optional[float] = None
    unit: str = ""
    # The arithmetic joining the children, printed as written: "Σ", "×", "÷". Empty on a leaf.
    op: str = ""
    formula: str = ""
    origin: str = FROM_COMPUTED
    cite: Optional[Citation] = None
    owner: str = ""             # the person, when origin is FROM_PERSON
    source: str = ""            # "book" | "yours" | "missing", when origin is FROM_LIBRARY
    note: str = ""
    children: list["TraceNode"] = Field(default_factory=list)

    def leaves(self) -> list["TraceNode"]:
        if not self.children:
            return [self]
        return [leaf for child in self.children for leaf in child.leaves()]

    def unsupported(self) -> list[str]:
        """Leaves that cannot say where they came from. Every one of these is a bug.

        The check exists because it is the only way to keep the promise the screen makes. A tree with
        one unattributed leaf still looks complete, and looking complete is exactly the failure.
        """
        problems = []
        for leaf in self.leaves():
            if leaf.origin == FROM_DOCUMENT and (leaf.cite is None or not leaf.cite.part_id):
                problems.append(f"{leaf.label!r} claims a document but names no page")
            elif leaf.origin == FROM_PERSON and not leaf.owner:
                problems.append(f"{leaf.label!r} was somebody's decision but nobody's name is on it")
            elif leaf.origin == FROM_COMPUTED and leaf.value is not None:
                problems.append(f"{leaf.label!r} is a bare number with nothing behind it")
        return problems


TraceNode.model_rebuild()


class RateTrace(BaseModel):
    """One item's rate, and everything under it."""

    full_ref: str = ""
    description: str = ""
    rate: Optional[float] = None
    unit: str = ""
    qty: float = 0.0
    amount: Optional[float] = None
    root: Optional[TraceNode] = None
    checks: list[str] = Field(default_factory=list)
    problems: list[str] = Field(default_factory=list)

    def extension_checks(self) -> bool:
        """Whether rate × quantity actually is the amount. The cheapest check in the bill, and the
        one an arithmetically-checked tender is disqualified for failing."""
        if self.rate is None or self.amount is None:
            return False
        return abs(self.rate * self.qty - self.amount) < 0.01


def trace_rate(breakdown: RateBreakdown, *, description: str = "", unit: str = "", qty: float = 0.0,
               amount: Optional[float] = None, margin_pct: float = 0.0,
               margin_owner: str = "", margin_at: str = "",
               groups: Optional[list[HoleGroup]] = None,
               schedule: Optional[StationSchedule] = None,
               divisor_cite: Optional[Citation] = None,
               spread_share: float = 0.0, spread_total: float = 0.0) -> RateTrace:
    """Turn a priced item into a tree.

    ``spread_share`` is the item's slice of the sweep pool. It is shown as its **own line** rather
    than folded into the build-up: a spread has to reach the tendered rates or the tender total is
    wrong — you cannot tender "plus 52,000" — but a spread hidden inside a metre rate is precisely
    the thing this screen exists to expose. So it lands in the rate and says so.
    """
    trace = RateTrace(full_ref=breakdown.full_ref, description=description or breakdown.label,
                      rate=breakdown.rate, unit=unit, qty=qty, amount=amount)

    build_up = TraceNode(
        label="build-up", value=breakdown.cost, op="Σ", origin=FROM_COMPUTED,
        children=_group_nodes(breakdown, groups) or _term_nodes(breakdown),
    )

    cost_children = [build_up]
    if spread_share:
        cost_children.append(TraceNode(
            label="spread share", value=round(spread_share, 2), origin=FROM_PERSON,
            owner=margin_owner,
            note=(f"this item's slice of the {spread_total:,.2f} you chose to spread on the sweep. "
                  f"It is inside the rate — it has to be, or the tender total is wrong — and it is "
                  f"on its own line so it is not hiding in the metres."),
        ))
    if margin_pct:
        cost_children.append(TraceNode(
            label=f"× {1 + margin_pct / 100:.2f} margin", value=margin_pct, unit="%",
            origin=FROM_PERSON, owner=margin_owner,
            note=f"your margin{f', set {margin_at}' if margin_at else ''}. A commercial decision.",
        ))

    cost = TraceNode(label="cost", value=breakdown.cost, op="+", origin=FROM_COMPUTED,
                     children=cost_children)

    if breakdown.lump:
        root = TraceNode(
            label="rate", value=breakdown.rate, unit=unit, op="=", origin=FROM_COMPUTED,
            formula=breakdown.formula, children=[cost],
            note="A lump item: the amount IS the rate (SMM Corr. 1/2007 Part III ¶3).")
    else:
        divisor = TraceNode(
            label=breakdown.divisor_label or "quantity", value=breakdown.divisor, unit=unit,
            origin=FROM_DOCUMENT if divisor_cite else FROM_COMPUTED, cite=divisor_cite,
            note=_divisor_note(schedule, breakdown.divisor_label),
        )
        root = TraceNode(label="rate", value=breakdown.rate, unit=unit, op="÷",
                         origin=FROM_COMPUTED, formula=breakdown.formula,
                         children=[cost, divisor])

    trace.root = root
    trace.problems = root.unsupported()
    if trace.extension_checks():
        trace.checks.append("extension checks — rate × quantity is the amount")
    elif trace.rate is not None and trace.amount is not None:
        trace.problems.append(
            f"the extension does not check: {trace.rate:,.2f} × {trace.qty:,g} is not "
            f"{trace.amount:,.2f}")
    if trace.rate is None:
        trace.problems.append(
            "no rate could be formed, so this item is unpriced — and General Preambles ¶6 deems an "
            "unpriced item covered by the other rates, which is work you have agreed to do for free.")
    return trace


def _group_nodes(breakdown: RateBreakdown, groups: Optional[list[HoleGroup]]) -> list[TraceNode]:
    """One child per hole group on a blended rate — the estimator's first question is which group is
    carrying it, and the answer belongs on screen rather than behind another query."""
    if not breakdown.groups:
        return []
    by_label = {g.label: g for g in (groups or [])}
    nodes = []
    for entry in breakdown.groups:
        group = by_label.get(entry["group"])
        divisor = entry.get("divisor") or 0.0
        nodes.append(TraceNode(
            label=entry["group"], value=entry["cost"], origin=FROM_PERSON,
            owner=(group.badge if group else "") or "",
            note=(f"{group.hole_count} holes · {divisor:,g} {breakdown.divisor_label} · "
                  f"{entry['cost'] / divisor:,.2f} each" if group and divisor else ""),
        ))
    return nodes


def _term_nodes(breakdown: RateBreakdown) -> list[TraceNode]:
    """One child per resource on a single-group rate: `rate × quantity × coefficient`, spelled out."""
    return [
        TraceNode(
            label=term["label"], value=term["value"], origin=FROM_LIBRARY, source="book",
            formula=f"{term['unit_cost']:,.2f} × {term['units']:,g}",
            note=f"resource {term['key']}",
        )
        for term in breakdown.terms
    ]


def _divisor_note(schedule: Optional[StationSchedule], label: str) -> str:
    """Say where a bill quantity came from, when the take-off can account for it."""
    if schedule is None:
        return ""
    if label.startswith("m") and schedule.soil_m():
        return (f"Σ soil depths across {schedule.hole_count()} stations, "
                f"{schedule.source_sheet or 'the borehole details schedule'}")
    return ""
