"""EOS reason extractor (Phase P2b) — fallback, fixture, snippet search, offline discipline."""

import sys

from pipeline.benchmark.eos_reason import (
    EOS_REASON_FIXTURE,
    extract_reason_candidates,
    fallback_candidate,
)

# A fictional GI EOS narrative (mirrors the demo scenario). Six sentences: G1/G2 standing
# time, ground OK, G3 remeasure, G5 unpriced obstruction, weather minimal.
_NARRATIVE = (
    "The rotary drilling rig stood idle for extended periods while utility diversions were "
    "completed, which pushed the achieved rate for the soil drilling item above the tendered rate. "
    "The rig also stood waiting for the Engineer's instruction to core into rock, raising the rock "
    "drilling rate over the tendered rate. Ground conditions were otherwise broadly as anticipated. "
    "Five additional standard penetration tests were instructed and remeasured on site beyond the "
    "tendered quantity. During excavation an unforeseen obstruction was encountered that required "
    "removal; this work was not priced in the tender and was carried out as an additional item. "
    "Weather standing over the contract period was minimal."
)

# Variance records mirroring the demo math shapes.
_RECORDS = [
    {"id": 1, "item_ref": "G1", "granularity": "item", "tender_item_id": 1, "actual_item_id": 1,
     "rate_delta": 300.0, "amount_delta_qty": 0.0, "amount_delta_rate": 60000.0},
    {"id": 2, "item_ref": "G2", "granularity": "item", "tender_item_id": 2, "actual_item_id": 2,
     "rate_delta": 300.0, "amount_delta_qty": 0.0, "amount_delta_rate": 24000.0},
    {"id": 3, "item_ref": "G3", "granularity": "item", "tender_item_id": 3, "actual_item_id": 3,
     "rate_delta": 0.0, "amount_delta_qty": 2250.0, "amount_delta_rate": 0.0},
    {"id": 4, "item_ref": "G4", "granularity": "item", "tender_item_id": 4, "actual_item_id": 4,
     "rate_delta": 0.0, "amount_delta_qty": 0.0, "amount_delta_rate": 0.0},   # zero variance -> no candidate
    {"id": 5, "item_ref": "G5", "granularity": "item", "tender_item_id": None, "actual_item_id": 5},  # arrived-unpriced
]


def test_fallback_candidate_covers_the_shape_codes():
    # arrived-unpriced (actual only) -> scope_variation
    assert fallback_candidate(_NARRATIVE, _RECORDS[4])["reason_code"] == "scope_variation"
    # priced but no actual -> omission_at_tender
    omission = fallback_candidate("", {"item_ref": "X", "tender_item_id": 9, "actual_item_id": None})
    assert omission["reason_code"] == "omission_at_tender"
    # qty-driven -> quantity_remeasure, with a snippet found in the narrative
    g3 = fallback_candidate(_NARRATIVE, _RECORDS[2])
    assert g3["reason_code"] == "quantity_remeasure" and "remeasured" in g3["snippet"]
    # a zero-variance line implies no reason
    assert fallback_candidate(_NARRATIVE, _RECORDS[3]) is None


def test_extract_uses_model_candidates_and_falls_back_for_uncovered(monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "false")  # consult the injected fake client

    class FakeClient:
        def complete_json(self, *, user, target_model, **_):
            return target_model(candidates=[
                {"item_ref": "G1", "granularity": "item", "reason_code": "standing_time",
                 "snippet": "the rig stood idle"},
            ])

    out = {c["item_ref"]: c for c in extract_reason_candidates(_NARRATIVE, _RECORDS, client=FakeClient())}
    assert out["G1"]["reason_code"] == "standing_time" and out["G1"]["source"] == "reason-from-eos"
    # G3 not covered by the model -> deterministic fallback
    assert out["G3"]["reason_code"] == "quantity_remeasure" and out["G3"]["source"] == "fallback"
    assert "G4" not in out  # zero variance -> no candidate


def test_extract_ignores_an_invalid_model_code_and_falls_back(monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "false")

    class BadClient:
        def complete_json(self, *, user, target_model, **_):
            return target_model(candidates=[
                {"item_ref": "G1", "granularity": "item", "reason_code": "banana", "snippet": "x"},
            ])

    out = {c["item_ref"]: c for c in extract_reason_candidates(_NARRATIVE, _RECORDS, client=BadClient())}
    # invalid code dropped -> G1 uses the deterministic fallback (a valid code)
    assert out["G1"]["source"] == "fallback"
    from db.benchmark import REASON_CODE_SET
    assert out["G1"]["reason_code"] in REASON_CODE_SET


def test_demo_fixture_short_circuits_offline(monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "true")
    for mod in ("anthropic", "openai", "torch", "sentence_transformers", "fitz", "httpx", "requests"):
        monkeypatch.setitem(sys.modules, mod, None)
    out = {c["item_ref"]: c for c in
           extract_reason_candidates(_NARRATIVE, _RECORDS, demo_fixture=EOS_REASON_FIXTURE)}
    assert out["G1"]["reason_code"] == "standing_time" and out["G1"]["source"] == "reason-from-eos"
    assert out["G2"]["reason_code"] == "standing_time"
    assert out["G3"]["reason_code"] == "quantity_remeasure"
    assert out["G5"]["reason_code"] == "omission_at_tender"      # EOS beats the shape's scope_variation guess
    assert all(out[k]["snippet"] for k in ("G1", "G2", "G3", "G5"))  # every candidate carries evidence
    assert "G4" not in out
    assert out["G1"]["record_id"] == 1                          # mapped back to the variance record


def test_demo_without_fixture_uses_fallback_only(monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "true")
    # no fixture + DEMO -> the model is never called; the deterministic fallback drives it
    out = {c["item_ref"]: c for c in extract_reason_candidates(_NARRATIVE, _RECORDS)}
    assert all(c["source"] == "fallback" for c in out.values())
    assert out["G3"]["reason_code"] == "quantity_remeasure"
    assert out["G5"]["reason_code"] == "scope_variation"        # shape guess without the narrative's help
