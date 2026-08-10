"""BOQ — what a coverage list is made of, and the vocabulary for saying where it came from.

Bucket: **Deterministic.** Types and constants; no logic beyond one matcher.

WHY THIS IS ITS OWN MODULE
--------------------------
Two things need this vocabulary and neither can own it. :mod:`client_boq.boq.coverage` ASSEMBLES an
item's list — merging the three routes, resolving citations, applying the human's ticks.
:mod:`client_boq.boq.smm_s01` is one contract's TRANSCRIPTION, 264 heads of it, and it has to be able
to say ``CoverageHead`` to build them. Leaving the models in ``coverage`` made the transcription
import the assembler and the assembler import the transcription — a cycle that happens to work when
``coverage`` is imported first and raises ``AttributeError`` when ``smm_s01`` is, which is a bug
waiting for whichever test file runs first.

So the shared vocabulary sits below both. ``coverage`` re-exports every name here, and every existing
``from client_boq.boq.coverage import CoverageHead`` keeps working — the split is structural, not a
rename.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from client_boq.models import BillItem

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
# paragraph 2.35…". **The base SMM 1992 is not in the pack.** So for every clause, the sub-heads the
# base defines are real, are binding, and are INVISIBLE HERE.
#
# Every list built from these types is therefore partial by construction, and that has to be said out
# loud. An empty list reading as "fully covered" was a bug fixed once already; a PARTIAL list reading
# as complete is the same bug wearing a longer coat.
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
