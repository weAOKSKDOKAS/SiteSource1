"""Relevant-only attachment assembly + n8n hand-off (relevant-doc assembler, RD5)."""

import base64

import pytest

from pipeline.stage_01_ingest.doc_index import DocIndexEntry, save_doc_index
from pipeline.stage_03_dispatch.drafts import assemble_firm_attachments, plan_for_firms, post_drafts
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


def test_n8n_post_fires_only_when_the_webhook_is_set(tmp_path, monkeypatch):
    ws, scope, _ = _run(tmp_path)
    plan = plan_for_firms(scope, {_PKG: ["F1"]}, tender_id=_TID, workspace=ws)[_PKG]
    atts = assemble_firm_attachments(plan, ws, _TID, _PKG)
    drafts = [{"firm_id": "F1", "to": "f1@x.com", "subject": "RFQ [SiteSource Ref: x]", "body": "…",
               "ref": "x", "attachments": atts}]

    captured: dict = {}
    monkeypatch.setattr("pipeline.stage_03_dispatch.drafts._http_post",
                        lambda url, payload: captured.update(url=url, payload=payload))

    monkeypatch.delenv("N8N_DRAFTS_WEBHOOK", raising=False)
    assert post_drafts(_TID, drafts) is False and captured == {}  # no webhook -> no network

    monkeypatch.setenv("N8N_DRAFTS_WEBHOOK", "https://n8n.example/webhook/abc")
    assert post_drafts(_TID, drafts) is True
    assert captured["url"].endswith("/webhook/abc")
    sent = captured["payload"]
    assert sent["tender"] == _TID
    sent_atts = sent["drafts"][0]["attachments"]
    assert {a["filename"] for a in sent_atts} == {"Clar.pdf", ws.sor_sheet_path(_TID, _PKG).name}
    assert all("content_b64" in a for a in sent_atts)  # base64 of exactly the planned files
