"""Three more silences, each losing something the operator was told nothing about.

**The bill has revisions and nothing contested them.** `_priced_return_attachment` chose from
`sr_entries` with `next(...)` — LIST POSITION. The pack reissues the bill twice (`TA #1/…_BQ-1.pdf`,
`TA #2/…_BQ-2.pdf`), so a firm could be handed the SUPERSEDED original to price: the single most
consequential document in an enquiry, decided by whichever order the index happened to be built in.
Every other population had this contest; the one the firm actually fills in did not.

**Documents no branch selects.** Six kinds are handled. `other` is not — so the pack's General
Conditions of Tender, Special Conditions, Notes to Tenderers and Site Information reached no branch,
produced no attachment and no line. On ND/2025/04 that is 31 documents absent from every enquiry
with nothing said. They are COUNTED AND NAMED, not attached: whether a subcontractor needs the GCT
is the operator's judgement, but "we did not send these" has to be visible before dispatch.

**A completeness guard that could not match its input.** `sequence_gaps` capped on the bill's whole
numbering SPAN while its own constant said *"a gap larger than this is a different bill, not a
dropped row"*. Any bill numbered past ~40 had its ENTIRE report suppressed — and a real bill is
exactly that. ND/2025/04's Bill 1 runs past item 53 and its only missing row is item 53, so the one
mechanism that reports dropped bill rows was switched off on the one bill that had a gap.
"""

import pytest

from pipeline.stage_01_ingest.doc_index import DocIndexEntry
from pipeline.stage_01_ingest.ingest import sequence_gaps
from pipeline.stage_03_dispatch.relevant_docs import PRICED_RETURN, resolve_section_plan
from schemas.models import ScopePackages, SorItem, TradeWorkPackage

BQ0 = "BQ/I-ND_2025_04_BQ-0.pdf"
BQ1 = "TA #1/BQ/I-ND_2025_04_BQ-1.pdf"
BQ2 = "TA #2/BQ/I-ND_2025_04_BQ-2.pdf"


def _bill(path: str) -> DocIndexEntry:
    return DocIndexEntry(filename=path, kind="schedule_of_rates", text_layer=True, page_count=26,
                         sor_section_pages={"2": [8, 9]})


def _e(path: str, kind: str, pages: int = 16) -> DocIndexEntry:
    return DocIndexEntry(filename=path, kind=kind, text_layer=True, page_count=pages)


def _plan(index):
    return resolve_section_plan(
        package_key="gi:2", trade="ground_investigation", section_title="GI", section="2",
        sections=["2"], items=[SorItem(item_ref="2.1", description="Drilling", section="2")],
        doc_index=list(index), sor_sheet_name="SoR_gi.xlsx")


def _priced(plan):
    return next(a for a in plan.attachments if PRICED_RETURN in a.flags)


# -- the bill's own revisions ----------------------------------------------------------------------
@pytest.mark.parametrize("order", ["as-built", "reversed"])
def test_the_operative_bill_is_priced_whatever_order_the_index_holds(order):
    index = [_bill(BQ0), _bill(BQ1), _bill(BQ2)]
    if order == "reversed":
        index.reverse()

    assert _priced(_plan(index)).source_doc == BQ2


def test_a_superseded_bill_is_not_enclosed_at_all():
    docs = {a.source_doc for a in _plan([_bill(BQ0), _bill(BQ1)]).attachments}
    assert BQ1 in docs and BQ0 not in docs


def test_an_unrevised_bill_is_still_the_priced_return():
    """The contest must not cost the ordinary case: one bill, no reissue, still chosen."""
    assert _priced(_plan([_bill(BQ0)])).source_doc == BQ0


def test_the_xlsx_companion_is_not_a_revision_of_the_pdf():
    """`E-…_BQ-0.xlsx` is a different RENDERING of the bill, not a later revision of it. Keyed on
    the basename, their stems differ, so neither supersedes the other."""
    workbook = DocIndexEntry(filename="BQ/E-ND_2025_04_BQ-0.xlsx", kind="schedule_of_rates",
                             text_layer=False, page_count=0)
    docs = {a.source_doc for a in _plan([_bill(BQ0), workbook]).attachments}
    assert BQ0 in docs, "the PDF is still sliceable and still chosen"


# -- documents no branch selects ---------------------------------------------------------------------
def test_documents_that_reach_no_enquiry_are_counted_and_named():
    index = [_bill(BQ0), _e("GCT/I-ND_2025_04-GCT-0.pdf", "other"),
             _e("SCT/I-ND_2025_04-SCT-0.pdf", "other"), _e("SI/I-ND_2025_04-SI-0.pdf", "other")]
    note = next(m for m in _plan(index).missing_specs if "reach NO enquiry" in m.spec)

    assert "3 'other' document(s)" in note.spec
    assert "48 pages" in note.spec
    assert "GCT/I-ND_2025_04-GCT-0.pdf" in note.spec
    assert "attach at the gate" in note.referenced_by


def test_they_are_reported_not_attached():
    """Enclosing them by default is the other error: a firm buried in a 232 MB pack reads nothing."""
    index = [_bill(BQ0), _e("GCT/I-ND_2025_04-GCT-0.pdf", "other")]
    assert "GCT/I-ND_2025_04-GCT-0.pdf" not in {a.source_doc for a in _plan(index).attachments}


def test_the_ps_index_is_not_named_by_this_report():
    """C15's lesson: a fix that adds a report can add a false alarm. Not enclosing the
    specification's contents page is a decision already taken and already tested, so naming it
    here would be noise in a report whose value is that every line is worth reading."""
    index = [_bill(BQ0), _e("S/PS/I-ND_2025_04-S_PS_Index-0.pdf", "ps_index")]
    assert not any("reach NO enquiry" in m.spec for m in _plan(index).missing_specs)


def test_a_pack_where_every_document_is_handled_says_nothing():
    index = [_bill(BQ0), _e("TA #1/I-ND_2025_04-Tender_Addendum_No_1.pdf", "clarification")]
    assert not any("reach NO enquiry" in m.spec for m in _plan(index).missing_specs)


# -- the completeness guard ---------------------------------------------------------------------------
def _scope(refs: list[str]) -> ScopePackages:
    return ScopePackages(project_name="ND/2025/04", packages=[TradeWorkPackage(
        trade="ground_investigation", scope_summary="GI",
        sor_items=[SorItem(item_ref=r) for r in refs])])


def test_the_real_packs_only_gap_is_reported():
    """Bill 1 runs past item 53 and item 53 is missing. Capping on the SPAN suppressed the whole
    report for exactly that bill."""
    refs = [f"1.{i}" for i in range(1, 61) if i != 53]
    assert sequence_gaps(_scope(refs)) == {"1": [53]}


def test_a_long_run_of_missing_numbers_is_still_suppressed():
    """The behaviour the cap exists for: a long CONTIGUOUS run means the numbering is not
    contiguous — a different block — rather than dropped rows."""
    refs = [f"2.{i}" for i in range(1, 6)] + [f"2.{i}" for i in range(80, 86)]
    assert sequence_gaps(_scope(refs)) == {}


def test_a_short_gap_survives_beside_a_long_one():
    """Per RUN, not per bill: one unreadable block must not suppress a real single-row gap."""
    refs = ([f"3.{i}" for i in range(1, 10) if i != 4]      # 4 missing — a dropped row
            + [f"3.{i}" for i in range(90, 95)])            # a 80-wide jump — a different block
    assert sequence_gaps(_scope(refs)) == {"3": [4]}


def test_a_complete_bill_reports_nothing():
    assert sequence_gaps(_scope([f"1.{i}" for i in range(1, 61)])) == {}


def test_the_ends_are_still_never_reported():
    """A bill may simply begin at 3, and its last item is unknowable from the inside — inventing
    either end produces a warning nobody can act on, which is how a real signal gets ignored."""
    assert sequence_gaps(_scope(["1.3", "1.4", "1.5"])) == {}
