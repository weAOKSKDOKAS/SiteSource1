"""Inbound-reply routing by item identity (leveling fix, Commit 4) — the 70-item bug and its
regressions, driven through the real /inbound-reply endpoint. Deterministic: the parse is stubbed
(no model/tesseract) and the scope is persisted directly, so routing is exercised offline."""

import api
from fastapi.testclient import TestClient
from pipeline import reply_loop
from pipeline.scope_store import save_scope
from pipeline.workspace import Workspace
from schemas.models import BidLineItem, BidReply, ScopePackages, SectionMeta, SorItem, TradeWorkPackage

client = TestClient(api.app)


def _gi_scope(project: str) -> ScopePackages:
    # One GI trade spanning FOUR sections (> 3) so route_units splits it into per-section units,
    # each its own dispatched enquiry — the multi-section shape behind the 70-item bug.
    return ScopePackages(project_name=project, packages=[TradeWorkPackage(
        trade="ground_investigation", scope_summary="GI", sor_items=[
            SorItem(item_ref="G4", description="Trial pit in soil", section="G"),
            SorItem(item_ref="G7", description="Trial pit backfill", section="G"),
            SorItem(item_ref="H12", description="Field vane shear test", section="H"),
            SorItem(item_ref="I3", description="Borehole log record", section="I"),
            SorItem(item_ref="J1", description="Install standpipe piezometer", section="J"),
        ],
        sections=[SectionMeta(code=c, item_count=n) for c, n in [("G", 2), ("H", 1), ("I", 1), ("J", 1)]])])


def _stub_parse(monkeypatch, reply: BidReply) -> None:
    monkeypatch.setattr(api, "_parse_reply", lambda *a, **k: reply)


def test_reply_spanning_g_h_j_becomes_three_per_section_bids(monkeypatch, tmp_path):
    monkeypatch.setenv("SITESOURCE_WORKDIR", str(tmp_path))
    ws = Workspace()
    save_scope(ws, "GI-70", _gi_scope("GI-70"))
    # The enquiry was Section J; the returned document actually prices G + H + J, plus one line
    # that belongs to no SoR item at all.
    ref = reply_loop.make_ref("GI-70", "F-GI-1", "ground_investigation:J")
    reply_loop.record_dispatch(ws, ref, "GI-70", "F-GI-1", "ground_investigation:J")
    _stub_parse(monkeypatch, BidReply(firm_id="F-GI-1", trade="ground_investigation:J", line_items=[
        BidLineItem(item_ref="G4", rate=100.0), BidLineItem(item_ref="H12", rate=200.0),
        BidLineItem(item_ref="J1", rate=300.0),
        BidLineItem(item_ref="X9", description="Site office welfare", rate=9.0),
    ]))

    body = client.post("/inbound-reply", files={"files": ("r.pdf", b"%PDF-1.4", "application/pdf")},
                       data={"ref": ref}).json()
    assert body["status"] == "matched" and body["reply_count"] == 3
    by_trade = {b["trade"]: b for b in body["comparison"]}
    assert set(by_trade) == {"ground_investigation:G", "ground_investigation:H", "ground_investigation:J"}
    # The J comparison reflects ONLY J items — not a 70-item G+H+J mix.
    assert [r["item_ref"] for r in by_trade["ground_investigation:J"]["item_rates"]] == ["J1"]
    assert [r["item_ref"] for r in by_trade["ground_investigation:H"]["item_rates"]] == ["H12"]
    # The out-of-scope line is flagged, never dropped, never in any section's rates.
    assert any("X9" in e for e in body["extras"])
    assert all("X9" not in r["item_ref"] for b in body["comparison"] for r in b["item_rates"])


def test_extras_never_enter_a_section_total(monkeypatch, tmp_path):
    monkeypatch.setenv("SITESOURCE_WORKDIR", str(tmp_path))
    ws = Workspace()
    save_scope(ws, "GI-71", _gi_scope("GI-71"))
    ref = reply_loop.make_ref("GI-71", "F-GI-2", "ground_investigation:J")
    reply_loop.record_dispatch(ws, ref, "GI-71", "F-GI-2", "ground_investigation:J")
    # Only J1 is a real SoR item; the other two are priced but outside the tender. Give every line
    # a quantity so an amount is computable — the extras' 6000 must NOT reach the section total.
    _stub_parse(monkeypatch, BidReply(firm_id="F-GI-2", trade="ground_investigation:J", line_items=[
        BidLineItem(item_ref="J1", qty=2.0, rate=300.0, amount=600.0),
        BidLineItem(item_ref="Z1", description="Temporary access road", qty=1.0, rate=5000.0, amount=5000.0),
        BidLineItem(item_ref="Z2", description="Insurance surcharge", qty=1.0, rate=1000.0, amount=1000.0),
    ]))

    body = client.post("/inbound-reply", files={"files": ("r.pdf", b"%PDF-1.4", "application/pdf")},
                       data={"ref": ref}).json()
    j = [b for b in body["comparison"] if b["trade"] == "ground_investigation:J"][0]
    assert j["corrected_total"] == 600.0  # only J1 (2 × 300) — the 6000 of extras is not added in
    assert len(body["extras"]) == 2
    cover = {s["package_key"]: s for s in body["sections"]}
    assert cover["ground_investigation:J"]["priced_items"] == 1
    assert cover["ground_investigation:J"]["section_total"] == 1  # J has one canonical item


def test_single_section_reply_levels_as_before(monkeypatch, tmp_path):
    # Regression: a reply whose lines all belong to the enquiry's section -> one bid on that
    # section key, exactly the pre-fix outcome for a split-package enquiry.
    monkeypatch.setenv("SITESOURCE_WORKDIR", str(tmp_path))
    ws = Workspace()
    save_scope(ws, "GI-72", _gi_scope("GI-72"))
    ref = reply_loop.make_ref("GI-72", "F-GI-3", "ground_investigation:G")
    reply_loop.record_dispatch(ws, ref, "GI-72", "F-GI-3", "ground_investigation:G")
    _stub_parse(monkeypatch, BidReply(firm_id="F-GI-3", trade="ground_investigation:G", line_items=[
        BidLineItem(item_ref="G4", rate=100.0), BidLineItem(item_ref="G7", rate=150.0),
    ]))

    body = client.post("/inbound-reply", files={"files": ("r.pdf", b"%PDF-1.4", "application/pdf")},
                       data={"ref": ref}).json()
    assert body["reply_count"] == 1
    assert [b["trade"] for b in body["comparison"]] == ["ground_investigation:G"]
    assert body["extras"] == []
    cover = body["sections"][0]
    assert cover["priced_items"] == 2 and cover["section_total"] == 2  # both G items priced


def test_reply_without_persisted_scope_falls_back_to_ref_trade(monkeypatch, tmp_path):
    # Regression: no canonical scope (an older tender / the DEMO path) -> today's behaviour, one bid
    # stamped the ref trade, nothing routed, no extras.
    monkeypatch.setenv("SITESOURCE_WORKDIR", str(tmp_path))
    ws = Workspace()  # NOTE: no save_scope
    ref = reply_loop.make_ref("Kwun Tong", "F-EL-9", "electrical")
    reply_loop.record_dispatch(ws, ref, "Kwun Tong", "F-EL-9", "electrical")
    _stub_parse(monkeypatch, BidReply(firm_id="F-EL-9", trade="electrical", line_items=[
        BidLineItem(item_ref="E1", rate=100.0), BidLineItem(item_ref="E2", rate=200.0),
    ]))

    body = client.post("/inbound-reply", files={"files": ("r.pdf", b"%PDF-1.4", "application/pdf")},
                       data={"ref": ref}).json()
    assert body["reply_count"] == 1
    assert [b["trade"] for b in body["comparison"]] == ["electrical"]  # stamped the ref trade
    assert body["extras"] == [] and body["sections"] == []
