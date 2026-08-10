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

# ---------------------------------------------------------------------------
# WHERE A HEAD'S WORDS CAME FROM — and the gap this pack cannot close
# ---------------------------------------------------------------------------
# The tender pack carries this contract's **amendments** to the Standard Method of Measurement for
# Civil Engineering Works (1992): "Delete paragraph 2.13(d) and substitute…", "Add the following to
# paragraph 2.35…". **The base SMM 1992 is not in the pack.** So for every clause below, the
# sub-heads the base defines are real, are binding, and are INVISIBLE HERE.
#
# Every list in this module is therefore partial by construction, and that has to be said out loud.
# An empty list reading as "fully covered" was a bug fixed a commit ago; a PARTIAL list reading as
# complete is the same bug wearing a longer coat.
FROM_AMENDMENT = "amendment"    # quoted verbatim from this contract's SMM Particular Preambles
FROM_BASE_SMM = "base_smm"      # the clause exists; its text is in SMM 1992, which is NOT in the pack

BASE_SMM_UNVERIFIABLE = (
    "This head's wording comes from the base Standard Method of Measurement for Civil Engineering "
    "Works (1992), which is NOT in this tender pack — the pack carries only this contract's "
    "amendments to it. The head is real and binding; its exact words cannot be checked from here.")

PARTIAL_BY_CONSTRUCTION = (
    "This list is the pack's AMENDMENTS to the SMM, not the whole item coverage. The base SMM 1992 "
    "is not in the pack, so its sub-heads under the same clause are binding and unlisted. Closing "
    "the gap needs the base SMM document.")


class CoverageHead(BaseModel):
    """One thing a rate is deemed to include, and the clause that says so."""

    key: str                        # "smm.s02.2.13.e" — stable, so a tick survives a re-read
    label: str
    clause_ref: str = ""            # "SMM S02 ¶2.13(e)", "PS 7.30S"
    cites: str = ""                 # a specification clause to resolve through the index
    authored_by: str = BY_RULE
    scope: str = SCOPE_ITEM
    #: Whether these words were read from the pack or belong to the base SMM nobody here has.
    provenance: str = FROM_AMENDMENT


class CoverageList(BaseModel):
    """One bill's transcribed coverage, the SMM clause it came from, and how complete it is.

    A bare ``list[CoverageHead]`` could not say "these are the amendments only" — and a parallel
    dict of caveats beside a dict of heads is the hand-maintained-copy trap this codebase keeps
    warning about. So the caveat travels WITH the heads.
    """

    bill_no: str = ""
    smm_clause: str = ""            # "SMM S02 ¶2.13" — the clause the whole list came from
    title: str = ""                 # what the bill is, in the bill's own words
    heads: list[CoverageHead] = Field(default_factory=list)
    #: Why this list is not the whole coverage. Empty would mean complete — nothing is, yet.
    partial: str = PARTIAL_BY_CONSTRUCTION


class TitleRule(BaseModel):
    """Coverage that attaches by what an item IS CALLED, not by its number.

    THE RULE THIS EXISTS FOR. A BQ item number is not an SMM clause number: BQ 1.12 is *Contract
    Computer Facilities* while SMM ¶1.12 is something else entirely. SMM 1 carries 42 item-coverage
    blocks, one per preliminaries item, and the only thing that lines a block up with a BQ item is
    the TITLE. The same is true of Bills 7, 8 and 9, whose clauses are named by what they govern.

    So the mapping is resolved against the item's description at read time rather than hard-coded
    to BQ references this transcription does not have. ``match`` requires EVERY phrase, and the
    phrases are chosen to be distinctive — a loose matcher would attach the core-store heads to the
    insurance item, which is exactly the failure a per-item list exists to prevent.
    """

    key: str                        # stable id for the rule itself, so a miss can be reported
    bill_no: str = ""               # "" matches any bill; set it when a title could recur
    match: tuple[str, ...] = ()     # every phrase must appear, case-insensitively
    smm_clause: str = ""
    title: str = ""                 # what the clause governs, in the pack's words
    heads: list[CoverageHead] = Field(default_factory=list)
    partial: str = PARTIAL_BY_CONSTRUCTION

    def matches(self, item: BillItem) -> bool:
        if self.bill_no and (item.bill_no or "").strip() != self.bill_no:
            return False
        text = f"{item.description}".lower()
        return bool(self.match) and all(phrase.lower() in text for phrase in self.match)


# ---------------------------------------------------------------------------
# The reference contract's item coverage, by bill section.
#
# Keyed on the section a bill item belongs to, because that is how the Method of Measurement is
# organised — Section 2 is Ground Investigation Fieldworks, and every drilling item in it carries the
# same coverage.
# ---------------------------------------------------------------------------
#
# ⚠ THE LETTERS ARE THIS CONTRACT'S, NOT THE BASE SMM's. The first transcription lettered these
# (a)–(h) in reading order. The pack does not letter them that way: it SUBSTITUTES 2.13(d) and then
# ADDS (e)–(j), so the content that was here as (a) is really (e), (b) is (f), and so on. The
# content was right and the references were wrong — which matters exactly as much as this module's
# own docstring says it does, because "a wrong transcription shows up the moment somebody clicks
# through to the page" only works if the reference points at the right sub-clause.
#
# Verbatim from SMM_S02 Particular Preambles:
#   Delete paragraph 2.13(d) and substitute: (d) taking readings, measurements and observations,
#   and recording and supplying the logs and other records of each drillhole, borehole or probehole
#   to the Project Manager.
#   Add the following to paragraph 2.13: (e) stabilising the hole; (f) reaming of casing;
#   (g) disposal of surplus material; (h) drilling using 4C-MLC core barrel as required;
#   (i) taking and submitting small disturbed samples to the Project Manager; (j) providing,
#   maintaining and removing temporary traffic arrangement in accordance with PS Clauses 1.14–1.15.
#
_DRILLING_2_13 = [
    # 2.13(d) is ONE substituted clause covering four acts. It is carried as three heads rather
    # than one because the estimator TICKS these — "have I priced the logging?" and "have I priced
    # supplying the logs?" are two different questions with two different answers, and a single
    # tick would settle both on the strength of whichever one they were thinking about. All three
    # carry the same clause_ref, so clicking any of them lands on the right sub-clause.
    CoverageHead(key="smm.s02.2.13.d.readings",
                 label="Taking readings, measurements and observations",
                 clause_ref="SMM S02 ¶2.13(d)"),
    CoverageHead(key="smm.s02.2.13.d.recording",
                 label="Recording the logs and other records of each hole",
                 clause_ref="SMM S02 ¶2.13(d)"),
    CoverageHead(key="smm.s02.2.13.d.supplying",
                 label="Supplying the logs and other records to the Project Manager",
                 clause_ref="SMM S02 ¶2.13(d)"),
    CoverageHead(key="smm.s02.2.13.e", label="Stabilising the hole",
                 clause_ref="SMM S02 ¶2.13(e)"),
    CoverageHead(key="smm.s02.2.13.f", label="Reaming of casing",
                 clause_ref="SMM S02 ¶2.13(f)"),
    # CASING ITSELF is not in any amendment quoted in the pack — only "reaming of casing" is. The
    # first transcription carried "Casing, and reaming of casing" as one head, so deleting the
    # casing half would delete a real cost on the strength of a document nobody here has read.
    # It is kept, marked base-SMM, and its words are declared unverifiable rather than quoted as
    # though they came from the pack.
    CoverageHead(key="smm.s02.2.13.base.casing", label="Casing",
                 clause_ref="SMM S02 ¶2.13 (base SMM 1992 sub-head)",
                 provenance=FROM_BASE_SMM),
    CoverageHead(key="smm.s02.2.13.g", label="Disposal of surplus material",
                 clause_ref="SMM S02 ¶2.13(g)"),
    CoverageHead(key="smm.s02.2.13.h",
                 label="Drilling using 4C-MLC core barrel as required",
                 clause_ref="SMM S02 ¶2.13(h)"),
    CoverageHead(key="smm.s02.2.13.i",
                 label="Taking and submitting small disturbed samples to the Project Manager",
                 clause_ref="SMM S02 ¶2.13(i)"),
    CoverageHead(key="smm.s02.2.13.j",
                 label="Providing, maintaining and removing temporary traffic arrangement",
                 clause_ref="SMM S02 ¶2.13(j) · PS 1.14–1.15", cites="1.14"),
    CoverageHead(key="ps.7.30S", label="An inspection pit before drilling starts",
                 clause_ref="PS 7.30S", cites="7.30S"),
    CoverageHead(key="ps.7.45D", label="Over-drilling, which is at the Contractor's expense",
                 clause_ref="PS 7.45D", cites="7.45D"),
]

# ---------------------------------------------------------------------------
# Laboratory testing â Â¶2.35 (Bills 4 and 5)
# ---------------------------------------------------------------------------
# Verbatim from SMM_S02 Particular Preambles:
#   2.35(b) (substituted) calibration of instruments and submission of calibration certificates;
#   2.35(g) disposal of samples and cores or transporting samples and cores to Project Manager's
#   store as directed by the Project Manager;
#   2.35(h) complying with all the requirements as specified in PS Section 31 for laboratory
#   testing.
_LABORATORY_2_35 = [
    CoverageHead(key="smm.s02.2.35.b",
                 label="Calibration of instruments and submission of calibration certificates",
                 clause_ref="SMM S02 ¶2.35(b)"),
    CoverageHead(key="smm.s02.2.35.g",
                 label="Disposal of samples and cores, or transporting them to the Project "
                       "Manager's store as directed",
                 clause_ref="SMM S02 ¶2.35(g)"),
    CoverageHead(key="smm.s02.2.35.h",
                 label="Complying with all the requirements of PS Section 31 for laboratory "
                       "testing",
                 clause_ref="SMM S02 ¶2.35(h) · PS Section 31", cites="31"),
]

# ---------------------------------------------------------------------------
# Instrument installation / groundwater monitoring â ¶2.30 (Bill 6)
# ---------------------------------------------------------------------------
# Verbatim from SMM_S02 Particular Preambles.
_INSTRUMENTS_2_30 = [
    CoverageHead(key="smm.s02.2.30.h",
                 label="Taking readings, measurements and observations, and recording and "
                       "supplying records to the Project Manager in report format",
                 clause_ref="SMM S02 ¶2.30(h)"),
    CoverageHead(key="smm.s02.2.30.j", label="Removal of instruments",
                 clause_ref="SMM S02 ¶2.30(j)"),
    CoverageHead(key="smm.s02.2.30.k", label="Response test and other test as required",
                 clause_ref="SMM S02 ¶2.30(k)"),
    CoverageHead(key="smm.s02.2.30.l",
                 label="UPVC pipes, cappings, G.I. pipes, couplers, grout infill, filter "
                       "materials, twin tubing, piezometer tips, piezometer buckets, strings, "
                       "lead weights, plugs and the like",
                 clause_ref="SMM S02 ¶2.30(l)"),
    CoverageHead(key="smm.s02.2.30.m",
                 label="In the case of standpipe piezometer, tip, UPVC standpipe, filter medium, "
                       "seals and cement/bentonite grout",
                 clause_ref="SMM S02 ¶2.30(m)"),
    CoverageHead(key="smm.s02.2.30.n",
                 label="Instrumentation and taking of records/measurements and submissions to the "
                       "Project Manager",
                 clause_ref="SMM S02 ¶2.30(n)"),
    CoverageHead(key="smm.s02.2.30.o",
                 label="Interpretation of test results and readings and submission to the Project "
                       "Manager in report format",
                 clause_ref="SMM S02 ¶2.30(o)"),
    CoverageHead(key="smm.s02.2.30.p",
                 label="Operation and maintenance manual for instruments",
                 clause_ref="SMM S02 ¶2.30(p)"),
]

# ---------------------------------------------------------------------------
# ★ ONE SMM SECTION, SEVERAL COVERAGE CLAUSES
# ---------------------------------------------------------------------------
# Bills 2, 3, 4, 5 and 6 ALL map to SMM section 2. That does not make their coverage the same.
# SMM 2 carries a different item-coverage clause per work type:
#
#     ¶2.07 / 2.08 / 2.09   setting up, moving rigs        Bills 2, 3
#     ¶2.13                 drilling, boring, probing      Bills 2, 3
#     ¶2.22                 samples                        Bills 2, 3   (not transcribed)
#     ¶2.26                 in-situ tests                  Bills 2, 3   (not transcribed)
#     ¶2.30                 instrument installation        Bill 6
#     ¶2.35                 laboratory testing             Bills 4, 5
#     ¶2.38                 report work                    reporting items (not transcribed)
#
# THE TRAP THIS AVOIDS: giving Bills 4/5/6 a copy of Bill 2's heads because "they are all SMM 2"
# would attach *drilling* heads — stabilising the hole, reaming casing — to a *laboratory test*.
# Same failure class as "bill number is not PS number": the bill-to-SMM map is right, but WITHIN a
# section the clause follows the WORK TYPE.
SECTION_COVERAGE: dict[str, CoverageList] = {
    "2": CoverageList(bill_no="2", smm_clause="SMM S02 ¶2.13",
                      title="Ground Investigation Fieldworks — drilling, boring, probing",
                      heads=_DRILLING_2_13),
    # Bill 3 is measured under the SAME clause as Bill 2 and SHARES the list rather than copying
    # it — one literal, so a correction to ¶2.13 cannot land on one bill and miss the other.
    "3": CoverageList(bill_no="3", smm_clause="SMM S02 ¶2.13",
                      title="GI Fieldworks (Environmental Boreholes) — drilling, boring, probing",
                      heads=_DRILLING_2_13),
    "4": CoverageList(bill_no="4", smm_clause="SMM S02 ¶2.35",
                      title="Laboratory Testing", heads=_LABORATORY_2_35),
    "5": CoverageList(bill_no="5", smm_clause="SMM S02 ¶2.35",
                      title="Laboratory Testing", heads=_LABORATORY_2_35),
    "6": CoverageList(bill_no="6", smm_clause="SMM S02 ¶2.30",
                      title="Groundwater Monitoring — instrument installation",
                      heads=_INSTRUMENTS_2_30),
}

# ---------------------------------------------------------------------------
# Setting up, moving rigs, standing time — ¶2.07 / ¶2.08 / ¶2.09
# ---------------------------------------------------------------------------
# These are PER ITEM, not bill-wide, and the difference is money: "application for road excavation
# permits" is a cost of establishing a rig, not a cost of every metre drilled. Attaching them to
# the drilling items would put a permit application inside the metre rate and then again on the
# establishment item. ¶2.08(h) was already keyed to 2.2a/2.2b for exactly this reason.
#
# Verbatim from SMM_S02 Particular Preambles:
#   Add to paragraph 2.07: (d) application for necessary road excavation permits; (e) application
#   for acceptance for ground investigation works on Government land; (f) providing, maintaining
#   and removing temporary traffic arrangement in accordance with PS Clause 1.14 to 1.15.
#   Add to paragraph 2.08: (f) setting out by survey for positioning of investigation station;
#   (g) providing, maintaining and removing temporary traffic arrangement in accordance with
#   PS Clause 1.14 to 1.15; (h) access scaffolding.
#   Add to paragraph 2.09: (c) providing, maintaining and removing temporary traffic arrangement
#   in accordance with PS Clause 1.14 to 1.15.
_SETTING_UP_2_07 = [
    CoverageHead(key="smm.s02.2.07.d",
                 label="Application for necessary road excavation permits",
                 clause_ref="SMM S02 ¶2.07(d)"),
    CoverageHead(key="smm.s02.2.07.e",
                 label="Application for acceptance for ground investigation works on Government "
                       "land",
                 clause_ref="SMM S02 ¶2.07(e)"),
    CoverageHead(key="smm.s02.2.07.f",
                 label="Providing, maintaining and removing temporary traffic arrangement",
                 clause_ref="SMM S02 ¶2.07(f) · PS 1.14–1.15", cites="1.14"),
]

_MOVING_RIGS_2_08 = [
    CoverageHead(key="smm.s02.2.08.f",
                 label="Setting out by survey for positioning of investigation station",
                 clause_ref="SMM S02 ¶2.08(f)"),
    CoverageHead(key="smm.s02.2.08.g",
                 label="Providing, maintaining and removing temporary traffic arrangement",
                 clause_ref="SMM S02 ¶2.08(g) · PS 1.14–1.15", cites="1.14"),
    CoverageHead(key="smm.s02.2.08.h", label="Access scaffolding",
                 clause_ref="SMM S02 ¶2.08(h)", cites="7.01A"),
]

_STANDING_TIME_2_09 = [
    CoverageHead(key="smm.s02.2.09.c",
                 label="Providing, maintaining and removing temporary traffic arrangement",
                 clause_ref="SMM S02 ¶2.09(c) · PS 1.14–1.15", cites="1.14"),
]

# Coverage that belongs to one item rather than to a whole section, keyed on the BQ reference.
# Bill 2's references are known from the bill itself; Bill 3's are not, so it is reached by title
# instead (see TITLE_COVERAGE) rather than by references invented here.
ITEM_COVERAGE: dict[str, list[CoverageHead]] = {
    "2.1": list(_SETTING_UP_2_07),
    "2.2": list(_MOVING_RIGS_2_08),
    # The addendum split 2.2 into Class A and Class B rig moves. Both are moves.
    "2.2a": list(_MOVING_RIGS_2_08),
    "2.2b": list(_MOVING_RIGS_2_08),
    "2.3": list(_STANDING_TIME_2_09),
}

# ---------------------------------------------------------------------------
# Coverage that attaches by TITLE. See `TitleRule` for why this exists at all.
# ---------------------------------------------------------------------------
# The setting-up family is reached BOTH ways on purpose: by reference for Bill 2, whose refs are
# known, and by title for Bill 3, whose are not. `heads_for` de-duplicates on the head key, so an
# item reached by both routes carries each head once.
TITLE_COVERAGE: list[TitleRule] = [
    TitleRule(key="rig.establish", match=("establishment of rigs",),
              smm_clause="SMM S02 ¶2.07", title="Setting up rigs",
              heads=list(_SETTING_UP_2_07)),
    TitleRule(key="rig.move", match=("moving rigs",),
              smm_clause="SMM S02 ¶2.08", title="Moving rigs",
              heads=list(_MOVING_RIGS_2_08)),
    TitleRule(key="rig.standing", match=("standing time",),
              smm_clause="SMM S02 ¶2.09", title="Standing time for rigs",
              heads=list(_STANDING_TIME_2_09)),
]

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
    #: Where the words came from. A base-SMM head is real and binding, and its exact wording cannot
    #: be checked against this pack — which is a different statement from "the index could not find
    #: the page", so it gets its own field rather than being crammed into `unresolved`.
    provenance: str = FROM_AMENDMENT
    unverifiable: str = ""

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
    #: Why this list is not the whole coverage — see `PARTIAL_BY_CONSTRUCTION`. A partial list that
    #: reads as complete is the same failure as an empty one reading as "fully covered".
    partial: list[str] = Field(default_factory=list)
    #: Ticks recorded against head keys this item no longer has. NEVER applied — reported, so a
    #: person can see the tick they gave has come back as a question rather than vanishing.
    orphan_ticks: list[str] = Field(default_factory=list)
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
        """The header line: `12 heads · 3 not covered`, or `12 heads · all covered`.

        "all covered" never appears without the partial caveat beside it, because every list here
        is the amendments only and a tidy-looking checklist is exactly how a partial list passes
        for a complete one.
        """
        if self.no_list_for_section:
            return f"no item-coverage list transcribed for Bill No.{self.no_list_for_section}"
        missing = len(self.uncovered())
        if missing:
            return f"{self.total()} heads · {missing} not covered"
        return (f"{self.total()} heads · all covered · LIST IS PARTIAL" if self.partial
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


def title_rules_for(item: BillItem) -> list[TitleRule]:
    """Every title rule this item's description matches, in declaration order."""
    return [rule for rule in TITLE_COVERAGE if rule.matches(item)]


def has_list_for(item: BillItem) -> bool:
    """Whether the printed item coverage for this item has been transcribed at all.

    The distinction `heads_for` cannot make on its own: an empty list means "this coverage was
    never written down here", not "this item's rate carries nothing".
    """
    return bool(section_of(item) in SECTION_COVERAGE
                or item.full_ref in ITEM_COVERAGE
                or title_rules_for(item))


def heads_for(item: BillItem) -> list[CoverageHead]:
    """The heads that apply to one bill item, before any verdict.

    Three sources, in the order a reader would expect them: the bill's own coverage clause, then
    anything attaching by TITLE, then anything keyed to this exact BQ reference. Deterministic: the
    same item always produces the same list, which is what lets a tick be keyed to a head and
    survive a re-read.

    An empty return is AMBIGUOUS by itself — see `has_list_for`, which is what separates "nothing to
    check" from "nobody has said what to check".
    """
    section = SECTION_COVERAGE.get(section_of(item))
    by_title = [head for rule in title_rules_for(item) for head in rule.heads]
    found = [*(section.heads if section else []), *by_title,
             *ITEM_COVERAGE.get(item.full_ref, [])]
    # DE-DUPLICATED ON THE KEY, because an item can legitimately be reached by more than one route
    # — Bill 2's rig moves arrive by reference AND by title. Two entries with one key would render
    # the same head twice and let one tick appear to settle both.
    seen: set[str] = set()
    out: list[CoverageHead] = []
    for head in found:
        if head.key in seen:
            continue
        seen.add(head.key)
        out.append(head)
    return out


def partial_reasons_for(item: BillItem) -> list[str]:
    """Why this item's list is not the whole of its coverage. Empty would mean complete.

    Nothing is complete yet and probably nothing will be until the base SMM 1992 is in the pack —
    which is the point of surfacing it rather than leaving the reader to infer it from a list that
    looks tidy.
    """
    out: list[str] = []
    section = SECTION_COVERAGE.get(section_of(item))
    if section and section.partial:
        out.append(f"{section.smm_clause}: {section.partial}")
    for rule in title_rules_for(item):
        if rule.partial:
            out.append(f"{rule.smm_clause}: {rule.partial}")
    return out


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

    heads = [*heads_for(item), *(proposed or [])]
    for head in heads:
        entry = CoverageEntry(key=head.key, label=head.label, clause_ref=head.clause_ref,
                              authored_by=head.authored_by, scope=head.scope,
                              provenance=head.provenance,
                              unverifiable=(BASE_SMM_UNVERIFIABLE
                                            if head.provenance == FROM_BASE_SMM else ""))
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

    # A TICK AGAINST A HEAD THAT IS NO LONGER HERE. It is never applied — `recorded.get(head.key)`
    # only reaches keys this item actually has — but silence would be wrong twice: the person who
    # gave it would not know it had stopped counting, and a rename would look like a clean
    # migration when it was really a quiet loss. So it is named.
    live = {head.key for head in heads} | {DEEMED_INCLUDED.key}
    orphans = sorted(key for key, mark in recorded.items()
                     if key not in live and mark and mark.get("ticked"))

    return ItemCoverage(full_ref=item.full_ref, description=item.description,
                        entries=entries, bill_level=bill_level,
                        partial=partial_reasons_for(item),
                        orphan_ticks=[
                            f"a tick recorded against {key!r} no longer matches any head on this "
                            f"item — it has NOT been applied to anything. The clause letters were "
                            f"corrected to the pack's own, so the tick is back to being a question"
                            for key in orphans],
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
                     "no_list_for_section": coverage.no_list_for_section,
                     "partial": coverage.partial, "orphan_ticks": coverage.orphan_ticks})
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
        # Every list here is the amendments only. Counted, so "settled" can never be read as
        # "complete" — see PARTIAL_BY_CONSTRUCTION.
        "partial": sum(1 for r in rows if r["partial"]),
        "orphan_ticks": sum(len(r["orphan_ticks"]) for r in rows),
        "note": NO_LATER_CLAIM,
    }
