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

⚠ EVERY LIST HERE IS PARTIAL, AND THAT IS NOT A TEMPORARY STATE
---------------------------------------------------------------
The tender pack carries this contract's **amendments** to the base *Standard Method of Measurement
for Civil Engineering Works (1992)* — "Delete paragraph 2.13(d) and substitute…", "Add the following
to paragraph 2.35…". **The base SMM 1992 is not in the pack.** So under every clause below there are
base sub-heads that are real, binding, and invisible from here: base ``2.13(a)``–``(c)``,
``2.35(a)`` and ``(c)``–``(f)``, ``2.30(a)``–``(g)`` and ``(i)``, and so on. Closing that gap needs
the base document, not more reading of this one.

Three mechanisms keep it from reading as complete, because *"12 heads · all covered"* on a tidy
checklist is exactly how a partial list passes for a whole one — the same failure as an empty list
reading as "fully covered", just slower to notice:

* :data:`PARTIAL_BY_CONSTRUCTION` rides on every :class:`CoverageList` and :class:`TitleRule`, and
  reaches the reader through :attr:`ItemCoverage.partial` and the summary line;
* :data:`FROM_BASE_SMM` marks an individual head whose words came from the base document, so a
  reader can see which ones cannot be checked against anything in their possession;
* :data:`BILL_1_AWAITING_TEXT` names what is STILL missing around Bill 1 now that the pack's
  Section 1 is transcribed (:mod:`client_boq.boq.smm_s01`) and the real bill has been read item by
  item — the base sub-heads the lettering proves are absent, the second ¶1.06(k) the pack prints and
  nobody read, the two clauses that extracted only as fragments, the three sub-heads that stop
  mid-sentence, the SMM 3 site-clearance block Bill 1's own banner demands, and the
  removal-of-traffic-measures clause the amendments never transcribe. It is much shorter than it
  was, and shorter is not the same as finished — **a head with an invented label is still worse
  than a named gap.**

WHERE A HEAD COMES FROM — three routes, one list
------------------------------------------------
``SECTION_COVERAGE`` by bill, ``TITLE_COVERAGE`` by what an item is CALLED, ``ITEM_COVERAGE`` by BQ
reference. The middle one exists because a BQ item number is not an SMM clause number (BQ 1.12 is
*Contract Computer Facilities*; SMM ¶1.12 is something else), and because most of Bills 1, 7, 8 and
9's references were never transcribed — a reference guessed here would attach a real clause to the
wrong item. :func:`heads_for` merges all three and de-duplicates on the key.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from client_boq.boq import smm_s01
from client_boq.boq.docmap import DocumentMap
from client_boq.models import BillItem, ClientBill

# The shared vocabulary — the head/list/rule types and the provenance constants — lives in
# `client_boq.boq.heads`, one level below both this module and the transcriptions that feed it.
# Re-exported here so every `from client_boq.boq.coverage import CoverageHead` keeps working: the
# split is structural, not a rename. See that module's docstring for why it had to happen.
from client_boq.boq.heads import (  # noqa: F401  (re-exported for this module's callers)
    BASE_SMM_UNVERIFIABLE,
    BY_MODEL,
    BY_RULE,
    FROM_AMENDMENT,
    FROM_BASE_SMM,
    PARTIAL_BY_CONSTRUCTION,
    SCOPE_BILL,
    SCOPE_ITEM,
    CoverageHead,
    CoverageList,
    TitleRule,
)


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
# ---------------------------------------------------------------------------
# Bills 7, 8 and 9 â a clause per ITEM, reached by title
# ---------------------------------------------------------------------------
# SMM 24 (trees), SMM 28 (site safety) and SMM 29 (monitoring payment of wages) do not carry one
# coverage clause per bill. Each ITEM has its own â "Provide Safety Officer" is Â¶28.07 and "Attend
# Site Safety Committee" is Â¶28.13, and nothing about a safety officer belongs on a safety walk.
#
# The BQ references for most of these were not transcribed, and a reference guessed here would
# attach a real clause to the wrong item. So they attach by TITLE, which the pack DOES give â the
# same rule the Bill 1 mapping runs on. Every phrase in `match` must appear, and the phrases are
# chosen to be distinctive.
_SAFETY_28 = [
    TitleRule(key="smm28.07", bill_no="9", match=("safety officer",),
              smm_clause="SMM S28 ¶28.07", title="Provide Safety Officer",
              heads=[
                  CoverageHead(key="smm.s28.28.07.a",
                               label="Submission of the qualifications and experience of the "
                                     "proposed Safety Officer to the Project Manager for acceptance",
                               clause_ref="SMM S28 ¶28.07(a)"),
                  CoverageHead(key="smm.s28.28.07.b",
                               label="Provision of sufficient number of Safety Officers and "
                                     "supporting staff to the Safety Officers",
                               clause_ref="SMM S28 ¶28.07(b) · PS 27.05", cites="27.05"),
                  CoverageHead(key="smm.s28.28.07.c",
                               label="Ensuring the fulfillment of the duties by the Safety "
                                     "Officer(s)",
                               clause_ref="SMM S28 ¶28.07(c) · PS 27.05", cites="27.05"),
                  CoverageHead(key="smm.s28.28.07.d",
                               label="Maintenance of the safety diary",
                               clause_ref="SMM S28 ¶28.07(d)"),
              ]),
    TitleRule(key="smm28.12", bill_no="9",
              match=("site safety management committee",),
              smm_clause="SMM S28 ¶28.12", title="Attend Site Safety Management Committee",
              heads=[
                  CoverageHead(key="smm.s28.28.12.a",
                               label="Attendance of the Site Safety Management Committee meetings "
                                     "and completing the agenda of the meeting for the month",
                               clause_ref="SMM S28 ¶28.12(a)"),
                  CoverageHead(key="smm.s28.28.12.b",
                               label="Arranging inspection of the Site by members of the Committee "
                                     "before the meeting for the month",
                               clause_ref="SMM S28 ¶28.12(b)"),
                  CoverageHead(key="smm.s28.28.12.c",
                               label="Providing necessary assistance for the proper functioning of "
                                     "the Committee",
                               clause_ref="SMM S28 ¶28.12(c)"),
                  CoverageHead(key="smm.s28.28.12.d",
                               label="Submission of monthly safety report for consideration at the "
                                     "meeting",
                               clause_ref="SMM S28 ¶28.12(d)"),
              ]),
    TitleRule(key="smm28.13", bill_no="9",
              match=("site safety committee",),
              smm_clause="SMM S28 ¶28.13", title="Attend Site Safety Committee",
              heads=[
                  CoverageHead(key="smm.s28.28.13.a",
                               label="Establishment of the Site Safety Committee",
                               clause_ref="SMM S28 ¶28.13(a)"),
                  CoverageHead(key="smm.s28.28.13.b",
                               label="Arranging and giving adequate notice to relevant parties of "
                                     "the meeting to be held for the month",
                               clause_ref="SMM S28 ¶28.13(b)"),
                  CoverageHead(key="smm.s28.28.13.c",
                               label="Attendance of the Site Safety Committee meetings",
                               clause_ref="SMM S28 ¶28.13(c)"),
                  CoverageHead(key="smm.s28.28.13.d",
                               label="Completion and distribution of minutes of meetings",
                               clause_ref="SMM S28 ¶28.13(d)"),
              ]),
    TitleRule(key="smm28.18", bill_no="9", match=("safety walk",),
              smm_clause="SMM S28 ¶28.18", title="Arrange and attend weekly safety walk",
              heads=[
                  CoverageHead(key="smm.s28.28.18.a",
                               label="Arranging and giving adequate notice to relevant parties of "
                                     "the weekly safety walk",
                               clause_ref="SMM S28 ¶28.18(a)"),
                  CoverageHead(key="smm.s28.28.18.b",
                               label="Using a comprehensive checklist during the walk to identify "
                                     "deficiencies, recording them in the summary table, and "
                                     "rectifying them within the agreed time",
                               clause_ref="SMM S28 ¶28.18(b)"),
                  CoverageHead(key="smm.s28.28.18.c",
                               label="Preparation of reports on safety walks and safety "
                                     "inspections conducted",
                               clause_ref="SMM S28 ¶28.18(c)"),
                  CoverageHead(key="smm.s28.28.18.d",
                               label="Implementation and upkeeping of all measures",
                               clause_ref="SMM S28 ¶28.18(d)"),
              ]),
    TitleRule(key="smm28.25", bill_no="9", match=("specified trade",),
              smm_clause="SMM S28 ¶28.25",
              title="Safety training — skilled workers of a specified trade",
              heads=[
                  CoverageHead(key="smm.s28.28.25.a",
                               label="Arrangement of skilled workers to attend the Safety Training "
                                     "Course for Construction Workers of Specified Trade organized "
                                     "by the Construction Industry Council",
                               clause_ref="SMM S28 ¶28.25(a)"),
                  CoverageHead(key="smm.s28.28.25.b",
                               label="Payment of the token allowance to skilled workers",
                               clause_ref="SMM S28 ¶28.25(b)"),
                  CoverageHead(key="smm.s28.28.25.c",
                               label="Preparation of training programme records, and submission of "
                                     "certified monthly statements to the Project Manager",
                               clause_ref="SMM S28 ¶28.25(c)"),
                  CoverageHead(key="smm.s28.28.25.d",
                               label="Administration in connection with (a), (b) and (c) above",
                               clause_ref="SMM S28 ¶28.25(d)"),
              ]),
    TitleRule(key="smm28.26", bill_no="9", match=("induction",),
              smm_clause="SMM S28 ¶28.26",
              title="Safety training — site-specific induction",
              heads=[
                  CoverageHead(key="smm.s28.28.26.a",
                               label="Site specific induction training",
                               clause_ref="SMM S28 ¶28.26(a) · PS 27.08", cites="27.08"),
                  CoverageHead(key="smm.s28.28.26.b",
                               label="The necessary facilities, trainers and demonstration "
                                     "equipment for complying with (a)",
                               clause_ref="SMM S28 ¶28.26(b)"),
                  CoverageHead(key="smm.s28.28.26.c",
                               label="Preparation of the training programme and records, and "
                                     "submission of certified monthly statements",
                               clause_ref="SMM S28 ¶28.26(c)"),
                  CoverageHead(key="smm.s28.28.26.d",
                               label="Administration in connection with (a), (b) and (c)",
                               clause_ref="SMM S28 ¶28.26(d)"),
              ]),
    TitleRule(key="smm28.27", bill_no="9", match=("toolbox",),
              smm_clause="SMM S28 ¶28.27", title="Safety training — toolbox talks",
              heads=[
                  CoverageHead(key="smm.s28.28.27.a", label="Toolbox talks conducted",
                               clause_ref="SMM S28 ¶28.27(a) · PS 27.08", cites="27.08"),
                  CoverageHead(key="smm.s28.28.27.b",
                               label="Providing necessary training to Safety Supervisors, foremen "
                                     "or gangers to conduct such talks",
                               clause_ref="SMM S28 ¶28.27(b)"),
                  CoverageHead(key="smm.s28.28.27.c",
                               label="Basing such talks on kits published by the Hong Kong "
                                     "Construction Association Ltd., the Occupational Safety and "
                                     "Health Council, or kits of comparable standard accepted or "
                                     "advised by the Project Manager",
                               clause_ref="SMM S28 ¶28.27(c)"),
                  CoverageHead(key="smm.s28.28.27.d",
                               label="Preparation of training programme and records",
                               clause_ref="SMM S28 ¶28.27(d)"),
              ]),
    TitleRule(key="smm28.33", bill_no="9", match=("pre-work",),
              smm_clause="SMM S28 ¶28.33",
              title="PES / HIA meetings and Pre-work Safety Checks",
              heads=[
                  CoverageHead(key="smm.s28.28.33.a",
                               label="Arranging and holding PES meetings, HIA meetings and "
                                     "Pre-work Safety Checks",
                               clause_ref="SMM S28 ¶28.33(a) · PS 27.18", cites="27.18"),
                  CoverageHead(key="smm.s28.28.33.b",
                               label="Providing training to leaders of the PES or HIA meetings",
                               clause_ref="SMM S28 ¶28.33(b) · PS 27.18", cites="27.18"),
                  CoverageHead(key="smm.s28.28.33.c", label="Attendance by workers",
                               clause_ref="SMM S28 ¶28.33(c)"),
              ]),
    TitleRule(key="smm28.38", bill_no="9", match=("heat stroke",),
              smm_clause="SMM S28 ¶28.38", title="Prevention of heat stroke",
              heads=[
                  CoverageHead(key="smm.s28.28.38.a",
                               label="Providing measures for working in hot summer months to the "
                                     "satisfaction of the Project Manager",
                               clause_ref="SMM S28 ¶28.38(a) · PS 27.21", cites="27.21"),
              ]),
]

# The setting-up family is reached BOTH ways on purpose: by reference for Bill 2, whose refs are
# known, and by title for Bill 3, whose are not. `heads_for` de-duplicates on the head key, so an
# item reached by both routes carries each head once.

# SMM 24 â preservation and protection of trees (Bill 7). A clause per item, reached by title.
# ¶24.39's heads, extracted from the Bill 7 rule so Bill 1 can carry them too: the real BQ
# puts "Vegetation Survey in Conservation Area" (BQ 1.63) in BILL 1, under its own printed
# `SECTION 24` banner. One literal, two rules — a correction cannot land on one bill and
# miss the other, the same sharing discipline as `_DRILLING_2_13`.
_VEGETATION_SURVEY_24_39 = [
    CoverageHead(key="smm.s24.24.39.a",
                 label="Preparing, amending and submitting the vegetation survey record and "
                       "report",
                 clause_ref="SMM S24 ¶24.39(a) · PS 25.37", cites="25.37"),
    CoverageHead(key="smm.s24.24.39.b",
                 label="Taking photographs of existing vegetation",
                 clause_ref="SMM S24 ¶24.39(b)"),
]

_TREES_24 = [
    TitleRule(key="smm24.19", bill_no="7", match=("protection of tree",),
              smm_clause="SMM S24 ¶24.19", title="Protection of trees to be preserved",
              heads=[
                  CoverageHead(key="smm.s24.24.19.a",
                               label="Provision, installation, securing, maintenance, "
                                     "reinstatement and removal of identification labelling or "
                                     "marking systems",
                               clause_ref="SMM S24 ¶24.19(a) · GS · PS 26.04", cites="26.04"),
                  CoverageHead(key="smm.s24.24.19.b",
                               label="Temporary protective fencing, armouring and mulching",
                               clause_ref="SMM S24 ¶24.19(b) · GS · PS 26.09", cites="26.09"),
                  CoverageHead(key="smm.s24.24.19.c",
                               label="Physical support measures to protect the trees from "
                                     "instability",
                               clause_ref="SMM S24 ¶24.19(c)"),
              ]),
    TitleRule(key="smm24.24", bill_no="7", match=("tree survey",),
              smm_clause="SMM S24 ¶24.24", title="Tree survey record",
              heads=[
                  CoverageHead(key="smm.s24.24.24.a",
                               label="Preparing, amending and submitting the tree survey record to "
                                     "the Project Manager",
                               clause_ref="SMM S24 ¶24.24(a) · GS · PS 26.03", cites="26.03"),
                  CoverageHead(key="smm.s24.24.24.b",
                               label="Provision and installation of an identification labelling or "
                                     "marking system for all existing trees to be felled",
                               clause_ref="SMM S24 ¶24.24(b) · GS · PS 26.04", cites="26.04"),
                  CoverageHead(key="smm.s24.24.24.c",
                               label="Taking photographs of existing trees",
                               clause_ref="SMM S24 ¶24.24(c)"),
              ]),
    TitleRule(key="smm24.25", bill_no="7", match=("photographic record",),
              smm_clause="SMM S24 ¶24.25", title="Updated photographic record of preserved trees",
              heads=[
                  CoverageHead(key="smm.s24.24.25.a",
                               label="Taking updated photographs of the trees",
                               clause_ref="SMM S24 ¶24.25(a)"),
                  CoverageHead(key="smm.s24.24.25.b",
                               label="Preparing, amending and submitting a report on the updated "
                                     "photographic record of the preserved trees",
                               clause_ref="SMM S24 ¶24.25(b) · PS 26.08S", cites="26.08S"),
              ]),
    TitleRule(key="smm24.31", bill_no="7", match=("area basis assessment",),
              smm_clause="SMM S24 ¶24.31", title="Area basis assessment",
              heads=[
                  CoverageHead(key="smm.s24.24.31.a", label="Carrying out area basis assessment",
                               clause_ref="SMM S24 ¶24.31(a)"),
                  CoverageHead(key="smm.s24.24.31.b",
                               label="Providing all necessary assistance, temporary traffic "
                                     "arrangements, tools, equipment and transportation",
                               clause_ref="SMM S24 ¶24.31(b)"),
                  CoverageHead(key="smm.s24.24.31.c", label="Complying with PS Clause 26.18",
                               clause_ref="SMM S24 ¶24.31(c) · PS 26.18", cites="26.18"),
              ]),
    TitleRule(key="smm24.32", bill_no="7", match=("tree group inspection",),
              smm_clause="SMM S24 ¶24.32", title="Tree group inspection",
              heads=[
                  CoverageHead(key="smm.s24.24.32.a", label="Carrying out tree group inspection",
                               clause_ref="SMM S24 ¶24.32(a)"),
                  CoverageHead(key="smm.s24.24.32.b",
                               label="Providing all necessary assistance, temporary traffic "
                                     "arrangements, tools, equipment and transportation",
                               clause_ref="SMM S24 ¶24.32(b)"),
                  CoverageHead(key="smm.s24.24.32.c", label="Complying with PS Clause 26.19",
                               clause_ref="SMM S24 ¶24.32(c) · PS 26.19", cites="26.19"),
              ]),
    TitleRule(key="smm24.33", bill_no="7", match=("detailed tree risk assessment",),
              smm_clause="SMM S24 ¶24.33", title="Detailed tree risk assessment",
              heads=[
                  CoverageHead(key="smm.s24.24.33.a",
                               label="Carrying out detailed tree risk assessment",
                               clause_ref="SMM S24 ¶24.33(a)"),
                  CoverageHead(key="smm.s24.24.33.b",
                               label="Providing all necessary assistance, temporary traffic "
                                     "arrangements, tools, equipment and transportation",
                               clause_ref="SMM S24 ¶24.33(b)"),
                  CoverageHead(key="smm.s24.24.33.c", label="Complying with PS Clause 26.20",
                               clause_ref="SMM S24 ¶24.33(c) · PS 26.20", cites="26.20"),
              ]),
    TitleRule(key="smm24.34", bill_no="7", match=("follow-up action",),
              smm_clause="SMM S24 ¶24.34", title="Follow-up actions after tree risk assessment",
              heads=[
                  CoverageHead(key="smm.s24.24.34.a",
                               label="Carrying out follow-up actions after tree risk assessment",
                               clause_ref="SMM S24 ¶24.34(a) · PS 26.21", cites="26.21"),
              ]),
    TitleRule(key="smm24.35", bill_no="7", match=("audit", "tree risk assessment"),
              smm_clause="SMM S24 ¶24.35", title="Audit on tree risk assessment",
              heads=[
                  CoverageHead(key="smm.s24.24.35.a", label="Audit on tree risk assessment",
                               clause_ref="SMM S24 ¶24.35(a) · PS 26.22", cites="26.22"),
              ]),
    TitleRule(key="smm24.39", bill_no="7", match=("vegetation survey",),
              smm_clause="SMM S24 ¶24.39", title="Vegetation survey record and report",
              heads=list(_VEGETATION_SURVEY_24_39)),
]

# SMM 29 â monitoring payment of wages (Bill 8). A clause per item, reached by title.
_WAGES_29 = [
    TitleRule(key="smm29.06", bill_no="8", match=("establish", "monitoring system"),
              smm_clause="SMM S29 ¶29.06", title="Establishing the monitoring system",
              heads=[
                  CoverageHead(key="smm.s29.29.06.a",
                               label="Preparation of the monitoring system for payment of wages to "
                                     "the acceptance of the Project Manager",
                               clause_ref="SMM S29 ¶29.06(a)"),
                  CoverageHead(key="smm.s29.29.06.b",
                               label="Setting up the monitoring system and any modifications "
                                     "thereof",
                               clause_ref="SMM S29 ¶29.06(b)"),
                  CoverageHead(key="smm.s29.29.06.c",
                               label="Provision for collection and maintenance of records of "
                                     "payment of wages to Site Workers",
                               clause_ref="SMM S29 ¶29.06(c)"),
                  CoverageHead(key="smm.s29.29.06.d",
                               label="Opening of accounts in a designated bank for relevant "
                                     "parties",
                               clause_ref="SMM S29 ¶29.06(d) · PS 29.05(1)–(2)", cites="29.05"),
                  CoverageHead(key="smm.s29.29.06.e",
                               label="Nomination of a Contractor's Labour Officer",
                               clause_ref="SMM S29 ¶29.06(e) · PS 29.09", cites="29.09"),
                  CoverageHead(key="smm.s29.29.06.f",
                               label="Setting up the attendance recording system",
                               clause_ref="SMM S29 ¶29.06(f)"),
              ]),
    TitleRule(key="smm29.implement", bill_no="8", match=("implement", "monitoring system"),
              smm_clause="SMM S29 — clause number NOT CAPTURED",
              title="Implementing the monitoring system",
              heads=[
                  CoverageHead(key="smm.s29.implement.a",
                               label="Operating and maintaining the attendance recording system of "
                                     "the CWRS to obtain accurate attendance records of Site Workers",
                               clause_ref="SMM S29 (clause number not captured) (a)"),
                  CoverageHead(key="smm.s29.implement.c",
                               label="Reviewing, updating and revising the monitoring system taking "
                                     "into account the comments made by the Project Manager or any "
                                     "other parties",
                               clause_ref="SMM S29 (clause number not captured) (c)"),
                  CoverageHead(key="smm.s29.implement.d",
                               label="Implementing measures to ensure that payments of wages to "
                                     "Site Workers are made against the attendance records",
                               clause_ref="SMM S29 (clause number not captured) (d)"),
                  CoverageHead(key="smm.s29.implement.e",
                               label="Compiling, submitting and maintaining records of payment of "
                                     "wages",
                               clause_ref="SMM S29 (clause number not captured) (e)"),
              ]),
    TitleRule(key="smm29.08", bill_no="8", match=("labour officer",),
              smm_clause="SMM S29 ¶29.08", title="Providing the Contractor's Labour Officer",
              heads=[
                  CoverageHead(key="smm.s29.29.08.employment",
                               label="Basic salary, gratuity, overtime payment, sundry allowance, "
                                     "housing allowance, travel allowance, leave allowance, "
                                     "education allowance, medical allowance, dental allowance, "
                                     "bonus, contribution to a registered mandatory provident fund "
                                     "scheme, all necessary levies (e.g. Construction Industry "
                                     "Council), insurances and fringe benefits",
                               clause_ref="SMM S29 ¶29.08(a)–(o)"),
              ]),
]


# ---------------------------------------------------------------------------
# Bill 1 — General & Preliminaries. MAPPED FROM THE REAL BILL, ITEM BY ITEM.
# ---------------------------------------------------------------------------
# SMM 1 carries 42 item-coverage blocks, one per preliminaries item, and the BQ's item numbers are
# NOT those clause numbers: BQ 1.12 is *Contract Computer Facilities* while SMM ¶1.12 is something
# else entirely. The mapping is by TITLE — the same lesson as "bill number is not PS number".
#
# THE MAPPING BELOW IS THE REAL BILL's (BQ Bill No.1, pages BQ 3–7, 63 items, read item by item),
# and reading it taught this block four things:
#
# 1. THE LINE BESIDE THE NUMBER IS NOT THE TITLE. BQ 1.23–1.40 print as bare "Provision" /
#    "Maintenance" / "Removal" — eighteen items, six distinct words, nine collisions. What
#    separates environmental MITIGATION (¶1.40–1.42) from environmental MONITORING (¶1.45–1.47)
#    is the heading two levels up, which is why `TitleRule.matches` runs on `full_description()`
#    — chain plus line — and why these rules match on a chain word plus an action word.
# 2. ONE CLAUSE, THREE MEDIA. ¶1.40 covers mitigation "not separately measured" for air, noise
#    and water alike — the air/noise/water grouping is a BQ sub-heading, not a clause
#    distinction. So each action rule matches all three media deliberately.
# 3. THE BQ'S OWN WORDS DIFFER FROM THE CLAUSE TITLES. The bill says "Servicing" and
#    "Dismantling" where ¶1.06/¶1.07 say maintenance and handing back; "Covering for dusty
#    materials" where ¶1.76's transcription said dust; "smoky activities" not "smoke screens".
#    Matching runs on the BILL's words, because that is the text the matcher will be shown.
# 4. BILL 1 IS NOT ONLY SMM 1. Its last two items sit under their own printed banners:
#    BQ 1.62 under `SECTION 3 - SITE CLEARANCE` (SMM 3 — not transcribed, a named gap) and
#    BQ 1.63 under `SECTION 24` (vegetation survey → ¶24.39, already transcribed for Bill 7
#    and shared from the same literal).
#
# THE SHAPE: per item, not a Bill-1-wide list. A preliminaries item's coverage has nothing in
# common with its neighbour's, so a `SECTION_COVERAGE['1']` would attach the core-store heads to
# the insurance item. Where the BQ bills one activity as several items (erection / servicing /
# handing over of the core store), the rules split the same way, so a servicing obligation is
# never a tick on the erection item. Two ranges stay deliberately bundled — the land transport
# (¶1.22–1.23) and the telephone line (¶1.116–1.117) — because their two items share every
# distinguishing phrase this side of the vehicle specification, and a false split that guesses
# wrong words would silently miss one of them.
#
# TWO RECONCILIATIONS, NOW ANSWERED by an independent read of the real bill: BQ 1.53 dropped
# because its wrapped description linearises with the quantity and unit INSIDE it — fixed in
# `pipeline/stage_01_ingest/ingest.py::_bq_item_inventory` (the wrapped-description collector,
# pinned with 1.53 as the fixture) — and Bill 1 prints 63 items (1.1–1.63, no gaps, no letter
# suffixes), so the routing card's 64 was an over-count of the same wrapped row, not a missing
# item. Both were about reading the bill, not about this mapping.
_BILL_1_MAPPING: tuple[tuple[str, tuple[str, ...], str, str, tuple[str, ...]], ...] = (
    # (rule key, title phrases — matched over heading chain + line, SMM clause, what the BQ
    #  calls it, the transcribed clauses its heads come from)
    #
    # The Site Office trio: the BQ's action words, not the clause titles' (see note 3 above).
    ("smm1.05", ("site office", "taking over"), "SMM S01 ¶1.05",
     "Project Manager's Site Office — taking over", ("1.05",)),
    ("smm1.06", ("site office", "servicing"), "SMM S01 ¶1.06",
     "Project Manager's Site Office — servicing", ("1.06",)),
    ("smm1.07", ("site office", "dismantling"), "SMM S01 ¶1.07",
     "Project Manager's Site Office — dismantling", ("1.07",)),
    ("smm1.11", ("temporary accommodation",), "SMM S01 ¶1.11",
     "Temporary accommodation for the Contractor", ("1.11",)),
    # BQ 1.5/1.6 — provision and maintenance of the maintain-traffic-flow measures. The third of
    # the trio, BQ 1.7 "Removal of measures", has NO transcribed clause: see the explicit
    # named-gap rule below the mapping.
    ("smm1.14", ("provision of measures",), "SMM S01 ¶1.14",
     "Maintenance of traffic flow — provision of measures", ("1.14",)),
    ("smm1.15", ("maintenance of measures",), "SMM S01 ¶1.15",
     "Maintenance of traffic flow — maintenance of measures", ("1.15",)),
    # BQ 1.10/1.11 — the bill titles these "Land transport for the use of the Project Manager",
    # not "vehicles". Bundled: both items share the transport heading and every phrase that
    # could split provision (¶1.22) from running (¶1.23) is vehicle-specification wording this
    # mapping has not verified. A bundle over-lists; a wrong split silently misses.
    ("smm1.22", ("transport", "project manager"), "SMM S01 ¶1.22–1.23",
     "Land transport for the Project Manager — provision, operation and maintenance",
     ("1.22", "1.23")),
    # ONE clause, TWO bill items (BQ 1.12/1.13): ¶1.28's sub-heads name both systems.
    ("smm1.28", ("computer facilities",), "SMM S01 ¶1.28",
     "Contract Computer Facilities", ("1.28",)),
    ("smm1.28.edms", ("electronic document management",), "SMM S01 ¶1.28",
     "Electronic Document Management System", ("1.28",)),
    # BQ 1.14/1.15/1.16 — progress / additional / record photographs, all under the Photographs
    # heading and all governed by ¶1.32. "8R size print" means nothing without its chain.
    ("smm1.32", ("photograph",), "SMM S01 ¶1.32",
     "Photographs — progress set, additional, record", ("1.32",)),
    ("smm1.37", ("hoarding",), "SMM S01 ¶1.37", "Hoardings", ("1.37",)),
    # The two environmental families (see notes 1 and 2): eighteen bare-titled items told apart
    # only by their chains. One rule per ACTION; each covers air, noise and water alike because
    # the clause does.
    ("smm1.40", ("mitigation", "provision"), "SMM S01 ¶1.40",
     "Environmental mitigation measures — provision (air / noise / water alike)", ("1.40",)),
    ("smm1.41", ("mitigation", "maintenance"), "SMM S01 ¶1.41",
     "Environmental mitigation measures — maintenance (air / noise / water alike)", ("1.41",)),
    ("smm1.42", ("mitigation", "removal"), "SMM S01 ¶1.42",
     "Environmental mitigation measures — removal (air / noise / water alike)", ("1.42",)),
    ("smm1.45", ("monitoring", "provision"), "SMM S01 ¶1.45",
     "Environmental monitoring measures — provision (air / noise / water alike)", ("1.45",)),
    ("smm1.46", ("monitoring", "maintenance"), "SMM S01 ¶1.46",
     "Environmental monitoring measures — maintenance (air / noise / water alike)", ("1.46",)),
    ("smm1.47", ("monitoring", "removal"), "SMM S01 ¶1.47",
     "Environmental monitoring measures — removal (air / noise / water alike)", ("1.47",)),
    ("smm1.66", ("trip ticket", "complete"), "SMM S01 ¶1.66",
     "Site management plan for trip ticket system — complete", ("1.66",)),
    ("smm1.67", ("trip ticket", "implement"), "SMM S01 ¶1.67",
     "Site management plan for trip ticket system — implement", ("1.67",)),
    # The bill says "Covering for dusty materials", not "dust covering".
    ("smm1.76", ("dusty materials",), "SMM S01 ¶1.76",
     "Air pollution abatement — covering for dusty materials", ("1.76",)),
    # The bill says "smoky activities"; "smoke screen" appears nowhere on the page.
    ("smm1.77", ("smoky",), "SMM S01 ¶1.77",
     "Air pollution abatement — screens or enclosures for smoky activities", ("1.77",)),
    ("smm1.85", ("acoustic screen",), "SMM S01 ¶1.85",
     "Noise pollution abatement — acoustic screens", ("1.85",)),
    ("smm1.86", ("other noise abatement",), "SMM S01 ¶1.86",
     "Adoption of other noise abatement practices", ("1.86",)),
    ("smm1.91", ("wastewater collection",), "SMM S01 ¶1.91",
     "Wastewater collection system", ("1.91",)),
    ("smm1.96", ("sorting of c&d",), "SMM S01 ¶1.96",
     "On-site sorting of C&D materials", ("1.96",)),
    ("smm1.100", ("fuel sample",), "SMM S01 ¶1.100", "Fuel sample", ("1.100",)),
    ("smm1.104", ("survey of the site",), "SMM S01 ¶1.104", "Survey of the Site", ("1.104",)),
    # BQ 1.18/1.19/1.20 — the bill splits the core store into erection / servicing / handing
    # over, so the rules do too: a servicing obligation must not be a tick on the erection item.
    ("smm1.109", ("core and sample store", "erection"), "SMM S01 ¶1.109",
     "Core and sample store — erection", ("1.109",)),
    ("smm1.110", ("core and sample store", "servicing"), "SMM S01 ¶1.110",
     "Core and sample store — servicing", ("1.110",)),
    ("smm1.111", ("core and sample store", "handing"), "SMM S01 ¶1.111",
     "Core and sample store — handing over", ("1.111",)),
    ("smm1.112", ("environmental management",), "SMM S01 ¶1.112",
     "Provide environmental management measures", ("1.112",)),
    # BQ 1.21/1.22 — bundled for the same reason as the land transport above.
    ("smm1.116", ("telephone line",), "SMM S01 ¶1.116–1.117",
     "24-hour telephone line", ("1.116", "1.117")),
    ("smm1.133", ("digital works supervision",), "SMM S01 ¶1.133",
     "Digital Works Supervision System (DWSS)", ("1.133",)),
    # The SSSS family: "complete" and "review" separate BQ 1.52 from 1.53, whose line contains
    # the word "plan" too — a rule matching on "plan" put ¶1.140's heads on both.
    ("smm1.140", ("smart site safety", "complete"), "SMM S01 ¶1.140",
     "Smart Site Safety System — complete Implementation Plan", ("1.140",)),
    ("smm1.141", ("smart site safety", "review"), "SMM S01 ¶1.141",
     "Smart Site Safety System — review, update and implement", ("1.141",)),
    # BQ 1.54's own line is "Provide site communication network"; its section banner is SITE
    # COMMUNICATION NETWORK, not SSSS, so the rule must not depend on the SSSS phrase.
    ("smm1.146", ("site communication network",), "SMM S01 ¶1.146",
     "Site communication network", ("1.146",)),
    ("smm1.151", ("smart site safety", "component"), "SMM S01 ¶1.151",
     "Smart Site Safety System — components", ("1.151",)),
    ("smm1.156", ("virtual reality",), "SMM S01 ¶1.156",
     "Safety training with Virtual Reality technology", ("1.156",)),
)


def _bill_1_partial(clauses: tuple[str, ...]) -> str:
    """Why this rule's list is not the whole coverage — naming the missing letters where it can.

    Every list here is the pack's amendments only, which `PARTIAL_BY_CONSTRUCTION` already says. For
    ten of these clauses the lettering says something sharper: ¶1.06 prints (c), (f), (h)–(p) and
    (w), so (a), (b), (d), (e), (g) and (q)–(v) are base SMM 1992 sub-heads — real, binding, and not
    in anybody's possession here. Naming them beats "this list is partial", because a reader can
    count them.
    """
    named = [f"¶{clause} prints no "
             f"({'), ('.join(smm_s01.BASE_SMM_GAPS[clause])})"
             for clause in clauses if clause in smm_s01.BASE_SMM_GAPS]
    if not named:
        return PARTIAL_BY_CONSTRUCTION
    return (f"{PARTIAL_BY_CONSTRUCTION} Here the lettering says which: {'; '.join(named)} — those "
            f"sub-heads are in the base SMM 1992 and are binding and unlisted.")


def _s01_letters(clause: str, *letters: str) -> list[CoverageHead]:
    """A clause's heads filtered to named letters — for a clause the BQ bills as SEPARATE items
    per sub-head. Raises on a letter that is not there: a typo that silently produced a shorter
    checklist is the failure this whole package is built against."""
    picked = {h.key.rsplit(".", 1)[-1]: h for h in smm_s01.CLAUSES[clause]}
    missing = [letter for letter in letters if letter not in picked]
    if missing:
        raise KeyError(f"¶{clause} has no sub-head(s) {missing} — check the letters")
    return [picked[letter] for letter in letters]


_TRAFFIC_REMOVAL_GAP = (
    "BQ 1.7 is the third of the maintain-traffic-flow trio — provision is ¶1.14, maintenance is "
    "¶1.15, and the pack's SMM S01 amendments transcribe NO removal clause. Whether the base SMM "
    "defines one was not established, so the gap is named rather than papered over with either "
    "neighbour's heads.")

_SITE_CLEARANCE_GAP = (
    "This item sits under Bill 1's own printed `SECTION 3 - SITE CLEARANCE` banner, so it is "
    "governed by SMM Section 3 — whose item-coverage blocks are not in the transcription at all. "
    "Reading the pack's SMM S03 document is the fix; nothing here invents its words.")

_PRELIMINARIES_1 = [
    TitleRule(key=key, bill_no="1", match=match, smm_clause=clause, title=title,
              heads=smm_s01.heads_for_clauses(*clauses),
              partial=_bill_1_partial(clauses))
    for key, match, clause, title, clauses in _BILL_1_MAPPING
] + [
    # BQ 1.8/1.9 — the bill splits ¶1.18 by INSURANCE: third party gets (a), professional
    # indemnity gets (b), and the fees-and-premiums head (c) belongs to both. One rule would put
    # a professional-indemnity obligation on the third-party item's checklist.
    TitleRule(key="smm1.18.third_party", bill_no="1", match=("third party insurance",),
              smm_clause="SMM S01 ¶1.18(a)", title="Third party insurance",
              heads=_s01_letters("1.18", "a", "c"),
              partial=_bill_1_partial(("1.18",))),
    TitleRule(key="smm1.18.indemnity", bill_no="1", match=("professional indemnity",),
              smm_clause="SMM S01 ¶1.18(b)", title="Professional indemnity insurance",
              heads=_s01_letters("1.18", "b", "c"),
              partial=_bill_1_partial(("1.18",))),
    # BQ 1.63 — a Bill 1 item governed by SMM 24 (see note 4). The heads are the SAME literal
    # the Bill 7 rule carries, so a correction lands on both.
    TitleRule(key="smm24.39.bill1", bill_no="1", match=("vegetation survey",),
              smm_clause="SMM S24 ¶24.39", title="Vegetation Survey in Conservation Area",
              heads=list(_VEGETATION_SURVEY_24_39)),
    # BQ 1.62 — governed by SMM 3, which nobody has transcribed. The clause family is known;
    # the words are not; heads are not invented.
    TitleRule(key="smm3.clearance", bill_no="1", match=("site clearance",),
              smm_clause="SMM S03 (site clearance)", title="General site clearance of the Site",
              heads=[], partial=_SITE_CLEARANCE_GAP, no_heads_reason=_SITE_CLEARANCE_GAP),
    # BQ 1.7 — the removal leg of the traffic-flow trio. No transcribed clause to attach.
    TitleRule(key="smm1.traffic.removal", bill_no="1", match=("removal of measures",),
              smm_clause="SMM S01 (removal of traffic measures — no clause in the pack's "
                         "amendments)",
              title="Maintenance of traffic flow — removal of measures",
              heads=[], partial=_TRAFFIC_REMOVAL_GAP, no_heads_reason=_TRAFFIC_REMOVAL_GAP),
]

# Which rules draw on which SMM S01 clause — DERIVED from the rules' own heads rather than
# maintained beside them, so it cannot drift. Used for the awaiting-text list below and by the
# test that proves every transcribed clause is actually reachable from Bill 1.
_BILL_1_RULES_FOR: dict[str, list[str]] = {}
for _rule in _PRELIMINARIES_1:
    for _head in _rule.heads:
        _parts = _head.key.split(".")
        if _parts[:2] != ["smm", "s01"]:
            continue  # the vegetation-survey rule's heads are SMM 24's
        _clause = f"{_parts[2]}.{_parts[3]}"
        _keys = _BILL_1_RULES_FOR.setdefault(_clause, [])
        if _rule.key not in _keys:
            _keys.append(_rule.key)

# WHAT IS STILL OUTSTANDING around Bill 1, assembled from the transcription's own records rather
# than maintained by hand beside them — a second copy of a list is a list that drifts.
#
# This has shrunk twice, honestly each time: it named all 27 mapped clauses when none of their
# words had been read, then the base-SMM letter gaps once the pack's amendments were transcribed,
# and now — with the real bill read item by item — the mitigation/monitoring contradiction is
# RESOLVED and replaced by the two gaps the bill itself exposed: the SMM 3 site-clearance block
# and the removal-of-traffic-measures clause, neither of which is in the transcription. Shorter
# is not the same as finished, and none of these are things a reader should have to infer from a
# tidy-looking checklist.
BILL_1_AWAITING_TEXT: list[dict] = [
    # ONE ROW PER CLAUSE, NOT PER RULE. ¶1.28 governs two BQ items — a row per rule listed the
    # same missing base sub-heads twice, and a work-list that repeats an entry is one somebody
    # does twice or crosses off once.
    *({"rules": _BILL_1_RULES_FOR[clause], "smm_clause": f"SMM S01 ¶{clause}",
       "titles": [rule.title for rule in _PRELIMINARIES_1
                  if rule.key in _BILL_1_RULES_FOR[clause]],
       "needs": f"sub-head{'s' if len(gaps) > 1 else ''} ({'), ('.join(gaps)}) of ¶{clause}, "
                f"which are in the base SMM 1992 — not in this pack, and not readable from it"}
      for clause, gaps in smm_s01.BASE_SMM_GAPS.items() if clause in _BILL_1_RULES_FOR),
    # The rules that match a real bill item and can hand it no heads — each says why itself.
    *({"rules": [rule.key], "smm_clause": rule.smm_clause, "titles": [rule.title],
       "needs": rule.no_heads_reason}
      for rule in _PRELIMINARIES_1 if not rule.heads),
    {"rules": _BILL_1_RULES_FOR["1.06"], "smm_clause": "SMM S01 ¶1.06(k)",
     "titles": ["Project Manager's Site Office — servicing"],
     "needs": smm_s01.SECOND_K["missing"]},
    *({"rules": [], "smm_clause": f"SMM S01 ¶{row['clause']}", "titles": [],
       "needs": f"the substituted text of this amendment: {row['reading']}"}
      for row in smm_s01.FRAGMENTS),
    *({"rules": [], "smm_clause": f"SMM S01 ¶{row['clause']}({row['letter']})", "titles": [],
       "needs": f"the rest of this sub-head — it {row['breaks_at']}"}
      for row in smm_s01.TRUNCATED),
]

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
    *_PRELIMINARIES_1,
    *_TREES_24,
    *_SAFETY_28,
    *_WAGES_29,
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

    #: The build-up basis the person named as carrying this head, and what that name is worth.
    #: A tick with no basis is a BELIEF — which is all a tick has ever been. A tick WITH one is a
    #: link, and a link can be checked against the cost the item's rate is actually made of.
    basis_key: str = ""
    basis_label: str = ""
    #: One of `ACCOUNTED_BY_COST`, `ASSERTED_ONLY`, `COST_NOT_IN_RATE`, `UNACCOUNTED`. Set by
    #: :func:`account_for_cost`; empty until that has run, because a verdict nobody computed must
    #: not read as one that came out clean.
    accounting: str = ""

    def covered(self) -> bool:
        return self.ticked


#: THE FOUR STATES OF AN OBLIGATION, once a tick can name the cost that discharges it.
#:
#: Under General Preambles ¶2 a rate is deemed to include everything the specification names for its
#: item, and *"any item missed out from the item coverage shall not be measured"* — the work is
#: still owed and cannot be claimed. So an obligation nobody has priced is not saved, it is given
#: away, and the whole point of a coverage checklist is to make that visible BEFORE the tender goes
#: in rather than on the first payment certificate.
#:
#: A tick alone could only ever say a person believed it. These four say what can be checked.
ACCOUNTED_BY_COST = "accounted_by_cost"
ASSERTED_ONLY = "asserted_only"
COST_NOT_IN_RATE = "cost_not_in_rate"
UNACCOUNTED = "unaccounted"

ACCOUNTING_WORDS = {
    ACCOUNTED_BY_COST: "carried by a cost this rate is actually built from",
    ASSERTED_ONLY: "ticked, but no cost was named — this is somebody's word for it",
    COST_NOT_IN_RATE: "claimed against a cost this rate does NOT draw on",
    UNACCOUNTED: "nobody has said this rate carries it",
}


def account_for_cost(coverage: "ItemCoverage", *, bases: Optional[dict[str, str]] = None,
                     drawn_on: Optional[set[str]] = None) -> "ItemCoverage":
    """Classify every head against the cost this item's rate is actually made of. Pure; mutates
    only the entries it was handed, and decides nothing a person has not already said.

    ``bases`` is ``basis_key -> label`` for every basis in the build-up, so a named cost can be
    printed in words rather than as a key. ``drawn_on`` is the set of basis keys THIS item's rate
    draws on — from the item's own ``ItemMapping``, which is the live engine's answer to "where
    does this rate's money come from".

    The one that earns this function is :data:`COST_NOT_IN_RATE`. A head ticked against a basis the
    rate does not draw on is an obligation claimed against money that is not in the number — and
    that is checkable arithmetic, not a reader's memory. It is also invisible to every other check
    here: the head is ticked, so it is "covered", and the rate is priced, so it is "priced".

    Nothing is ever ticked or unticked by this. It reads what a person recorded and says what that
    recording is worth.
    """
    labels = bases or {}
    drawn = drawn_on or set()
    for entry in coverage.entries:
        entry.basis_label = labels.get(entry.basis_key, "")
        if not entry.ticked:
            entry.accounting = UNACCOUNTED
        elif not entry.basis_key:
            entry.accounting = ASSERTED_ONLY
        elif entry.basis_key in drawn:
            entry.accounting = ACCOUNTED_BY_COST
        else:
            entry.accounting = COST_NOT_IN_RATE
    return coverage


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
    #: WHY this item has no list, in words. "No list transcribed for Bill No.9" would be a lie once
    #: nine of Bill 9's clauses ARE transcribed and none of them matched this item's title — those
    #: are different problems with different fixes, and saying the wrong one sends somebody to
    #: transcribe a thing that is already there.
    no_list_reason: str = ""

    def total(self) -> int:
        return len(self.entries)

    def uncovered(self) -> list[CoverageEntry]:
        return [e for e in self.entries if not e.covered()]

    # --- once `account_for_cost` has run -----------------------------------------------------
    def accounted_by_cost(self) -> list[CoverageEntry]:
        return [e for e in self.entries if e.accounting == ACCOUNTED_BY_COST]

    def asserted_only(self) -> list[CoverageEntry]:
        return [e for e in self.entries if e.accounting == ASSERTED_ONLY]

    def cost_not_in_rate(self) -> list[CoverageEntry]:
        """Heads claimed against a cost this rate does not draw on. The check nothing else makes.

        Invisible to every other reading here: the head is ticked, so it counts as covered, and the
        rate is priced, so it counts as priced. The obligation is real and the money is somewhere
        else."""
        return [e for e in self.entries if e.accounting == COST_NOT_IN_RATE]

    def unaccounted(self) -> list[CoverageEntry]:
        """Heads nobody has said this rate carries. NOT the same as "covered by other rates".

        General Preambles ¶6 makes an unpriced obligation the other rates' problem for the life of
        the contract, so this list is money, not paperwork."""
        return [e for e in self.entries if e.accounting == UNACCOUNTED]

    def accounting_problems(self) -> list[str]:
        """The two states worth a sentence, worst first. Empty is only ever earned."""
        out = [
            f"{e.clause_ref or e.key}: {e.label} — claimed against {e.basis_label or e.basis_key!r}, "
            f"which this rate does not draw on. The obligation is real and the money is somewhere "
            f"else."
            for e in self.cost_not_in_rate()
        ]
        out += [
            f"{e.clause_ref or e.key}: {e.label} — nobody has said this rate carries it. General "
            f"Preambles ¶6 makes it the other rates' problem for the life of the contract."
            for e in self.unaccounted()
        ]
        return out

    def accounting_summary(self) -> str:
        """One line. Says nothing reassuring that is not true, and never says it about an empty
        list — an item with no transcribed coverage has nothing to account for and must not read
        as an item that accounted for everything."""
        if self.no_list_for_section:
            return f"no item-coverage list transcribed for Bill No.{self.no_list_for_section}"
        if not self.entries:
            return "no heads on this item, so there is nothing to account for"
        if not any(e.accounting for e in self.entries):
            return "the rate's cost has not been checked against these heads"
        parts = [f"{len(self.accounted_by_cost())} carried by a named cost"]
        if self.asserted_only():
            parts.append(f"{len(self.asserted_only())} asserted without one")
        if self.cost_not_in_rate():
            parts.append(f"{len(self.cost_not_in_rate())} claimed against a cost NOT in this rate")
        if self.unaccounted():
            parts.append(f"{len(self.unaccounted())} accounted for by nobody")
        return f"{self.total()} heads · " + " · ".join(parts)

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
    """Whether this item has an actual checklist — HEADS, not merely a clause with its name on it.

    The distinction `heads_for` cannot make on its own: an empty list means "this coverage was
    never written down here", not "this item's rate carries nothing".

    IT IS `heads_for`, NOT THE SOURCES. Bill 1's mapping names the clause that governs each
    preliminaries item and carries NO heads, because SMM S01's 42 blocks were not transcribed. An
    earlier version of this asked "is there a rule for it?", and a matched-but-empty rule then made
    `no_list_for_section` blank, which let `settled()` return True on an item with nothing to
    check. "All covered" for coverage nobody has read is the exact failure this field exists to
    prevent, and it came back through the door marked "we know which clause it is".
    """
    return bool(heads_for(item))


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


def _no_list_reason(item: BillItem) -> str:
    """Why this item has no checklist â and the two cases are not the same problem.

    A bill whose coverage was never transcribed needs somebody to read the Method of Measurement.
    A bill whose clauses ARE transcribed but none of which matched THIS item's title needs somebody
    to look at the title. Reporting the first when it is really the second sends a reader off to
    transcribe a thing that is already sitting in this file.
    """
    bill_no = section_of(item)
    # A clause matched by title but carrying no heads: the governing clause is KNOWN and something
    # about it is outstanding. Saying "nothing is transcribed for this bill" would throw that away.
    #
    # WHICH outstanding thing is not one answer. A clause's words may never have been read, or they
    # may be sitting in the file while the MAPPING that would attach them is in doubt — see
    # `_MAPPING_UNVERIFIED`. Those need different people to do different work, so a rule that knows
    # its own reason gives it, and the general reading is the fallback rather than the assumption.
    # This is the same lesson as the two branches below, applied one level further in.
    named = [rule for rule in title_rules_for(item) if not rule.heads]
    if named:
        clauses = " Â· ".join(f"{rule.smm_clause} ({rule.title})" for rule in named)
        given = [rule.no_heads_reason for rule in named if rule.no_heads_reason]
        if given:
            return f"{clauses} governs this item. " + " ".join(given)
        return (f"{clauses} governs this item, and its sub-heads have not been transcribed. The "
                f"clause is known; the words are outstanding. Nothing here invents them — a head "
                f"with a made-up label is worse than a named gap.")
    for_this_bill = [rule for rule in TITLE_COVERAGE if rule.bill_no == bill_no]
    if not for_this_bill:
        return (f"No item-coverage list has been transcribed for Bill No.{bill_no}. Until one is, "
                f"nothing here can say what this rate must carry.")
    return (f"Bill No.{bill_no} has {len(for_this_bill)} transcribed coverage clause(s), and none "
            f"of them matched this item by title ({item.description[:60]!r}). Either this item is "
            f"governed by a clause nobody has transcribed yet, or its title does not read the way "
            f"the clause names it — which is a mapping to check, not a clause to write.")


def unmatched_rules(bill: ClientBill) -> list[dict]:
    """Transcribed clauses that matched NO item in this bill.

    The other half of the same honesty. A clause read off the pack and attached to nothing is a
    coverage head nobody will ever be asked about, and it looks identical to a clause that simply
    does not apply. Reported so a person can tell those apart — the usual cause is that the BQ
    calls the item something the clause does not.
    """
    matched = {rule.key for item in bill.items for rule in title_rules_for(item)}
    bills_present = {(item.bill_no or "").strip() for item in bill.items}
    return [
        {"rule": rule.key, "smm_clause": rule.smm_clause, "title": rule.title,
         "matched_on": list(rule.match),
         # A rule with no `bill_no` applies wherever its title appears, so "this bill has no
         # Bill No." would be nonsense for it. Three cases, three sentences.
         "why": (f"no item in this bill of quantities is titled with "
                 f"{' and '.join(repr(m) for m in rule.match)}" if not rule.bill_no else
                 f"no item in Bill No.{rule.bill_no} is titled with "
                 f"{' and '.join(repr(m) for m in rule.match)}")}
        for rule in TITLE_COVERAGE
        if rule.key not in matched and (not rule.bill_no or rule.bill_no in bills_present)
    ]


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
            # The cost the person named. Empty for every tick given before the column existed,
            # which reads as "asserted, no cost named" — the honest reading of what a tick was.
            entry.basis_key = mark.get("basis_key", "") or ""
        entries.append(entry)

    bill_mark = recorded.get(DEEMED_INCLUDED.key, {})
    bill_level = CoverageEntry(
        key=DEEMED_INCLUDED.key, label=DEEMED_INCLUDED.label,
        clause_ref=DEEMED_INCLUDED.clause_ref, scope=SCOPE_BILL,
        ticked=bool(bill_mark.get("ticked")), ticked_by=bill_mark.get("ticked_by", ""),
        ticked_at=bill_mark.get("ticked_at"),
        basis_key=bill_mark.get("basis_key", "") or "")

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
                                             else section_of(item)),
                        no_list_reason=("" if (has_list_for(item) or proposed)
                                        else _no_list_reason(item)))


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
                     "no_list_reason": coverage.no_list_reason,
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
        # Clauses transcribed off the pack that matched NO item here. A head nobody will be asked
        # about looks exactly like one that does not apply.
        "unmatched_rules": unmatched_rules(bill),
        "note": NO_LATER_CLAIM,
    }
