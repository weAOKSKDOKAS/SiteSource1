"""Per-section relevant-document resolver + pymupdf slicing (relevant-doc assembler, RD3)."""

import pytest

from pipeline.stage_01_ingest.doc_index import DocIndexEntry
from pipeline.stage_03_dispatch.relevant_docs import resolve_section_plan, slice_pdf
from schemas.models import SorItem


def _items(descs, section="E"):
    return [SorItem(item_ref=f"{section}{i}", description=d, section=section) for i, d in enumerate(descs)]


def test_plan_slices_ps_and_attaches_scanned_appendix_whole():
    doc_index = [
        DocIndexEntry(filename="PS-S07.pdf", kind="particular_specification", spec_section_number="7",
                      text_layer=True, page_count=40, clause_index={"7.13.1": [11], "7.14": [30]}),
        DocIndexEntry(filename="APPENDIX 7.pdf", kind="appendix", spec_section_number="7",
                      text_layer=False, page_count=58),
        DocIndexEntry(filename="MoM.pdf", kind="method_of_measurement", text_layer=True, page_count=10),
        DocIndexEntry(filename="AECOM Clarification.pdf", kind="clarification", text_layer=True, page_count=2),
        DocIndexEntry(filename="PS-S99.pdf", kind="particular_specification", spec_section_number="99",
                      text_layer=True, page_count=5, clause_index={"99.1": [0]}),
    ]
    items = _items(["Rotary drilling per PS 7.13.1 and PS 7.14, see Appendix 7.4.1"])
    plan = resolve_section_plan(
        package_key="ground_investigation:E", trade="ground_investigation", section_title="DRILLING",
        items=items, doc_index=doc_index, sor_sheet_name="SoR_ground_investigation-E.xlsx", section="E")
    by = {a.source_doc: a for a in plan.attachments}
    assert by["SoR_ground_investigation-E.xlsx"].mode == "generated"      # always the SoR sheet
    assert by["MoM.pdf"].mode == "whole" and by["AECOM Clarification.pdf"].mode == "whole"
    ps = by["PS-S07.pdf"]                                                 # sliced to clauses ±1
    assert ps.mode == "sliced" and set(ps.pages) == {11, 12, 13, 30, 31, 32}
    assert by["APPENDIX 7.pdf"].mode == "whole" and "scanned_whole" in by["APPENDIX 7.pdf"].flags
    assert "PS-S99.pdf" not in by                                         # unrelated section not attached
    assert plan.missing_specs == []


def test_referenced_but_unsupplied_spec_is_flagged_not_dropped():
    plan = resolve_section_plan(
        package_key="x", trade="general", section_title="PRELIMINARIES",
        items=_items(["Prelim item per PS 28.2.07"]), doc_index=[], sor_sheet_name="SoR_x.xlsx")
    assert [m.spec for m in plan.missing_specs] == ["PS Section 28"]      # never a silent gap
    assert plan.attachments[0].mode == "generated"                       # SoR sheet still included


def test_text_layer_ps_with_no_resolving_clause_falls_back_to_whole():
    doc_index = [DocIndexEntry(filename="PS-S07.pdf", kind="particular_specification", spec_section_number="7",
                               text_layer=True, page_count=40, clause_index={"7.99": [5]})]
    plan = resolve_section_plan(
        package_key="x", trade="ground_investigation", section_title="DRILLING",
        items=_items(["Drilling per PS 7.13.1"]), doc_index=doc_index, sor_sheet_name="s.xlsx")
    ps = next(a for a in plan.attachments if a.source_doc == "PS-S07.pdf")
    assert ps.mode == "whole" and not ps.flags  # text-layer but the clause did not resolve to a page


def test_plan_always_has_sor_sheet_and_clarifications_even_with_no_refs():
    doc_index = [DocIndexEntry(filename="Clar.pdf", kind="clarification", text_layer=True, page_count=1)]
    plan = resolve_section_plan(
        package_key="x", trade="joinery_fitting_out", section_title="FITTINGS",
        items=_items(["Loose furniture, no references"]), doc_index=doc_index, sor_sheet_name="s.xlsx")
    modes = {a.source_doc: a.mode for a in plan.attachments}
    assert modes["s.xlsx"] == "generated" and modes["Clar.pdf"] == "whole"


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
