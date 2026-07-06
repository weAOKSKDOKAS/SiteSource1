"""Per-section relevant-document resolver + pymupdf slicing (Assembler v2: clause-driven)."""

import pytest

from pipeline.stage_01_ingest.doc_index import DocIndexEntry
from pipeline.stage_03_dispatch.relevant_docs import resolve_section_plan, slice_pdf
from schemas.models import SorItem


def _item(clause_refs, section="I", desc="work"):
    return SorItem(item_ref=f"{section}1", description=desc, section=section, clause_refs=clause_refs)


def test_ps_and_mm_sliced_by_clause_ref_not_trade_map():
    # The core fix: Section I references PS 7.34A / 7.37A (in PS-S07) and PB 71 (in the MM). The
    # resolver slices to exactly those — and does NOT pull the landscape PS-S26 by a trade guess,
    # even though the description reads "landscape".
    doc_index = [
        DocIndexEntry(filename="PS-S07.pdf", kind="particular_specification", spec_section_number="7",
                      text_layer=True, page_count=40, clause_index={"7.34A": [3], "7.37A": [4]}),
        DocIndexEntry(filename="PS-S26.pdf", kind="particular_specification", spec_section_number="26",
                      text_layer=True, page_count=10, clause_index={"26.1": [0]}),
        DocIndexEntry(filename="APPENDIX 7.pdf", kind="appendix", spec_section_number="7",
                      text_layer=False, page_count=58),
        DocIndexEntry(filename="MM-01.pdf", kind="method_of_measurement", text_layer=True,
                      page_count=20, clause_index={"PB 1": [0], "PB 71": [11]}),
        DocIndexEntry(filename="AECOM Clarification.pdf", kind="clarification", text_layer=True, page_count=2),
    ]
    items = [_item(["PS 7.34A", "PS 7.37A", "PB 71", "Appendix 7.4.1"], desc="Rotary drilling, landscape edging")]
    plan = resolve_section_plan(
        package_key="ground_investigation:I", trade="ground_investigation", section_title="DRILLING",
        items=items, doc_index=doc_index, sor_sheet_name="SoR_ground_investigation-I.xlsx", section="I")
    by = {a.source_doc: a for a in plan.attachments}
    assert by["SoR_ground_investigation-I.xlsx"].mode == "generated"       # always the SoR sheet
    ps = by["PS-S07.pdf"]
    assert ps.mode == "sliced" and set(ps.pages) == {3, 4, 5, 6} and ps.clauses == ["7.34A", "7.37A"]
    mm = by["MM-01.pdf"]
    assert mm.mode == "sliced" and set(mm.pages) == {11, 12, 13} and mm.clauses == ["PB 71"]  # not whole
    assert by["APPENDIX 7.pdf"].mode == "whole" and "scanned_whole" in by["APPENDIX 7.pdf"].flags
    assert by["AECOM Clarification.pdf"].mode == "whole"
    assert "PS-S26.pdf" not in by                                          # not pulled by a trade/topic guess
    assert plan.missing_specs == []


def test_mm_is_not_attached_when_the_section_references_no_pb():
    doc_index = [DocIndexEntry(filename="MM-01.pdf", kind="method_of_measurement", text_layer=True,
                               page_count=20, clause_index={"PB 71": [11]})]
    plan = resolve_section_plan(
        package_key="x", trade="joinery_fitting_out", section_title="FITTINGS",
        items=[_item(["PS 12.3"], section="J")], doc_index=doc_index, sor_sheet_name="s.xlsx")
    assert "MM-01.pdf" not in {a.source_doc for a in plan.attachments}     # no longer whole-to-all


def test_gs_reference_amended_by_a_present_ps_clause_is_not_missing():
    # GS 7.34 is amended by PS 7.34A (present in PS-S07) -> the amendment rides in the PS extract,
    # and it is NOT flagged missing.
    doc_index = [DocIndexEntry(filename="PS-S07.pdf", kind="particular_specification", spec_section_number="7",
                               text_layer=True, page_count=40, clause_index={"7.34A": [3]})]
    plan = resolve_section_plan(
        package_key="x", trade="ground_investigation", section_title="DRILLING",
        items=[_item(["GS 7.34"])], doc_index=doc_index, sor_sheet_name="s.xlsx")
    ps = next(a for a in plan.attachments if a.source_doc == "PS-S07.pdf")
    assert ps.mode == "sliced" and ps.clauses == ["7.34A"]                 # GS 7.34 -> PS 7.34A pages
    assert plan.missing_specs == []


def test_gs_reference_without_a_present_amendment_is_flagged_missing():
    # GS 7.34 with no PS amendment present -> the base GS text is not enclosed; flag it.
    doc_index = [DocIndexEntry(filename="PS-S07.pdf", kind="particular_specification", spec_section_number="7",
                               text_layer=True, page_count=40, clause_index={"7.99": [3]})]
    plan = resolve_section_plan(
        package_key="x", trade="ground_investigation", section_title="DRILLING",
        items=[_item(["GS 7.34"])], doc_index=doc_index, sor_sheet_name="s.xlsx")
    assert [m.spec for m in plan.missing_specs] == ["General Specification 7.34"]  # never a silent gap
    ps = next(a for a in plan.attachments if a.source_doc == "PS-S07.pdf")
    assert ps.mode == "whole" and "whole_clause_not_located" in ps.flags   # relevant section, clause unresolved


def test_unlocatable_ps_clause_falls_back_to_whole_with_a_flag():
    doc_index = [DocIndexEntry(filename="PS-S07.pdf", kind="particular_specification", spec_section_number="7",
                               text_layer=True, page_count=40, clause_index={"7.99": [5]})]
    plan = resolve_section_plan(
        package_key="x", trade="ground_investigation", section_title="DRILLING",
        items=[_item(["PS 7.13.1"])], doc_index=doc_index, sor_sheet_name="s.xlsx")
    ps = next(a for a in plan.attachments if a.source_doc == "PS-S07.pdf")
    assert ps.mode == "whole" and ps.flags == ["whole_clause_not_located"]  # never silently whole


def test_referenced_but_unsupplied_ps_section_is_flagged_not_dropped():
    plan = resolve_section_plan(
        package_key="x", trade="general", section_title="PRELIMINARIES",
        items=[_item(["PS 28.2.07"], section="P")], doc_index=[], sor_sheet_name="SoR_x.xlsx")
    assert [m.spec for m in plan.missing_specs] == ["PS Section 28"]        # PS section not supplied
    assert plan.attachments[0].mode == "generated"                         # SoR sheet still included


def test_plan_always_has_sor_sheet_and_clarifications_even_with_no_refs():
    doc_index = [DocIndexEntry(filename="Clar.pdf", kind="clarification", text_layer=True, page_count=1)]
    plan = resolve_section_plan(
        package_key="x", trade="joinery_fitting_out", section_title="FITTINGS",
        items=[_item([], section="J", desc="Loose furniture, no references")],
        doc_index=doc_index, sor_sheet_name="s.xlsx")
    modes = {a.source_doc: a.mode for a in plan.attachments}
    assert modes["s.xlsx"] == "generated" and modes["Clar.pdf"] == "whole"


def test_onward_appendix_from_a_ps_clause_is_pulled_and_sliced():
    # Section references PS 7.07A; the PS clause 7.07A points onward to Appendix 7.8.20; the firm's
    # bundle gets the PS sliced to 7.07A AND the separate appendix document sliced to 7.8.20.
    doc_index = [
        DocIndexEntry(filename="PS-S07.pdf", kind="particular_specification", spec_section_number="7",
                      text_layer=True, page_count=40, clause_index={"7.07A": [3]},
                      clause_onward_appendices={"7.07A": ["7.8.20"]}),
        DocIndexEntry(filename="APP-7.pdf", kind="appendix", spec_section_number="7",
                      text_layer=True, page_count=30, clause_index={"7.8.20": [12]}),
    ]
    plan = resolve_section_plan(
        package_key="ground_investigation:G", trade="ground_investigation", section_title="PILING",
        items=[_item(["PS 7.07A"], section="G")], doc_index=doc_index, sor_sheet_name="s.xlsx")
    by = {a.source_doc: a for a in plan.attachments}
    assert by["PS-S07.pdf"].mode == "sliced" and by["PS-S07.pdf"].clauses == ["7.07A"]
    app = by["APP-7.pdf"]
    assert app.mode == "sliced" and app.clauses == ["7.8.20"] and set(app.pages) == {12, 13, 14}
    assert plan.missing_specs == []


def test_onward_appendix_with_no_appendix_document_is_flagged_missing():
    doc_index = [DocIndexEntry(filename="PS-S07.pdf", kind="particular_specification", spec_section_number="7",
                               text_layer=True, page_count=40, clause_index={"7.07A": [3]},
                               clause_onward_appendices={"7.07A": ["7.8.20"]})]
    plan = resolve_section_plan(
        package_key="x", trade="ground_investigation", section_title="PILING",
        items=[_item(["PS 7.07A"], section="G")], doc_index=doc_index, sor_sheet_name="s.xlsx")
    assert "Appendix 7" in [m.spec for m in plan.missing_specs]  # onward appendix, no doc -> flagged


def test_slice_pdf_extracts_requested_pages():
    fitz = pytest.importorskip("fitz")
    doc = fitz.open()
    for i in range(6):
        doc.new_page().insert_text((72, 72), f"page {i + 1}")
    data = doc.tobytes()
    sliced = slice_pdf(data, [2, 4])
    with fitz.open(stream=sliced, filetype="pdf") as out:
        assert out.page_count == 2
        assert "page 2" in out[0].get_text() and "page 4" in out[1].get_text()
    assert slice_pdf(data, []) == data  # empty -> whole file, never fabricated
