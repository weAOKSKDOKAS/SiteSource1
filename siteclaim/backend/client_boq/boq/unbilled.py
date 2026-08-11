"""BOQ — costs you believe in that the bill has no item for. They may not evaporate.

Bucket: **Rule** plus a **human gate**. Nothing here decides anything; it refuses to let a decision go
unmade.

WHY THIS IS A GATE AND NOT A LIST
----------------------------------
Leaving a cost unpriced feels like leaving a question open. On this contract it is not:

    General Preambles ¶6 — "Items against which no rate is entered shall be deemed to be covered by
    the other rates in the bill of quantities."

    Particular Preamble ¶12 / ¶4A — "Any item missed out from the item coverage shall not be measured
    unless it is expressly required to be measured under other provisions in the Method of
    Measurement."

    GCT Appendix C 2.2(iii) — at examination "the rate shall therefore be marked as zero".

**Silence is not neutral. Silence is a promise to do the work for nothing, for the life of a
remeasured contract.** So a believed cost with no bill item has to go somewhere, and there are exactly
four somewheres:

* **QUERY** — ask before the deadline. It works: a tenderer's question about rig classes is what
  produced the 2.2a / 2.2b split in Addendum No. 1 in the first place. Deadline is real, though —
  seven days before close (SCT 23), after which *"any queries received … will not be responded to"*.
* **LOAD** — put it on a named item whose coverage already reaches it. A Class B access platform
  belongs on the rig-move item, because SMM S02 ¶2.08(h) puts access scaffolding in that item's
  coverage and ¶2.03 measures moves per hole.
* **SPREAD** — into the pool that is shared across every priced rate. This is what the documents
  themselves instruct where they say there is no separate item: site uniform (PP ¶11/¶2A, *"There
  shall be no measurement or separate payment"*), the Subcontractor Management Plan (NTT C2), Pay for
  Safety to subcontractors (NTT C25).
* **ACCEPT** — carry it as a stated risk and rely on a compensation event if it materialises. The
  weakest of the four, because it is a claim and not an entitlement — so it must be recorded as a
  decision somebody made, with a reason.

The fifth option, doing nothing, is the one the gate exists to prevent.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from client_boq.estimate import money

ROUTE_QUERY = "query"
ROUTE_LOAD = "load"
ROUTE_SPREAD = "spread"
ROUTE_ACCEPT = "accept"
ROUTES = (ROUTE_QUERY, ROUTE_LOAD, ROUTE_SPREAD, ROUTE_ACCEPT)
#: Not a route — the bucket for costs that have none, so `by_route` accounts for every cost it was
#: given rather than quietly returning fewer than it holds. The fifth option is the one the gate
#: exists to prevent, and it has to be visible before you reach the gate.
ROUTE_NOWHERE = ""

ROUTE_MEANING = {
    ROUTE_QUERY: "asked of the client before the query deadline",
    ROUTE_LOAD: "priced into a named bill item whose coverage reaches it",
    ROUTE_SPREAD: "spread across the priced rates, as the documents instruct where there is no item",
    ROUTE_ACCEPT: "carried as a stated risk, to be claimed as a compensation event if it happens",
}

SILENCE_WARNING = (
    "Left unrouted this is priced at nothing, and General Preambles ¶6 deems an unpriced item "
    "'covered by the other rates' — work you have agreed to do for free for the life of the contract.")


class UnbilledCost(BaseModel):
    """Something the estimator believes he must do, with no bill item to put it in."""

    key: str = ""
    label: str = ""
    source: str = ""                    # the clause that put it on the list
    amount: Optional[float] = None      # what he thinks it costs; may be unknown when queried
    route: str = ""                     # blank = undecided, which is what the gate refuses
    target_ref: str = ""                # for ROUTE_LOAD: which bill item carries it
    reason: str = ""                    # required for ROUTE_ACCEPT — a risk taken needs a why
    decided_by: str = ""

    def problem(self) -> Optional[str]:
        """Why this one is not settled yet, or None."""
        if not self.route:
            return f"{self.label}: not routed. {SILENCE_WARNING}"
        if self.route not in ROUTES:
            return (f"{self.label}: {self.route!r} is not a route. "
                    f"Choose one of {', '.join(ROUTES)}.")
        if self.route == ROUTE_LOAD and not self.target_ref:
            return f"{self.label}: routed to a bill item, but no item named."
        if self.route == ROUTE_ACCEPT and not self.reason.strip():
            return (f"{self.label}: accepted as a risk with no reason recorded. A risk somebody took "
                    f"deliberately and one nobody noticed look identical six months later.")
        return None


class UnbilledSweep(BaseModel):
    """Every unbilled cost on this bill, and whether the estimator has dealt with all of them."""

    set_id: str = ""
    rev: int = 0
    costs: list[UnbilledCost] = Field(default_factory=list)

    def outstanding(self) -> list[str]:
        return [note for note in (cost.problem() for cost in self.costs) if note]

    def settled(self) -> bool:
        """Every believed cost has a route, AND somebody actually listed the costs.

        The `self.costs` guard is the whole of it. This read `not self.outstanding()`, and an empty
        cost list has nothing outstanding — so a sweep nobody had opened reported itself settled.
        That is not a corner case: the sweep is hand-typed and is never seeded from the build-up,
        so an EMPTY sweep is the normal state of a tender that has just been priced. "Nobody has
        looked" was reading as "looked, and clean" on every tender in the product.
        """
        return bool(self.costs) and not self.outstanding()

    def not_settled_because(self) -> str:
        """Why this sweep is not settled, in words. Empty when it is.

        A separate sentence rather than a flag, because the two reasons are different work: an
        empty sweep needs somebody to think about what the contract orders into the rates with no
        bill line, and an unrouted cost needs a decision about one cost already named.
        """
        if not self.costs:
            return ("nobody has listed the costs this contract orders into the rates with no bill "
                    "line — an empty sweep is where every tender starts, not a tender that has "
                    "been swept")
        return "; ".join(self.outstanding())

    def by_route(self) -> dict[str, list[UnbilledCost]]:
        """Every cost, in exactly one bucket. ``ROUTE_NOWHERE`` holds the ones with no valid route.

        It used to be ``if cost.route in out`` — so an undecided cost, or one with a typo'd route,
        fell through the loop and appeared in NO bucket. A screen rendering this showed fewer costs
        than the sweep holds, and the missing ones were precisely the unrouted ones this module
        exists to stop being forgotten. The gate would still have caught them, but only when
        somebody reached the gate; until then they were invisible on the way there.
        """
        out: dict[str, list[UnbilledCost]] = {name: [] for name in (*ROUTES, ROUTE_NOWHERE)}
        for cost in self.costs:
            out[cost.route if cost.route in ROUTES else ROUTE_NOWHERE].append(cost)
        return out

    def spread_total(self) -> float:
        """What goes into the pool, to be shared across every priced rate."""
        return money(sum(c.amount or 0.0 for c in self.costs if c.route == ROUTE_SPREAD))

    def loadings(self) -> dict[str, float]:
        """Extra cost per bill item, for the items that agreed to carry something."""
        out: dict[str, float] = {}
        for cost in self.costs:
            if cost.route == ROUTE_LOAD and cost.target_ref:
                out[cost.target_ref] = money(out.get(cost.target_ref, 0.0) + (cost.amount or 0.0))
        return out

    def queries(self) -> list[UnbilledCost]:
        """What to put in the next batch of questions, while the deadline is still open."""
        return [c for c in self.costs if c.route == ROUTE_QUERY]

    def accepted_risk(self) -> float:
        return money(sum(c.amount or 0.0 for c in self.costs if c.route == ROUTE_ACCEPT))


def gate(sweep: UnbilledSweep) -> None:
    """Raise unless every unbilled cost has been routed. Called before a bill revision is signed off.

    Deliberately a hard stop. Every other check in this package surfaces and lets the estimator carry
    on, because a flag he disagrees with should not block him. This one blocks, because the failure it
    guards against is not a wrong number — it is a number nobody ever wrote.
    """
    problems = sweep.outstanding()
    if problems:
        raise UnroutedCost(problems)


class UnroutedCost(RuntimeError):
    """One or more believed costs have nowhere to go."""

    def __init__(self, problems: list[str]) -> None:
        self.problems = problems
        count = len(problems)
        super().__init__(
            f"{count} cost{'s' if count != 1 else ''} you believe in {'have' if count != 1 else 'has'} "
            f"no home: " + " · ".join(problems))
