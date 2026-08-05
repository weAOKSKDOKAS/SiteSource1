"""THE SEAM: what the assembler produced is what reaches Gmail — on the bridge path too.

The defect this exists to catch shipped because both ends were tested alone, each in a shape that
agreed with itself, and the shape the live path actually passes was exercised by neither.

`assemble_firm_attachments` resolves each planned file through `Workspace.doc_path(tender,
att.source_doc)`. `/ingest-upload` writes every original to `docs/<filename>` and indexes it under
that same filename, so the lookup finds it — and `test_draft_assembly.py` builds its run exactly
that way, which is why it passes and always did.

The BRIDGE cannot. Its documents are client_boq PARTS: indexed under the part's TITLE ("Schedule of
Rates") and living at the part's own cut-pdf path. `doc_path(tender, "Schedule of Rates")` is not a
file. `_attachment_bytes` returned None for every attachment, `assemble_firm_attachments` skipped
every one in silence, and the drafts went out EMPTY — while the preview, which reads the doc index
and never touches disk, showed the full relevant-only set.

So the test drives the real chain end to end: bridge split -> plan -> assemble -> the draft payload
built exactly as `api.py` builds it -> `create_gmail_drafts` against a stub service -> the bytes in
the MIME message. **Fixtures, not the real pack**: the pdfs below are written by pymupdf.
"""

import base64
import email as _email

import pytest
from fastapi.testclient import TestClient

from bridge import parts as parts_mod
from pipeline.stage_03_dispatch.drafts import (
    assemble_firm_attachments,
    create_gmail_drafts,
    plan_for_firms,
)
from pipeline.tests.test_gmail_client import StubService
from pipeline.workspace import Workspace
from schemas.models import ScopePackages, SorItem, TradeWorkPackage

fitz = pytest.importorskip("fitz")

SET_ID = "gi-2026-12"
PKG = "ground_investigation:G"

BILL_PAGES = [
    "SECTION G : DRILLING AND SAMPLING\n"
    "G1   Cable percussion borehole      m    120   Clause Ref: PS 3.1",
    "SECTION H : INSTRUMENTATION\n"
    "H1   Standpipe piezometer          nr     12",
]
SPEC_PAGES = [
    "SECTION 3 : GROUND INVESTIGATION\n"
    "3.1  Cable percussion boring shall be carried out in accordance with the GS.",
    "3.9  Piezometers shall be installed and tested on completion.",
]


@pytest.fixture
def client():
    import api

    return TestClient(api.app)


@pytest.fixture
def make_pdf(tmp_path):
    def _make(name: str, pages: list[str]) -> str:
        doc = fitz.open()
        for body in pages:
            page = doc.new_page()
            y = 70
            for line in body.splitlines():
                page.insert_text((55, y), line, fontsize=10)
                y += 14
        path = tmp_path / name
        doc.save(str(path))
        doc.close()
        return str(path)

    return _make


class StubClient:
    def complete_json(self, *, system, user, target_model, **_kw):
        return ScopePackages(project_name="GI/2026/12", packages=[TradeWorkPackage(
            trade="ground_investigation", scope_summary="Ground investigation",
            sor_items=[
                SorItem(item_ref="G1", description="Cable percussion borehole", unit="m",
                        qty=120.0, section="G", clause_refs=["PS 3.1"]),
                SorItem(item_ref="H1", description="Standpipe piezometer", unit="nr", qty=12.0,
                        section="H"),
            ],
        )])


@pytest.fixture
def split_set(client, make_set, part_spec, make_pdf, tmp_path, monkeypatch):
    """A bridge set, split for real — the doc index is written by the split, not by the test."""
    monkeypatch.setenv("SITESOURCE_WORKDIR", str(tmp_path / "ws"))
    monkeypatch.setattr("pipeline.stage_01_ingest.ingest.LLMClient", lambda *a, **k: StubClient())
    specs = [
        part_spec(1, "SR", "Schedule of Rates", "pricing", end=2),
        part_spec(2, "PS", "Particular Specification", "specifications", end=2),
    ]
    paths = {
        specs[0].part_id: make_pdf("bill.pdf", BILL_PAGES),
        specs[1].part_id: make_pdf("spec.pdf", SPEC_PAGES),
    }
    make_set(SET_ID, "Contract No. GI/2026/12", specs, pdf_paths=paths)
    parts_mod.confirm_bill_parts(SET_ID, [specs[0].part_id])
    split = client.post(f"/bridge/{SET_ID}/scope").json()
    return _dispatched_scope(split["scope"])


def _dispatched_scope(scope_json: dict) -> ScopePackages:
    """The scope as the DISPATCH step sends it — `route_units` keys, `trade: package_key`."""
    from pipeline.routing.split import route_units

    scope = ScopePackages.model_validate(scope_json)
    units = route_units(scope, split_keys={p.trade for p in scope.packages})
    return ScopePackages(
        project_name=scope.project_name,
        packages=[u["package"].model_copy(update={"trade": u["package_key"]}) for u in units],
    )


def _draft_payload(atts: list[dict]) -> dict:
    """The draft dict EXACTLY as `api.py::post_dispatch_drafts` builds it."""
    return {"firm_id": "F1", "to": "f1@example.com", "subject": "RFQ [SiteSource Ref: r-1]",
            "body": "Please price the attached.", "ref": "r-1", "attachments": atts}


def _mime_attachments(svc: StubService) -> dict:
    (name, payload), = svc.calls
    assert name == "drafts.create"
    msg = _email.message_from_bytes(base64.urlsafe_b64decode(payload["body"]["message"]["raw"]))
    return {p.get_filename(): p.get_payload(decode=True) for p in msg.walk() if p.get_filename()}


# -- the seam ---------------------------------------------------------------------------------------
def test_every_assembled_attachment_reaches_the_gmail_call_with_its_bytes(split_set):
    """The equivalence the two isolated tests never checked, on the shape the live path passes."""
    ws = Workspace()
    plan = plan_for_firms(split_set, {PKG: ["F1"]}, tender_id=SET_ID, workspace=ws)[PKG]
    assert len(plan.attachments) >= 2, "the preview shows a set; the seam is about delivering it"

    atts = assemble_firm_attachments(plan, ws, SET_ID, PKG)
    assert len(atts) == len(plan.attachments)          # NOTHING was skipped

    svc = StubService(draft_result={"id": "d-1"})
    drafted, failed = create_gmail_drafts([_draft_payload(atts)], service=svc)
    assert drafted == ["F1"] and failed == []

    arrived = _mime_attachments(svc)
    # Every assembled file is in the message, byte for byte.
    assert set(arrived) == {a["filename"] for a in atts}
    for a in atts:
        assert arrived[a["filename"]] == base64.b64decode(a["content_b64"])
        assert arrived[a["filename"]], "an attachment that arrives empty is not an attachment"


def test_the_bridge_path_attaches_the_sliced_bill_and_the_sliced_spec(split_set):
    """Named, so a regression says WHICH document went missing rather than just 'fewer'."""
    ws = Workspace()
    plan = plan_for_firms(split_set, {PKG: ["F1"]}, tender_id=SET_ID, workspace=ws)[PKG]
    atts = assemble_firm_attachments(plan, ws, SET_ID, PKG)

    names = {a["filename"] for a in atts}
    assert any("Section_G" in n for n in names)        # the bill, sliced to this unit's section
    assert "Particular Specification" in names
    # And the bill slice is a real PDF, not an empty placeholder.
    bill = next(a for a in atts if "Section_G" in a["filename"])
    assert base64.b64decode(bill["content_b64"]).startswith(b"%PDF")


def test_a_part_indexed_by_title_resolves_through_its_recorded_source_path(split_set):
    """The fix itself. The index names a document by the PART TITLE; no such file is in `docs/`."""
    from pipeline.stage_01_ingest.doc_index import load_doc_index

    ws = Workspace()
    entries = {e.filename: e for e in load_doc_index(ws, SET_ID)}
    assert "Schedule of Rates" in entries
    assert not ws.doc_path(SET_ID, "Schedule of Rates").is_file()   # it never was a file
    assert entries["Schedule of Rates"].source_path.endswith(".pdf")
    from pathlib import Path

    assert Path(entries["Schedule of Rates"].source_path).is_file()  # ...and this one is


def test_a_missing_source_is_reported_rather_than_skipped_in_silence(split_set, monkeypatch):
    """Skipping stays correct — a source that is not there cannot be fabricated. Silence does not.

    Silence is why an empty draft could ship while the preview showed the full set.
    """
    from pipeline.stage_01_ingest import doc_index as di

    ws = Workspace()
    plan = plan_for_firms(split_set, {PKG: ["F1"]}, tender_id=SET_ID, workspace=ws)[PKG]
    # Break every recorded path — the exact condition that was silent before.
    entries = [e.model_copy(update={"source_path": "/nowhere/at/all.pdf"})
               for e in di.load_doc_index(ws, SET_ID)]
    di.save_doc_index(ws, SET_ID, entries)

    notes: list[str] = []
    atts = assemble_firm_attachments(plan, ws, SET_ID, PKG, on_note=notes.append)
    assert len(atts) < len(plan.attachments)
    assert notes and all("NOT attached" in n for n in notes)
    assert any("Schedule of Rates" in n for n in notes)      # it names the document


# -- the upload path is untouched --------------------------------------------------------------------
def test_the_upload_shape_still_resolves_through_docs_dir(tmp_path):
    """`/ingest-upload` records no `source_path` and must keep working on the `docs/` lookup."""
    from pipeline.stage_01_ingest.doc_index import DocIndexEntry, save_doc_index
    from pipeline.stage_03_dispatch.relevant_docs import PlanAttachment, SectionPlan

    ws = Workspace(tmp_path)
    doc = fitz.open()
    doc.new_page().insert_text((72, 72), "Clarification No. 1")
    data = doc.tobytes()
    doc.close()
    ws.save_upload("GE/2026/14", "Clar.pdf", data)
    save_doc_index(ws, "GE/2026/14", [DocIndexEntry(filename="Clar.pdf", kind="clarification",
                                                    text_layer=True, page_count=1)])

    plan = SectionPlan(package_key="x", trade="x", attachments=[
        PlanAttachment(source_doc="Clar.pdf", mode="whole", reason="clarification")])
    atts = assemble_firm_attachments(plan, ws, "GE/2026/14", "x")
    assert [a["filename"] for a in atts] == ["Clar.pdf"]
    assert base64.b64decode(atts[0]["content_b64"]) == data
