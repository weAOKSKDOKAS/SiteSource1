"""BOQ — is every cost recovered exactly once?

Bucket: **RULE.** Deterministic arithmetic over the join between the cost build-up and the priced
bill. No model, no rate book, no judgement. It reports; it never corrects.

WHY THIS EXISTS
---------------
The engine builds cost in one shape and recovers it in another. :mod:`client_boq.boq.buildup`
produces a handful of BASES — soil drilling, rig moves, the site team, grouting — each with a
direct cost and a divisor. :mod:`client_boq.boq.costing` then attaches each bill item to at most
one basis and prices it at that basis's ``cost_per_unit``. Nothing checked that the two sides
agree, and the join is where a tender quietly stops adding up.

    ``price()``:      ``row.direct_cost = item.qty * basis.cost_per_unit``
    ``build()``:      ``basis.cost_per_unit = basis.total_cost / basis.divisor``

So the whole law is one line:

    **a basis is recovered exactly once when the quantities of the items claiming it sum to its
    divisor.**

Anything else is money moving without anyone deciding it should. Two ways it goes wrong, both
observed on a probe of the shipped engine (2026-08-11, ``default_model``, a four-item bill):

* **NOTHING CLAIMS IT.** Eight of eleven bases had no bill item at all — standing time, the site
  team, mobilisation, setting out, sample tubes, core boxes, backfill grout — carrying
  **HK$5,264,157** of real direct cost between them. ``PricedBQ.unpriced`` was ``[]`` and
  ``placeholders`` was ``[]``: the engine reported the bill fully priced. That is the same failure
  :mod:`client_boq.boq.unbilled` was written to prevent, in the one place ``unbilled`` cannot see —
  its sweep is a hand-typed list, never seeded from the build-up.
* **THE CLAIMANTS DO NOT ADD UP.** A basis whose divisor came from ONE item can be claimed by
  several. Adding a second "material other than rock" item drawn from a different bill added
  **HK$720,000** to the tender for cost that was already fully recovered — no flag, no note.

Note what is NOT a defect: two items sharing a basis is normal and right. Rock and artificial hard
material are drilled by the same rig at the same cost per metre, so ¶2.13's rock basis is divided
by rock **plus** hard metres and claimed by both items — and the sum comes out exactly once. It is
the SUM that has to hold, never the count.

WHY IT REPORTS AND NEVER REPAIRS
--------------------------------
Every repair here is a commercial decision wearing arithmetic. A basis nothing claims might belong
in a preliminaries item, might belong spread across the rates, or might be work this contract does
not actually require — three different answers worth different money, and only the estimator knows
which. Silently pro-rating it would produce a total that looks right for a reason nobody chose.
So this module hands over the numbers and the names, and

    General Preambles ¶6 — "Items against which no rate is entered shall be deemed to be covered
    by the other rates in the bill of quantities."

is why the unrecovered case is the expensive direction: cost that reaches no rate is not saved, it
is given away for the life of a remeasured contract.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from client_boq.boq.buildup import Buildup
from client_boq.models import ClientBill

#: Under this many dollars, a difference is rounding in the divisor arithmetic rather than a
#: decision anyone made. Deliberately small: the failures this catches are in the millions, and a
#: generous tolerance is how a real leak learns to hide.
TOLERANCE = 1.0

GP6 = ('General Preambles ¶6 — "Items against which no rate is entered shall be deemed to be '
       'covered by the other rates in the bill of quantities."')


class BasisRecovery(BaseModel):
    """One cost basis, and how much of it the bill actually recovers."""

    key: str
    label: str
    direct_cost: float = 0.0
    divisor: float = 0.0
    divisor_name: str = ""
    #: The bill items whose rate is derived from this basis.
    claimed_by: list[str] = Field(default_factory=list)
    #: Their quantities, summed. A lump item (no quantity) counts as one.
    claimed_qty: float = 0.0
    #: ``cost_per_unit × claimed_qty`` — what the priced bill actually carries of this basis.
    recovered: float = 0.0

    def difference(self) -> float:
        """Positive = under-recovered (given away). Negative = over-recovered (charged twice)."""
        return round(self.direct_cost - self.recovered, 2)

    def clean(self) -> bool:
        return abs(self.difference()) <= TOLERANCE

    def problem(self) -> str:
        """Why this basis does not balance, in the estimator's terms. Empty when it does."""
        if self.clean():
            return ""
        gap = self.difference()
        if not self.claimed_by:
            return (f"{self.label} costs {self.direct_cost:,.2f} and NO bill item is priced from "
                    f"it — none of it reaches a rate. {GP6} Route it to an item, spread it across "
                    f"the rates, or say it is not required; leaving it here submits the work for "
                    f"nothing.")
        who = ", ".join(self.claimed_by)
        if gap > 0:
            return (f"{self.label}: item(s) {who} are priced from it and carry "
                    f"{self.claimed_qty:,.2f} of the {self.divisor:,.2f} "
                    f"{self.divisor_name or 'units'} it was divided by, so {gap:,.2f} of its "
                    f"{self.direct_cost:,.2f} reaches no rate. {GP6}")
        return (f"{self.label}: item(s) {who} carry {self.claimed_qty:,.2f} against the "
                f"{self.divisor:,.2f} {self.divisor_name or 'units'} it was divided by, so "
                f"{abs(gap):,.2f} of cost is recovered TWICE. The tender is that much high on "
                f"cost nobody spends — check whether the divisor should include their quantities.")


class Conservation(BaseModel):
    """The whole join: what the build-up costs, what the bill recovers, and every basis apart."""

    direct_cost: float = 0.0
    recovered: float = 0.0
    bases: list[BasisRecovery] = Field(default_factory=list)
    #: Bases that could form no rate at all (a zero divisor). They carry cost and cannot recover it,
    #: and `buildup` already says why on the row — repeated here so one screen holds the whole story.
    unformable: list[str] = Field(default_factory=list)

    def difference(self) -> float:
        return round(self.direct_cost - self.recovered, 2)

    def unrecovered(self) -> list[BasisRecovery]:
        return [b for b in self.bases if not b.claimed_by and b.direct_cost]

    def miscounted(self) -> list[BasisRecovery]:
        return [b for b in self.bases if b.claimed_by and not b.clean()]

    def clean(self) -> bool:
        return abs(self.difference()) <= TOLERANCE and not self.miscounted()

    def problems(self) -> list[str]:
        """Every basis that does not balance, worst money first. Empty when the bill conserves."""
        out = [b for b in self.bases if not b.clean()]
        out.sort(key=lambda b: abs(b.difference()), reverse=True)
        return [b.problem() for b in out]

    def headline(self) -> str:
        """One sentence for the top of a screen. Says nothing reassuring unless it is true."""
        if self.clean():
            return (f"Every basis balances: {self.direct_cost:,.2f} of direct cost is recovered "
                    f"exactly once across the priced items.")
        gap = self.difference()
        direction = ("reaches no rate at all" if gap > 0
                     else "is recovered more than once and is in the tender twice")
        return (f"{abs(gap):,.2f} of {self.direct_cost:,.2f} direct cost {direction}. "
                f"{len(self.unrecovered())} basis/bases have no bill item; "
                f"{len(self.miscounted())} do not sum to their divisor.")


def check(bill: ClientBill, buildup: Buildup, item_mappings: list) -> Conservation:
    """Join the build-up to the priced bill and report every basis that does not balance.

    ``item_mappings`` is what :func:`client_boq.boq.costing.propose_pricing` returns (after any
    human confirmation) — each carries ``full_ref`` and the ``basis_key`` its rate comes from.
    Only ``basis_key`` is checked: a laboratory or preliminaries rate is a per-unit figure from the
    rate book or the resource, not a pooled cost being divided up, so there is no pool to conserve.

    Pure: it reads, it returns, it changes nothing.
    """
    index = bill.index()
    claims: dict[str, list[str]] = {}
    for mapping in item_mappings or []:
        key = getattr(mapping, "basis_key", "") or ""
        ref = getattr(mapping, "full_ref", "") or ""
        if key and ref:
            claims.setdefault(key, []).append(ref)

    report = Conservation()
    for row in buildup.rows:
        refs = claims.get(row.key, [])
        # A lump/no-divisor basis hands its WHOLE cost to each claiming item, so the quantity that
        # matters is the number of claimants, and its "divisor" is one.
        divides = bool(row.divisor)
        qty = 0.0
        for ref in refs:
            item = index.get(ref)
            if item is None:
                continue
            qty += (item.qty if (divides and item.qty is not None) else 1.0)

        per_unit = row.cost_per_unit
        basis = BasisRecovery(
            key=row.key, label=row.label or row.key,
            direct_cost=round(row.total_cost or 0.0, 2),
            divisor=round(row.divisor or (1.0 if refs else 0.0), 2),
            divisor_name=row.divisor_name,
            claimed_by=refs, claimed_qty=round(qty, 2),
            recovered=round((per_unit or 0.0) * qty, 2),
        )
        if per_unit is None and (row.total_cost or 0.0):
            # No rate could be formed (a zero divisor). The cost is real and recovers nothing;
            # `buildup` already carries the reason on the row.
            report.unformable.append(row.key)
        report.bases.append(basis)

    report.direct_cost = round(sum(b.direct_cost for b in report.bases), 2)
    report.recovered = round(sum(b.recovered for b in report.bases), 2)
    return report
