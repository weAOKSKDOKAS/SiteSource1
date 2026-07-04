"""Phase A live-engine API surface, exercised in DEMO_MODE (offline).

The routes exist and behave, but DEMO_MODE keeps every one of them off the network:
``/level-upload`` returns the baked levelling, ``/dispatch`` records to the mock
outbox, and ``/contacts`` reads the seeded address book.
"""

from fastapi.testclient import TestClient

from api import app

client = TestClient(app)


def test_live_routes_are_registered():
    paths = {route.path for route in app.routes}
    assert {"/level-upload", "/contacts"} <= paths


def test_contacts_endpoint_lists_the_address_book():
    contacts = client.get("/contacts").json()
    assert isinstance(contacts, list) and contacts
    assert all({"firm_id", "trade", "email"} <= set(c) for c in contacts)


def test_level_upload_in_demo_returns_the_baked_levelling():
    files = {"files": ("reply.pdf", b"%PDF-1.4 fake", "application/pdf")}
    data = {"firm_id": "F-EL-03", "trade": "electrical"}
    resp = client.post("/level-upload", files=files, data=data)
    assert resp.status_code == 200
    levelled = resp.json()
    assert levelled and all("corrected_total" in bid for bid in levelled)


def test_ingest_upload_in_demo_returns_scope_and_untagged_tender():
    files = {"files": ("tender.pdf", b"%PDF-1.4 fake", "application/pdf")}
    resp = client.post("/ingest-upload", files=files, data={"project_name": "Live Tender A"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["scope"]["packages"]     # the scope split
    assert body["tender"]["documents"]   # the tagged tender (for /dispatch routing)
    # DEMO_MODE leaves the tender untagged — classification runs only on the live path,
    # so the demo scenarios and the hero catch are untouched.
    assert all(doc["trades"] == [] for doc in body["tender"]["documents"])


def test_dispatch_send_in_demo_is_mock_and_carries_attachments():
    case = client.get("/demo/messy").json()
    scope = client.post("/ingest", json={"tender": case["tender"]}).json()
    shortlist = client.post("/shortlist", json={"scope": scope}).json()
    dispatch = client.post("/dispatch", json={
        "shortlist": shortlist, "approvals": {"electrical": ["F-EL-02"]},
        "scope": scope, "tender": case["tender"], "project_name": case["name"], "send": True,
    }).json()
    bundle = dispatch["bundles"][0]
    assert bundle["status"] == "sent_mock"  # DEMO_MODE never really sends
    kinds = {a["kind"] for a in bundle["attachments"]}
    assert "sor_sheet" in kinds and "general" in kinds  # routed, even if not written to disk


def test_refresh_write_routes_are_disabled_in_demo():
    # The refresh write path must never mutate the committed demo DB during a demo run.
    stage = client.post("/refresh/stage", json={"records": [
        {"firm_id": "some-firm", "public_flags": [{"signal_type": "winding_up", "label": "x"}]}
    ]})
    confirm = client.post("/refresh/confirm", json={})
    assert stage.status_code == 409 and confirm.status_code == 409
    # the read-only pending view is available and tolerant (empty on the demo DB)
    pending = client.get("/refresh/pending")
    assert pending.status_code == 200 and isinstance(pending.json(), list)


def test_refresh_routes_are_registered():
    paths = {route.path for route in app.routes}
    assert {"/refresh/stage", "/refresh/pending", "/refresh/confirm", "/refresh/reject"} <= paths


def test_refresh_write_refuses_a_non_live_target(tmp_path, monkeypatch):
    # Even with DEMO_MODE off, a refresh must never mutate a demo-profile DB.
    from db import seed

    demo_db = tmp_path / "demo.db"
    seed.build_database(demo_db)  # profile 'demo'
    monkeypatch.setenv("DEMO_MODE", "false")
    monkeypatch.setenv("SITESOURCE_DB", str(demo_db))
    resp = client.post("/refresh/stage", json={"records": []})
    assert resp.status_code == 409


def test_refresh_write_applies_to_a_live_target(tmp_path, monkeypatch):
    from db import seed

    live_db = tmp_path / "live.db"
    seed.build_database(live_db, profile="live")
    monkeypatch.setenv("DEMO_MODE", "false")
    monkeypatch.setenv("SITESOURCE_DB", str(live_db))
    resp = client.post("/refresh/stage", json={"records": [
        {"firm_id": "new-live-firm-1", "name_en": "New Live Firm Ltd", "trades": ["electrical"],
         "public_flags": [{"signal_type": "winding_up", "label": "Winding-up 2026"}]}
    ]})
    assert resp.status_code == 200 and resp.json()["staged_firms"] == 1


def test_inbound_reply_route_is_registered():
    assert "/inbound-reply" in {route.path for route in app.routes}


def test_inbound_reply_ref_path_accumulates_and_relevels(monkeypatch, tmp_path):
    from pipeline import reply_loop
    from pipeline.workspace import Workspace

    monkeypatch.setenv("SITESOURCE_WORKDIR", str(tmp_path))
    ws = Workspace()  # picks up the env
    ref2 = reply_loop.make_ref("Kwun Tong", "F-EL-02", "electrical")
    reply_loop.record_dispatch(ws, ref2, "Kwun Tong", "F-EL-02", "electrical")

    first = client.post("/inbound-reply", files={"files": ("reply.pdf", b"%PDF-1.4", "application/pdf")}, data={"ref": ref2})
    assert first.status_code == 200
    body = first.json()
    assert body["status"] == "matched" and body["reply_count"] == 1
    assert [b["firm_id"] for b in body["comparison"]] == ["F-EL-02"]

    # a second firm's reply on the same tender grows the comparison (accumulate + relevel)
    ref3 = reply_loop.make_ref("Kwun Tong", "F-EL-03", "electrical")
    reply_loop.record_dispatch(ws, ref3, "Kwun Tong", "F-EL-03", "electrical")
    second = client.post("/inbound-reply", files={"files": ("reply.pdf", b"%PDF-1.4", "application/pdf")}, data={"ref": ref3})
    body2 = second.json()
    assert body2["reply_count"] == 2
    assert {b["firm_id"] for b in body2["comparison"]} == {"F-EL-02", "F-EL-03"}


def test_inbound_reply_without_a_ref_is_unmatched(monkeypatch, tmp_path):
    monkeypatch.setenv("SITESOURCE_WORKDIR", str(tmp_path))  # empty registry -> nothing to match
    resp = client.post("/inbound-reply", files={"files": ("reply.pdf", b"%PDF-1.4", "application/pdf")}, data={"ref": ""})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "unmatched" and "manual assignment" in body["detail"]
    assert body["comparison"] == []


def test_shortlist_include_public_opens_the_pool():
    # Phase B, reached through the API: the live-engine flag adds real public firms.
    case = client.get("/demo/messy").json()
    scope = client.post("/ingest", json={"tender": case["tender"]}).json()
    default = client.post("/shortlist", json={"scope": scope}).json()
    public = client.post("/shortlist", json={"scope": scope, "include_public": True}).json()
    assert len(public["per_trade"]["electrical"]) > len(default["per_trade"]["electrical"])


# -- deterministic xlsx reply parsing through the routes ------------------------------
#
# The realistic reply is our own dispatched SoR sheet returned with the Rate column
# filled — parsing it needs no model at all. These tests flip DEMO off (the parse
# branch only runs live) and stub the LLM parse with an assertion bomb, proving the
# xlsx path never consults the model: openpyxl is local, so everything stays offline.

_XLSX_CT = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _model_must_not_be_called(*args, **kwargs):
    raise AssertionError("the model must not be called on the xlsx reply path")


def _filled_sheet_bytes(tmp_path) -> bytes:
    """The dispatched SoR sheet for two electrical items, rates filled in by the firm."""
    from io import BytesIO

    from openpyxl import load_workbook

    from pipeline.stage_03_dispatch.attachments import generate_sor_sheet
    from schemas.models import SorItem, TradeWorkPackage

    pkg = TradeWorkPackage(
        trade="electrical", scope_summary="LV works",
        sor_items=[
            SorItem(item_ref="E-01", description="LV main switchboard", unit="no", qty=1.0),
            SorItem(item_ref="E-02", description="Sub-main cabling", unit="m", qty=100.0),
        ],
        source_refs=["Schedule of Rates"],
    )
    path = generate_sor_sheet(pkg, "Kwun Tong", tmp_path / "sor.xlsx")
    wb = load_workbook(path)
    ws = wb.active
    header = next(r for r in range(1, ws.max_row + 1) if ws.cell(row=r, column=1).value == "Item")
    rates = {"E-01": 950000, "E-02": 2500}
    for r in range(header + 1, ws.max_row + 1):
        ref = ws.cell(row=r, column=1).value
        if ref in rates:
            ws.cell(row=r, column=5, value=rates[ref])  # "Rate (HKD)"
    buffer = BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def test_level_upload_parses_an_xlsx_reply_with_no_model_call(monkeypatch, tmp_path):
    monkeypatch.setenv("DEMO_MODE", "false")
    monkeypatch.setattr("api.parse_bid_reply", _model_must_not_be_called)

    resp = client.post(
        "/level-upload",
        files={"files": ("SoR_electrical.xlsx", _filled_sheet_bytes(tmp_path), _XLSX_CT)},
        data={"firm_id": "F-EL-02", "trade": "electrical"},
    )

    assert resp.status_code == 200
    (bid,) = resp.json()
    assert bid["firm_id"] == "F-EL-02" and bid["trade"] == "electrical"
    assert bid["corrected_total"] == 1200000.0  # 1 x 950,000 + 100 x 2,500 — Layer 1 arithmetic
    assert {ir["item_ref"]: ir["rate"] for ir in bid["item_rates"]} == {"E-01": 950000.0, "E-02": 2500.0}


def test_inbound_reply_xlsx_resolves_by_ref_and_parses_deterministically(monkeypatch, tmp_path):
    from pipeline import reply_loop
    from pipeline.workspace import Workspace

    monkeypatch.setenv("DEMO_MODE", "false")
    monkeypatch.setenv("SITESOURCE_WORKDIR", str(tmp_path))
    monkeypatch.setattr("api.parse_bid_reply", _model_must_not_be_called)
    ws = Workspace()
    ref = reply_loop.make_ref("Kwun Tong", "F-EL-02", "electrical")
    reply_loop.record_dispatch(ws, ref, "Kwun Tong", "F-EL-02", "electrical")

    resp = client.post(
        "/inbound-reply",
        files={"files": ("SoR_electrical.xlsx", _filled_sheet_bytes(tmp_path), _XLSX_CT)},
        data={"ref": ref},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "matched" and body["firm_id"] == "F-EL-02"  # ref stays authoritative
    assert body["reply_count"] == 1
    assert body["comparison"][0]["corrected_total"] == 1200000.0


def test_level_upload_rejects_a_non_sor_xlsx_with_a_clear_400(monkeypatch):
    from io import BytesIO

    from openpyxl import Workbook

    monkeypatch.setenv("DEMO_MODE", "false")
    monkeypatch.setattr("api.parse_bid_reply", _model_must_not_be_called)
    wb = Workbook()
    wb.active.append(["Colour", "Size", "Price"])  # wrong headers — not our SoR layout
    buffer = BytesIO()
    wb.save(buffer)

    resp = client.post(
        "/level-upload",
        files={"files": ("prices.xlsx", buffer.getvalue(), _XLSX_CT)},
        data={"firm_id": "F-EL-02", "trade": "electrical"},
    )

    assert resp.status_code == 400
    assert "Not a Schedule of Rates sheet" in resp.json()["detail"]
