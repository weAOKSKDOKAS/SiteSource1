"""Relevant-only attachment assembly + the Gmail draft hand-off (direct API, no n8n)."""

import base64

import pytest

from pipeline.stage_01_ingest.doc_index import DocIndexEntry, save_doc_index
from pipeline.stage_03_dispatch.drafts import assemble_firm_attachments, create_gmail_drafts, plan_for_firms
from pipeline.stage_03_dispatch.relevant_docs import (
    PlanAttachment,
    SectionPlan,
    apply_attachment_overrides,
)
from pipeline.workspace import Workspace
from schemas.models import ScopePackages, SorItem, TradeWorkPackage

fitz = pytest.importorskip("fitz")

_TID = "GE/2026/14"
_PKG = "ground_investigation:E"


def _run(tmp_path):
    """A live run on disk: a whole clarification PDF, a generated SoR sheet, and a doc index."""
    ws = Workspace(tmp_path)
    clar = fitz.open()
    clar.new_page().insert_text((72, 72), "AECOM Clarification")
    clar_bytes = clar.tobytes()
    ws.save_upload(_TID, "Clar.pdf", clar_bytes)
    ws.sor_sheet_path(_TID, _PKG).write_bytes(b"PK-fake-sor-sheet")  # the generated SoR sheet
    save_doc_index(ws, _TID, [DocIndexEntry(filename="Clar.pdf", kind="clarification", text_layer=True, page_count=1)])
    scope = ScopePackages(packages=[TradeWorkPackage(
        trade=_PKG, scope_summary="Section E DRILLING",
        sor_items=[SorItem(item_ref="E1", description="Rotary drilling per PS 7.1", section="E")])])
    return ws, scope, clar_bytes


def test_plan_always_carries_the_sor_sheet_and_clarifications(tmp_path):
    ws, scope, _ = _run(tmp_path)
    plan = plan_for_firms(scope, {_PKG: ["F1"]}, tender_id=_TID, workspace=ws)[_PKG]
    modes = {a.source_doc: a.mode for a in plan.attachments}
    assert modes[ws.sor_sheet_path(_TID, _PKG).name] == "generated"  # the priced sheet, always
    assert modes["Clar.pdf"] == "whole"                              # clarification to every firm


def test_assembly_is_exactly_the_planned_files_as_base64(tmp_path):
    ws, scope, clar_bytes = _run(tmp_path)
    plan = plan_for_firms(scope, {_PKG: ["F1"]}, tender_id=_TID, workspace=ws)[_PKG]
    atts = assemble_firm_attachments(plan, ws, _TID, _PKG)
    by = {a["filename"]: a for a in atts}
    assert set(by) == {"Clar.pdf", ws.sor_sheet_path(_TID, _PKG).name}  # only the planned files
    assert base64.b64decode(by["Clar.pdf"]["content_b64"]) == clar_bytes  # exactly the bytes


def test_override_removes_a_doc_expands_a_slice_and_never_drops_the_sor_sheet():
    plan = SectionPlan(package_key=_PKG, section="E", attachments=[
        PlanAttachment(source_doc="SoR-E.xlsx", mode="generated"),
        PlanAttachment(source_doc="Clar.pdf", mode="whole", reason="clarification"),
        PlanAttachment(source_doc="PS.pdf", mode="sliced", pages=[12, 13], reason="PS 7.1"),
    ])
    out = apply_attachment_overrides(plan, removed=["Clar.pdf", "SoR-E.xlsx"], whole=["PS.pdf"])
    by = {a.source_doc: a for a in out.attachments}
    assert "Clar.pdf" not in by                       # the removed document is gone
    assert "SoR-E.xlsx" in by                          # the generated SoR sheet is never removable
    assert by["PS.pdf"].mode == "whole" and by["PS.pdf"].pages == []  # expanded slice -> whole file
    assert len(plan.attachments) == 3                  # the input plan is left untouched (new plan)


def test_override_drops_the_removed_file_from_the_assembled_bundle(tmp_path):
    ws, scope, _ = _run(tmp_path)
    plan = plan_for_firms(scope, {_PKG: ["F1"]}, tender_id=_TID, workspace=ws)[_PKG]
    edited = apply_attachment_overrides(plan, removed=["Clar.pdf"])
    atts = assemble_firm_attachments(edited, ws, _TID, _PKG)
    assert {a["filename"] for a in atts} == {ws.sor_sheet_path(_TID, _PKG).name}  # Clar.pdf base64 omitted


# -- the Gmail draft hand-off (direct API; a failure is data, never an exception) ------------
def _draft(firm_id="F1", to="f1@x.com", atts=None):
    return {"firm_id": firm_id, "to": to, "subject": "RFQ [SiteSource Ref: x]", "body": "…",
            "ref": "x", "attachments": atts or []}


def test_gmail_drafts_are_created_from_the_assembled_bundle(tmp_path):
    # The full path: plan -> assemble -> one Gmail draft per firm, carrying exactly the planned
    # files (decoded back from base64 for the MIME build). Stubbed service — no Google SDK.
    from pipeline.tests.test_gmail_client import StubService

    ws, scope, clar_bytes = _run(tmp_path)
    plan = plan_for_firms(scope, {_PKG: ["F1"]}, tender_id=_TID, workspace=ws)[_PKG]
    atts = assemble_firm_attachments(plan, ws, _TID, _PKG)
    svc = StubService(draft_result={"id": "d-1"})

    drafted, failed = create_gmail_drafts([_draft(atts=atts)], service=svc)
    assert drafted == ["F1"] and failed == []
    (name, payload), = svc.calls
    assert name == "drafts.create"
    import email as _email
    msg = _email.message_from_bytes(base64.urlsafe_b64decode(payload["body"]["message"]["raw"]))
    by_name = {p.get_filename(): p.get_payload(decode=True) for p in msg.walk() if p.get_filename()}
    assert by_name["Clar.pdf"] == clar_bytes                          # exactly the planned bytes
    assert set(by_name) == {"Clar.pdf", ws.sor_sheet_path(_TID, _PKG).name}


def test_a_firm_with_no_contact_email_is_reported_never_silently_skipped():
    from pipeline.tests.test_gmail_client import StubService

    svc = StubService()
    drafted, failed = create_gmail_drafts([_draft(firm_id="F-NO-MAIL", to="")], service=svc)
    assert drafted == [] and svc.calls == []                          # nothing drafted with an empty To
    assert failed == [{"firm_id": "F-NO-MAIL",
                       "reason": "no contact email on file — add one in the address book (GET /contacts)"}]


def test_gmail_unavailable_returns_every_firm_failed_with_the_actionable_reason(monkeypatch, tmp_path):
    # No injected service and no credentials/token -> ALL enquiries come back failed with the
    # typed, actionable reason. NOTHING raises — the dispatch endpoint stays 200.
    monkeypatch.setenv("GMAIL_TOKEN_PATH", str(tmp_path / "absent.json"))
    drafted, failed = create_gmail_drafts([_draft("F1"), _draft("F2", to="f2@x.com")])
    assert drafted == []
    assert [f["firm_id"] for f in failed] == ["F1", "F2"]
    assert all(f["reason"] for f in failed)                           # a reason on every failure


def test_a_per_firm_api_error_fails_that_firm_and_drafts_the_rest():
    from pipeline.tests.test_gmail_client import StubService, _Call

    class FlakyService(StubService):
        def __init__(self):
            super().__init__()
            self.n = 0

        def create(self, userId, body):
            self.n += 1
            if self.n == 1:  # the first draft blows up, the second succeeds
                return _Call(RuntimeError("500 backendError"))
            return super().create(userId, body)

    drafted, failed = create_gmail_drafts([_draft("F1"), _draft("F2", to="f2@x.com")], service=FlakyService())
    assert drafted == ["F2"]                                          # partial success, order kept
    assert [f["firm_id"] for f in failed] == ["F1"] and "failed" in failed[0]["reason"]
