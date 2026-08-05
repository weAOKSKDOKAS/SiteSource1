"""FIX 9 — the priced-return document, and saying so when it is not the one the design intends.

Observed live: the Gmail draft carried ``SoR_ground-investigation-4.xlsx`` (7K). The design sends
the ORIGINAL Schedule of Rates sliced to the unit's section pages — ``relevant_docs`` emits
``SoR_{unit}_Section_{X}.pdf`` "when an indexed SoR carries the section(s)" — because a
subcontractor returns what they were sent, and the return format follows the dispatch format.

**Why the slice did not fire.** ``_priced_return_attachment`` filters ``doc_index`` for
``kind == "schedule_of_rates"``; with no entry the first early return emits the generated sheet.
The xlsx therefore came from the PLAN itself — ``mode="generated"`` — not from
``build_attachments`` reaching the draft another way; ``api.py`` assembles only
``assemble_firm_attachments(plan, …)``. That much held up.

**The CAUSE named here was wrong, and FIX 10 corrects it.** This file originally blamed the
workbook bill: an .xlsx is indexed with ``text_layer=False`` and no section pages, so there was
nothing to slice. True of a workbook, and not why. The index was empty because the BRIDGE NEVER
PERSISTED ONE — ``bridge/scope.py`` built a doc index, read ``sor_section_pages`` off it for the
provenance guard, and discarded it, while ``save_doc_index``'s only call site was
``/ingest-upload``. Every archive/bridge tender hit this branch unconditionally, and the pack
ships ``I-ND_2025_04_BQ-0.pdf`` beside the workbook which would have been discarded just the same.

The tests below are unchanged and still correct: they exercise the branch given an empty or
unhelpful index, which stays reachable (DEMO, no upload, a genuinely workbook-only bill).

**And the slicer cuts on PAGE BOUNDS, not the heading chain.** ``pages = [p + 1 for p in
sorted({… hit.sor_section_pages[sk] …})]`` — the span from ``_spans`` over line-start ``SECTION n``
markers. A BQ item's full description is an ancestor path chain, so a slice cut at a page boundary
ships items whose parent headers sit on an earlier page. Recorded here; not changed by this fix.
"""

import pytest
from pipeline.stage_01_ingest.doc_index import DocIndexEntry
from pipeline.stage_03_dispatch.relevant_docs import (
    PRICED_RETURN,
    SUBSTITUTED,
    _priced_return_attachment,
)


def _sor(filename="SoR.pdf", *, text_layer=True, sections=None):
    return DocIndexEntry(
        filename=filename, kind="schedule_of_rates", text_layer=text_layer,
        sor_section_pages=sections or {}, page_count=40,
    )


def _plan(doc_index, sections=("G",)):
    return _priced_return_attachment(
        doc_index, sections=list(sections), trade="ground_investigation",
        package_key="ground_investigation:G", sor_sheet_name="SoR_ground-investigation-G.xlsx")


# ---------------------------------------------------------------------------
# The path that SHOULD fire, and does when there is something to slice
# ---------------------------------------------------------------------------
def test_an_indexed_sor_is_sliced_to_the_units_section():
    att = _plan([_sor(sections={"G": [4, 5, 6]})])
    assert att.mode == "sliced"
    assert att.pages == [5, 6, 7]                       # 1-based, from the 0-based index
    assert att.out_filename == "SoR_ground_investigation_Section_G.pdf"
    assert SUBSTITUTED not in att.flags                 # this IS the intended artifact
    assert PRICED_RETURN in att.flags


def test_the_slice_is_not_marked_substituted_even_across_several_sections():
    att = _priced_return_attachment(
        [_sor(sections={"G": [1, 2], "H": [3]})], sections=["G", "H"],
        trade="gi", package_key="gi", sor_sheet_name="s.xlsx")
    assert att.mode == "sliced" and SUBSTITUTED not in att.flags


# ---------------------------------------------------------------------------
# The branch this pack actually took
# ---------------------------------------------------------------------------
def test_no_sor_in_the_index_emits_the_generated_sheet_and_says_so():
    """An empty index yields no `schedule_of_rates` entry, so the generated .xlsx goes instead.
    Still reachable after FIX 10 — DEMO, no upload, or a genuinely workbook-only bill."""
    att = _plan([])
    assert att.mode == "generated"
    assert att.source_doc == "SoR_ground-investigation-G.xlsx"
    assert SUBSTITUTED in att.flags
    assert "GENERATED sheet, not the original bill" in att.reason
    assert "workbook" in att.reason                     # names the real cause on this pack


def test_a_workbook_bill_is_indexed_without_section_pages():
    """The premise, from the indexer rather than assumed: a non-PDF yields no page text, so
    `text_layer` is False and `sor_section_pages` is empty — nothing to slice on."""
    from pipeline.stage_01_ingest.doc_index import build_doc_entry
    from schemas.models import DocType

    entry = build_doc_entry("E-ND_2025_04-BQ-2.xlsx", DocType.SCHEDULE_OF_RATES, b"PK\x03\x04 not a pdf")
    assert entry.text_layer is False
    assert entry.sor_section_pages == {}


def test_an_sor_whose_section_is_not_located_sends_the_whole_bill_and_says_so():
    att = _plan([_sor(sections={"Z": [1, 2]})])
    assert att.mode == "whole"
    assert SUBSTITUTED in att.flags
    assert "WHOLE bill, not this unit's section" in att.reason
    assert "may price sections it was not enquired on" in att.reason


def test_a_scanned_sor_says_it_has_no_text_layer():
    att = _plan([_sor(text_layer=False)])
    assert att.mode == "whole" and SUBSTITUTED in att.flags
    assert "no text layer (scanned)" in att.reason


# ---------------------------------------------------------------------------
# The gate sees it BEFORE anything is drafted
# ---------------------------------------------------------------------------
def test_the_plan_preview_carries_the_flag_so_the_gate_can_show_it():
    """The response shape is unchanged — two frontends read /dispatch/plan as a list — because the
    flag and the reason are already ON the data. Moving the shape to carry one sentence would have
    broken both to say something the list already contains."""
    att = _plan([])
    assert SUBSTITUTED in att.flags and att.reason


def test_the_drafts_response_states_it_too(monkeypatch):
    """Belt and braces: if the operator skipped the preview, the response that actually created
    the drafts is the last place the swap is stated before the enquiry leaves."""
    import api
    from pipeline.stage_03_dispatch.relevant_docs import SectionPlan

    plans = {"ground_investigation:G": SectionPlan(
        package_key="ground_investigation:G", trade="ground_investigation",
        attachments=[_plan([])])}
    notice = api._substitution_notice(plans)
    assert "PRICED-RETURN DOCUMENT SUBSTITUTED" in notice
    assert "ground_investigation:G" in notice
    assert "generated .xlsx sheet" in notice


def test_no_notice_when_every_document_is_the_intended_one():
    import api
    from pipeline.stage_03_dispatch.relevant_docs import SectionPlan

    plans = {"gi:G": SectionPlan(package_key="gi:G", trade="gi",
                                 attachments=[_plan([_sor(sections={"G": [1]})])])}
    assert api._substitution_notice(plans) == ""


# ---------------------------------------------------------------------------
# The xlsx generator stays — it is the zero-model return reader
# ---------------------------------------------------------------------------
def test_the_workbook_generator_and_reader_are_untouched():
    """`parse_sor_xlsx` is the deterministic zero-model return path and stays the reader for any
    workbook that does come back — including every workbook this substitution causes to go out."""
    from pipeline.stage_03_dispatch.attachments import generate_sor_sheet
    from pipeline.stage_04_level.reply_xlsx import parse_sor_xlsx

    assert callable(generate_sor_sheet) and callable(parse_sor_xlsx)
