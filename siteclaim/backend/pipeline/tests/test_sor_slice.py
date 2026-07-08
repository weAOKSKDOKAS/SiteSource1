"""RT2-C4: the SoR attachment per enquiry is the ORIGINAL Schedule of Rates sliced to that unit's
section pages (a PDF named ``SoR_{unit}_Section_{X}.pdf``), not a generated ``.xlsx``. The section
page ranges are indexed at ingest; dispatch slices the original; a section that can't be located
falls back to the whole SoR flagged; with no original SoR uploaded (DEMO / no upload) the generated
sheet remains; and the priced-return sheet is never removable at the human gate."""

import base64

import pytest

from pipeline.stage_01_ingest.doc_index import DocIndexEntry, build_doc_entry, save_doc_index
from pipeline.stage_03_dispatch.drafts import assemble_firm_attachments, plan_for_firms
from pipeline.stage_03_dispatch.relevant_docs import (
    PRICED_RETURN,
    apply_attachment_overrides,
    resolve_section_plan,
)
from pipeline.workspace import Workspace
from schemas.models import DocType, ScopePackages, SorItem, TradeWorkPackage

fitz = pytest.importorskip("fitz")

_TID = "GE/2026/14"
_SR = "Schedule_of_Rates.pdf"


def _sor_pdf(pages):
    """A real multi-page SoR PDF. ``pages`` is a list of ``(header_or_None, body)`` — the header
    (when present) is its own top line, exactly as a section header sits above its item table."""
    doc = fitz.open()
    for header, body in pages:
        page = doc.new_page()
        y = 72
        if header:
            page.insert_text((72, y), header)
            y += 30
        page.insert_text((72, y), body)
    return doc.tobytes()


_THREE_SECTION_SOR = [
    ("SECTION A : PRELIMINARIES ITEMS", "A1 Provide site office"),
    (None, "A2 Maintain site office"),
    ("SECTION E : GROUND INVESTIGATION", "E1 Rotary drilling"),
    (None, "E2 Standpipes in trial pits"),
    ("SECTION I : LANDSCAPE", "I1 Soft landscape"),
]


def _item(section="E"):
    return SorItem(item_ref=f"{section}1", description="work", section=section)


# -- ingest: index the SoR's section page ranges ----------------------------
def test_ingest_indexes_the_sor_section_page_ranges():
    entry = build_doc_entry(_SR, DocType.SCHEDULE_OF_RATES, _sor_pdf(_THREE_SECTION_SOR))
    assert entry.kind == "schedule_of_rates" and entry.text_layer
    # A: header p0, body p1; E: p2-p3; I: p4 (each spans to the page before the next header).
    assert entry.sor_section_pages == {"A": [0, 1], "E": [2, 3], "I": [4]}


def test_a_sor_with_no_section_headers_indexes_no_ranges():
    entry = build_doc_entry(_SR, DocType.SCHEDULE_OF_RATES, _sor_pdf([
        (None, "Item A1 provide and maintain the site office for the works duration"),
        (None, "Item A2 remove the site office and reinstate on completion of the works"),
    ]))
    assert entry.kind == "schedule_of_rates" and entry.text_layer
    assert entry.sor_section_pages == {}  # nothing to slice by -> whole-SoR fallback at dispatch


def test_the_index_round_trips_through_save_and_load(tmp_path):
    from pipeline.stage_01_ingest.doc_index import load_doc_index

    ws = Workspace(tmp_path)
    save_doc_index(ws, _TID, [build_doc_entry(_SR, DocType.SCHEDULE_OF_RATES, _sor_pdf(_THREE_SECTION_SOR))])
    loaded = load_doc_index(ws, _TID)
    assert loaded[0].sor_section_pages == {"A": [0, 1], "E": [2, 3], "I": [4]}


# -- dispatch: the priced-return attachment is the section slice ------------
def _sr_entry(**over):
    base = dict(filename=_SR, kind="schedule_of_rates", text_layer=True, page_count=5,
                sor_section_pages={"A": [0, 1], "E": [2, 3], "I": [4]})
    base.update(over)
    return DocIndexEntry(**base)


def test_priced_return_is_the_sor_section_slice_not_the_generated_sheet():
    plan = resolve_section_plan(
        package_key="ground_investigation:E", trade="ground_investigation", section_title="DRILLING",
        items=[_item("E")], doc_index=[_sr_entry()], sor_sheet_name="SoR_gi.xlsx", section="E")
    sor = plan.attachments[0]
    assert sor.mode == "sliced" and sor.source_doc == _SR       # the ORIGINAL SoR, sliced
    assert sor.out_filename == "SoR_ground_investigation_Section_E.pdf"
    assert sor.pages == [2, 3, 4, 5] and PRICED_RETURN in sor.flags  # E pages (0-based 1..4) 1-based, ±1
    assert not any(a.mode == "generated" for a in plan.attachments)  # no generated .xlsx anymore


def test_priced_return_falls_back_to_whole_flagged_when_the_section_is_not_located():
    # The SoR is present and indexed, but this unit's section isn't among its ranges -> whole, flagged.
    plan = resolve_section_plan(
        package_key="piling:Z", trade="piling", section_title="PILING",
        items=[_item("Z")], doc_index=[_sr_entry()], sor_sheet_name="SoR_piling.xlsx", section="Z")
    sor = plan.attachments[0]
    assert sor.mode == "whole" and sor.source_doc == _SR
    assert "whole_section_not_located" in sor.flags and PRICED_RETURN in sor.flags


def test_priced_return_falls_back_to_scanned_whole_when_the_sor_has_no_text_layer():
    plan = resolve_section_plan(
        package_key="ground_investigation:E", trade="ground_investigation", section_title="DRILLING",
        items=[_item("E")], doc_index=[_sr_entry(text_layer=False, sor_section_pages={})],
        sor_sheet_name="SoR_gi.xlsx", section="E")
    sor = plan.attachments[0]
    assert sor.mode == "whole" and "scanned_whole" in sor.flags and PRICED_RETURN in sor.flags


def test_priced_return_is_the_generated_sheet_when_no_original_sor_was_uploaded():
    # DEMO / no upload: the doc_index carries no schedule_of_rates -> the generated .xlsx (unchanged).
    plan = resolve_section_plan(
        package_key="joinery_fitting_out:J", trade="joinery_fitting_out", section_title="FITTINGS",
        items=[_item("J")], doc_index=[], sor_sheet_name="SoR_joinery.xlsx", section="J")
    sor = plan.attachments[0]
    assert sor.mode == "generated" and sor.source_doc == "SoR_joinery.xlsx" and PRICED_RETURN in sor.flags


# -- assembly: the slice is sent under its friendly PDF name ----------------
def test_assembly_sends_the_sor_slice_under_its_friendly_pdf_name(tmp_path):
    ws = Workspace(tmp_path)
    data = _sor_pdf(_THREE_SECTION_SOR)
    ws.save_upload(_TID, _SR, data)
    save_doc_index(ws, _TID, [build_doc_entry(_SR, DocType.SCHEDULE_OF_RATES, data)])
    pkg = "ground_investigation:E"
    scope = ScopePackages(packages=[TradeWorkPackage(
        trade=pkg, scope_summary="Section E", sor_items=[_item("E")])])
    plan = plan_for_firms(scope, {pkg: ["F1"]}, tender_id=_TID, workspace=ws)[pkg]
    atts = assemble_firm_attachments(plan, ws, _TID, pkg)
    by = {a["filename"]: a for a in atts}
    name = "SoR_ground_investigation_Section_E.pdf"
    assert set(by) == {name}                       # only the priced-return slice (no other docs here)
    assert by[name]["mime"] == "application/pdf"    # a PDF now, not the .xlsx
    sliced = base64.b64decode(by[name]["content_b64"])
    with fitz.open(stream=sliced, filetype="pdf") as d:
        text = " ".join(p.get_text() for p in d)
        page_count = d.page_count
    assert page_count < 5 and "E1" in text and "A1" not in text  # sliced to E, not the whole SoR


def test_the_priced_return_slice_is_never_removable_or_whole_expandable_at_the_gate():
    plan = resolve_section_plan(
        package_key="ground_investigation:E", trade="ground_investigation", section_title="DRILLING",
        items=[_item("E")], doc_index=[_sr_entry()], sor_sheet_name="SoR_gi.xlsx", section="E")
    edited = apply_attachment_overrides(plan, removed=[_SR], whole=[_SR])
    sor = edited.attachments[0]
    assert sor.source_doc == _SR and sor.mode == "sliced" and sor.pages == [2, 3, 4, 5]  # untouched
