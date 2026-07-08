"""Supersede / migration / withdraw for the reply registry (replies-meet-enquiries, Commit 2).
Deterministic, offline — pure registry + item-identity routing."""

import api
from fastapi.testclient import TestClient
from pipeline import reply_loop
from pipeline.reply_loop import _replies_path, _write_json
from pipeline.scope_store import save_scope
from pipeline.workspace import Workspace
from schemas.models import BidLineItem, BidReply, ScopePackages, SectionMeta, SorItem, TradeWorkPackage

client = TestClient(api.app)


def _reply(firm, key, refs_rates):
    return BidReply(firm_id=firm, trade=key, line_items=[BidLineItem(item_ref=r, rate=v) for r, v in refs_rates])


def _split_gi_scope() -> ScopePackages:
    return ScopePackages(project_name="GI", packages=[TradeWorkPackage(
        trade="ground_investigation", scope_summary="GI",
        sor_items=[SorItem(item_ref=r, section=r[0]) for r in ["G4", "H12", "I3", "J1"]],
        sections=[SectionMeta(code=c, item_count=1) for c in ("G", "H", "I", "J")])])


def test_supersede_keeps_latest_with_history(tmp_path):
    ws = Workspace(tmp_path)
    reply_loop.accumulate_replies(ws, "T", [_reply("F1", "field_installations", [("H1", 10.0)])],
                                  received_at="2026-01-01T00:00:00Z")
    active = reply_loop.accumulate_replies(ws, "T", [_reply("F1", "field_installations", [("H1", 99.0)])],
                                           received_at="2026-01-02T00:00:00Z")
    assert len(active) == 1 and active[0].line_items[0].rate == 99.0  # latest wins in the comparison
    records = reply_loop.tender_reply_records(ws, "T")
    assert [r["status"] for r in records] == ["superseded", "active"]  # the prior is kept as history
    assert records[1]["received_at"] == "2026-01-02T00:00:00Z"


def test_supersede_is_per_unit_not_whole_firm(tmp_path):
    ws = Workspace(tmp_path)
    # firm holds two units; a new reply for one unit does not touch the other
    reply_loop.accumulate_replies(ws, "T", [_reply("F1", "gi:G", [("G1", 1.0)]), _reply("F1", "gi:H", [("H1", 2.0)])])
    active = reply_loop.accumulate_replies(ws, "T", [_reply("F1", "gi:H", [("H1", 5.0)])])
    by_key = {r.trade: r.line_items[0].rate for r in active}
    assert by_key == {"gi:G": 1.0, "gi:H": 5.0}  # G untouched, H superseded to the latest


def test_migration_rekeys_a_stale_misrouted_entry(tmp_path):
    ws = Workspace(tmp_path)
    save_scope(ws, "GI", _split_gi_scope())
    # a pre-fix reply: all G/H/J lines stamped under the single J enquiry key
    reply_loop.accumulate_replies(ws, "GI", [_reply("F1", "ground_investigation:J",
                                                    [("G4", 1.0), ("H12", 2.0), ("J1", 3.0)])])
    from pipeline.scope_store import load_scope
    reply_loop.migrate_stale_replies(ws, "GI", load_scope(ws, "GI"))
    by_key = {r.trade: [li.item_ref for li in r.line_items] for r in reply_loop.tender_replies(ws, "GI")}
    assert set(by_key) == {"ground_investigation:G", "ground_investigation:H", "ground_investigation:J"}
    assert by_key["ground_investigation:G"] == ["G4"] and by_key["ground_investigation:J"] == ["J1"]
    assert any(r["status"] == "migrated" for r in reply_loop.tender_reply_records(ws, "GI"))  # kept as history


def test_migration_is_idempotent_on_correctly_keyed_replies(tmp_path):
    ws = Workspace(tmp_path)
    save_scope(ws, "GI", _split_gi_scope())
    reply_loop.accumulate_replies(ws, "GI", [_reply("F1", "ground_investigation:H", [("H12", 2.0)])])
    from pipeline.scope_store import load_scope
    before = reply_loop.tender_reply_records(ws, "GI")
    reply_loop.migrate_stale_replies(ws, "GI", load_scope(ws, "GI"))
    assert reply_loop.tender_reply_records(ws, "GI") == before  # untouched — already on its own key


def test_withdraw_marks_active_reply_withdrawn_and_re_levels(tmp_path):
    ws = Workspace(tmp_path)
    reply_loop.accumulate_replies(ws, "T", [_reply("F1", "field_installations", [("H1", 10.0)])])
    assert reply_loop.withdraw_reply(ws, "T", "F1", "field_installations") is True
    assert reply_loop.tender_replies(ws, "T") == []  # withdrawn -> out of the active comparison
    assert reply_loop.withdraw_reply(ws, "T", "F1", "field_installations") is False  # nothing active left


def test_legacy_flat_reply_file_reads_as_active(tmp_path):
    ws = Workspace(tmp_path)
    # an older registry: a flat list of bare BidReply dumps (no record wrapper)
    _write_json(_replies_path(ws, "T"), [_reply("F1", "electrical", [("E1", 1.0)]).model_dump()])
    assert [r.firm_id for r in reply_loop.tender_replies(ws, "T")] == ["F1"]  # wrapped as active, still read


def test_withdraw_endpoint_removes_from_comparison(tmp_path, monkeypatch):
    monkeypatch.setenv("SITESOURCE_WORKDIR", str(tmp_path))
    ws = Workspace()
    reply_loop.accumulate_replies(ws, "ge-x", [_reply("F1", "field_installations", [("H1", 10.0)])])
    resp = client.post("/tender/ge-x/replies/withdraw",
                       json={"firm_id": "F1", "package_key": "field_installations"})
    assert resp.status_code == 200 and resp.json()["reply_count"] == 0
    # a second withdraw of the same (nothing active) is a 404
    assert client.post("/tender/ge-x/replies/withdraw",
                       json={"firm_id": "F1", "package_key": "field_installations"}).status_code == 404
