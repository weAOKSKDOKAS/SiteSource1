"""Misdirected-return guard (return round-trip v2, Commit 3): a return uploaded/sent FOR one enquiry
whose lines actually price ANOTHER unit strongly yields a hint naming that unit — never auto-moved.
Deterministic, offline (pure Layer-1 routing over the canonical scope)."""

from api import _misdirect_hint
from schemas.models import BidLineItem, ScopePackages, SectionMeta, SorItem, TradeWorkPackage


def _split_gi_scope() -> ScopePackages:
    # 4 sections -> route_units splits ground_investigation into per-section units (G/H/I/J).
    return ScopePackages(project_name="GE/2026/14", packages=[TradeWorkPackage(
        trade="ground_investigation", scope_summary="GI",
        sor_items=[SorItem(item_ref=r, section=r[0]) for r in ["G4", "H12", "H13", "H14", "I3", "J1"]],
        sections=[SectionMeta(code=c, item_count=n) for c, n in [("G", 1), ("H", 3), ("I", 1), ("J", 1)]])])


def _lines(refs):
    return [BidLineItem(item_ref=r, rate=10.0) for r in refs]


def test_an_h_return_uploaded_to_the_g_enquiry_is_flagged_misdirected():
    hint = _misdirect_hint(_lines(["H12", "H13", "H14"]), _split_gi_scope(), "ground_investigation:G")
    assert hint is not None
    assert hint.target_unit == "ground_investigation:G"     # where it was uploaded
    assert hint.matched_unit == "ground_investigation:H"    # where its lines actually belong
    assert hint.matched_items == 3 and hint.unit_total == 3  # 3 of 3 H items priced


def test_a_correct_return_yields_no_hint():
    # priced the target unit's item -> not misdirected (even if it also touches another unit)
    assert _misdirect_hint(_lines(["G4", "H12"]), _split_gi_scope(), "ground_investigation:G") is None


def test_no_hint_without_a_persisted_scope():
    assert _misdirect_hint(_lines(["H12"]), None, "ground_investigation:G") is None


def test_no_hint_when_the_return_is_mostly_out_of_scope_extras():
    # nothing matches a dominant other unit (all lines are extras) -> not implicated
    assert _misdirect_hint(_lines(["ZZ9", "QQ1"]), _split_gi_scope(), "ground_investigation:G") is None


def test_no_hint_when_no_single_unit_dominates():
    # target got nothing, but the matches are split evenly across two other units -> too weak to flag
    hint = _misdirect_hint(_lines(["H12", "I3"]), _split_gi_scope(), "ground_investigation:G")
    assert hint is None  # H=1, I=1 -> neither holds a majority


def test_level_upload_envelope_shape_in_demo():
    from fastapi.testclient import TestClient
    import api

    client = TestClient(api.app)
    resp = client.post("/level-upload",
                       files={"files": ("reply.pdf", b"%PDF-1.4 fake", "application/pdf")},
                       data={"firm_id": "F-EL-03", "trade": "electrical"})
    assert resp.status_code == 200
    body = resp.json()
    assert "levelled" in body and body["misdirected"] is None  # demo: no scope -> no hint, enveloped
