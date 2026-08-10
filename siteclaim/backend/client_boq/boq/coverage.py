"""BOQ — what a rate must cover, and who says it does.

Bucket: **Deterministic list, human verdict.** Assembling the heads is clerical retrieval and a rule
does it. Deciding whether *your* build-up already carries one of them is judgement, and only a person
does it. **Nothing here is ever pre-ticked.**

WHY THE LIST EXISTS
-------------------
    General Preambles ¶2 — "The exact nature and extent of an item of work must be ascertained by
    reference to the Drawings and Specification … the item of work described is deemed to include for
    all requirements shown on all Drawings and/or Specification pertaining to that item of work
    irrespective of whether or not the Drawing and/or Specification is stated in the item description
    or item coverage."

So a metre of item 2.4 is not a metre of drilling. It is a metre of logged, stabilised, cased,
traffic-managed drilling, including reaming of casing, disposal of surplus, the routine small
disturbed samples, the readings, and the logs. Price the metre and forget the logging and you have
priced perhaps 60% of something you are bound to deliver in full — and there is no later claim for it:

    Particular Preamble ¶12 / ¶4A — "Any item missed out from the item coverage shall not be
    measured."

WHY THE TICKS ARE THE HUMAN'S
-----------------------------
A machine cannot know what you put in your number. It can see that your sheet has a line called
"traffic management crew"; it cannot know whether that line was sized for this item or for the
compound. Two good estimators would disagree about it — which is the test this whole product uses to
decide what to automate — so it is asked, never assumed.

Three unticked heads is not an error. It is a decision waiting, and :mod:`client_boq.boq.unbilled` is
where those decisions get made.

THE HEADS ARE A TRANSCRIPTION, AND ARE MEANT TO BE CORRECTED
------------------------------------------------------------
:data:`SECTION_COVERAGE` below is the reference contract's, read off the Standard Method of
Measurement and its Particular Preambles. It is **data, not law**: another contract measures
differently, and every head carries the clause that produced it so a wrong transcription shows up the
moment somebody clicks through to the page. A head whose clause the specification index cannot
resolve says so rather than pretending to a page number.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from client_boq.boq.docmap import DocumentMap
from client_boq.models import BillItem, ClientBill

# Who put a head on the list — the authorship triad, in the two flavours it can take here.
BY_RULE = "rule"        # read off a structured list: the item coverage, or the preambles
BY_MODEL = "model"      # a model proposed that this clause bears on the item. Still needs a tick.

# The scope a head applies to.
SCOPE_ITEM = "item"     # this bill item only
SCOPE_BILL = "bill"     # every item in the contract — ticked once, not 27 times


class CoverageHead(BaseModel):
    """One thing a rate is deemed to include, and the clause that says so."""

    key: str                        # "smm.2.13.a" — stable, so a tick survives a re-read
    label: str
    clause_ref: str = ""            # "SMM S02 ¶2.13(a)", "PS 7.30S"
    cites: str = ""                 # a specification clause to resolve through the index
    authored_by: str = BY_RULE
    scope: str = SCOPE_ITEM


# ---------------------------------------------------------------------------
# The reference contract's item coverage, by bill section.
#
# Keyed on the section a bill item belongs to, because that is how the Method of Measurement is
# organised — Section 2 is Ground Investigation Fieldworks, and every drilling item in it carries the
# same coverage.
# ---------------------------------------------------------------------------
SECTION_COVERAGE: dict[str, list[CoverageHead]] = {
    "2": [
        CoverageHead(key="smm.2.13.a", label="Stabilising and supporting the hole",
                     clause_ref="SMM S02 ¶2.13(a)"),
        CoverageHead(key="smm.2.13.b", label="Casing, and reaming of casing",
                     clause_ref="SMM S02 ¶2.13(b)"),
        CoverageHead(key="smm.2.13.c", label="Disposal of surplus material",
                     clause_ref="SMM S02 ¶2.13(c)"),
        CoverageHead(key="smm.2.13.d", label="Routine small disturbed samples, taken and submitted",
                     clause_ref="SMM S02 ¶2.13(d)"),
        CoverageHead(key="smm.2.13.e", label="Taking readings",
                     clause_ref="SMM S02 ¶2.13(e)"),
        CoverageHead(key="smm.2.13.f", label="Logging the hole",
                     clause_ref="SMM S02 ¶2.13(f)"),
        CoverageHead(key="smm.2.13.g", label="Supplying the logs and records of the hole",
                     clause_ref="SMM S02 ¶2.13(g)"),
        CoverageHead(key="smm.2.13.h", label="Temporary traffic arrangements",
                     clause_ref="SMM S02 ¶2.13(h)"),
        CoverageHead(key="ps.7.30S", label="An inspection pit before drilling starts",
                     clause_ref="PS 7.30S", cites="7.30S"),
        CoverageHead(key="ps.7.45D", label="Over-drilling, which is at the Contractor's expense",
                     clause_ref="PS 7.45D", cites="7.45D"),
    ],
}

# Coverage that belongs to one item rather than to a whole section.
ITEM_COVERAGE: dict[str, list[CoverageHead]] = {
    "2.2a": [CoverageHead(key="smm.2.08.h", label="Access scaffolding and temporary platforms",
                          clause_ref="SMM S02 ¶2.08(h)", cites="7.01A")],
    "2.2b": [CoverageHead(key="smm.2.08.h", label="Access scaffolding and temporary platforms",
                          clause_ref="SMM S02 ¶2.08(h)", cites="7.01A")],
}

# The heads deemed included in EVERY rate in the contract: General Preambles ¶2 (i)–(xxii), twenty-two
# of them, and Particular Preambles ¶¶7–10, nine more. Thirty-one.
#
# Ticked once at bill level, not repeated against all twenty-seven items. Listing thirty-one heads on
# every item would bury the eight or ten that are actually about THIS item, and the count in the
# header — "12 heads · 3 not covered" — is only useful while it is a number somebody can act on.
DEEMED_INCLUDED = CoverageHead(
    key="preambles.deemed",
    label="The 31 heads deemed included in every rate",
    clause_ref="GP ¶2(i)–(xxii) · PP ¶¶7–10",
    scope=SCOPE_BILL,
)

# The rule that makes an untidied list expensive rather than merely untidy.
NO_LATER_CLAIM = ("Particular Preamble ¶12 / ¶4A — \"Any item missed out from the item coverage "
                  "shall not be measured.\" There is no later claim for a forgotten cost.")


class CoverageEntry(BaseModel):
    """A head, resolved against the specification, with whatever verdict a person has given it."""

    key: str
    label: str
    clause_ref: str = ""
    authored_by: str = BY_RULE
    scope: str = SCOPE_ITEM

    # Where to open. Empty when the index could not resolve the citation — which is reported rather
    # than filled with a plausible page, because a `▸ show me` that lands on the wrong page is worse
    # than one that admits it does not know.
    page: str = ""
    document_hint: str = ""
    unresolved: str = ""

    ticked: bool = False
    ticked_by: str = ""
    ticked_at: Optional[str] = None

    def covered(self) -> bool:
        return self.ticked


class ItemCoverage(BaseModel):
    """Everything one bill item's rate must carry, and how much of it is accounted for."""

    full_ref: str = ""
    description: str = ""
    entries: list[CoverageEntry] = Field(default_factory=list)
    bill_level: Optional[CoverageEntry] = None
    note: str = NO_LATER_CLAIM
    #: WHY THIS FIELD EXISTS. `SECTION_COVERAGE` is a transcription of the printed item coverage,
    #: and only Bill No.2's has been transcribed. Every item in the other four bills therefore
    #: produced ZERO heads — and zero heads with zero uncovered read as "all covered", so four
    #: fifths of the bill reported itself fully settled because nobody had written its checklist
    #: down. Absence looked exactly like completeness, which is the failure this whole package is
    #: built against. An item with no list now says so and cannot settle.
    no_list_for_section: str = ""

    def total(self) -> int:
        return len(self.entries)

    def uncovered(self) -> list[CoverageEntry]:
        return [e for e in self.entries if not e.covered()]

    def summary(self) -> str:
        """The header line: `12 heads · 3 not covered`, or `12 heads · all covered`."""
        if self.no_list_for_section:
            return f"no item-coverage list transcribed for Bill No.{self.no_list_for_section}"
        missing = len(self.uncovered())
        return (f"{self.total()} heads · {missing} not covered" if missing
                else f"{self.total()} heads · all covered")

    def settled(self) -> bool:
        """Whether every head has a person's tick against it. Never a gate — a decision waiting.

        An item with NO list is never settled. Not because anything is wrong with it, but because
        nobody has yet said what its rate must carry, and "nothing to check" and "checked" are
        different states that were previously indistinguishable.
        """
        return not self.no_list_for_section and not self.uncovered()


def section_of(item: BillItem) -> str:
    """Which bill's item coverage governs this item."""
    return (item.bill_no or item.full_ref.split(".", 1)[0]).strip()


def has_list_for(item: BillItem) -> bool:
    """Whether the printed item coverage for this item's bill has been transcribed at all.

    The distinction `heads_for` cannot make on its own: an empty list means "this bill's coverage
    was never written down here", not "this item's rate carries nothing".
    """
    return section_of(item) in SECTION_COVERAGE or item.full_ref in ITEM_COVERAGE


def heads_for(item: BillItem) -> list[CoverageHead]:
    """The heads that apply to one bill item, before any verdict.

    Section coverage plus anything specific to the item. Deterministic: the same item always produces
    the same list, which is what lets a tick be keyed to a head and survive a re-read.

    An empty return is AMBIGUOUS by itself — see `has_list_for`, which is what separates "nothing to
    check" from "nobody has said what to check".
    """
    return [*SECTION_COVERAGE.get(section_of(item), []), *ITEM_COVERAGE.get(item.full_ref, [])]


def coverage_for(item: BillItem, *, docmap: Optional[DocumentMap] = None,
                 ticks: Optional[dict[str, dict]] = None,
                 proposed: Optional[list[CoverageHead]] = None) -> ItemCoverage:
    """Assemble one item's checklist, resolve its citations, and apply the ticks already recorded.

    ``proposed`` is where a model's contribution enters — heads it believes bear on this item that the
    printed coverage does not name. They arrive marked ``model`` (brass) and, like every other head,
    **unticked**. A model may widen the list; it may never shorten it and it may never settle it.
    """
    recorded = ticks or {}
    entries: list[CoverageEntry] = []

    for head in [*heads_for(item), *(proposed or [])]:
        entry = CoverageEntry(key=head.key, label=head.label, clause_ref=head.clause_ref,
                              authored_by=head.authored_by, scope=head.scope)
        if head.cites and docmap is not None:
            found = docmap.resolve(head.cites)
            if found is None:
                entry.unresolved = (f"{head.cites} is cited by the item coverage but the "
                                    f"specification index does not list it")
            else:
                entry.page = found.page
                entry.document_hint = found.document_hint()
        elif head.cites:
            entry.unresolved = "the specification index has not been read for this set"

        mark = recorded.get(head.key)
        if mark:
            entry.ticked = bool(mark.get("ticked"))
            entry.ticked_by = mark.get("ticked_by", "")
            entry.ticked_at = mark.get("ticked_at")
        entries.append(entry)

    bill_mark = recorded.get(DEEMED_INCLUDED.key, {})
    bill_level = CoverageEntry(
        key=DEEMED_INCLUDED.key, label=DEEMED_INCLUDED.label,
        clause_ref=DEEMED_INCLUDED.clause_ref, scope=SCOPE_BILL,
        ticked=bool(bill_mark.get("ticked")), ticked_by=bill_mark.get("ticked_by", ""),
        ticked_at=bill_mark.get("ticked_at"))

    return ItemCoverage(full_ref=item.full_ref, description=item.description,
                        entries=entries, bill_level=bill_level,
                        # A model's proposed heads DO make a list where there was none: somebody
                        # has now said what this rate must carry, and the heads arrive unticked
                        # like every other, so nothing is settled by their arrival.
                        no_list_for_section=("" if (has_list_for(item) or proposed)
                                             else section_of(item)))


def bill_summary(bill: ClientBill, ticks: dict[str, dict[str, dict]]) -> dict:
    """How much of the whole bill's coverage has been settled, item by item.

    ``ticks`` is keyed full_ref → head key → mark, which is the shape the store returns. Parents and
    the client's own pre-priced items are skipped: neither carries a rate of yours.
    """
    rows = []
    for item in bill.items:
        if item.is_parent or item.pre_priced:
            continue
        coverage = coverage_for(item, ticks=ticks.get(item.full_ref, {}))
        rows.append({"full_ref": item.full_ref, "total": coverage.total(),
                     "uncovered": len(coverage.uncovered()), "settled": coverage.settled(),
                     "no_list_for_section": coverage.no_list_for_section})
    no_list = sorted({r["no_list_for_section"] for r in rows if r["no_list_for_section"]})
    return {
        "items": rows,
        "settled": sum(1 for r in rows if r["settled"]),
        "outstanding": sum(r["uncovered"] for r in rows),
        # COUNTED SEPARATELY, not folded into `outstanding`. An item waiting for a tick and an item
        # whose checklist was never written are different problems with different owners, and
        # adding them together would hide the second inside the first.
        "no_list": sum(1 for r in rows if r["no_list_for_section"]),
        "bills_without_a_list": no_list,
        "note": NO_LATER_CLAIM,
    }
