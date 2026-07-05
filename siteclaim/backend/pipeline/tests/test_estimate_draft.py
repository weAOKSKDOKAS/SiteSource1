"""Estimate scope + skeleton draft (Phase P3b) — fallback, fixture, dedupe, no invented qty."""

import sys

from pipeline.estimate.draft import ESTIMATE_DRAFT_FIXTURE, draft_estimate


def test_fallback_uses_the_scope_summary_and_invents_nothing(monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "true")  # no fixture + DEMO -> deterministic fallback only
    out = draft_estimate("ground_investigation", "GI drilling and testing", ["G1", "G2"])
    assert out["scope_of_works"] == "GI drilling and testing"
    assert out["additional_items"] == []          # nothing invented without the model
    assert out["trade"] == "ground_investigation" and out["trade_mapped"] is True


def test_fallback_synthesises_a_scope_when_summary_is_blank(monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "true")
    out = draft_estimate("electrical", "", [])
    assert "electrical" in out["scope_of_works"].lower() and out["additional_items"] == []


def test_off_taxonomy_trade_is_surfaced_not_dropped(monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "true")
    out = draft_estimate("underwater basket weaving", "misc", [])
    assert out["trade"] == "underwater basket weaving" and out["trade_mapped"] is False


def test_draft_uses_model_and_dedupes_existing_refs(monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "false")  # consult the injected fake client

    class FakeClient:
        def complete_json(self, *, user, target_model, **_):
            return target_model(
                scope_of_works="Self-perform the GI works; allow for standing time.",
                items=[
                    {"item_ref": "G-MOB", "description": "Mobilisation", "unit": "sum"},
                    {"item_ref": "G1", "description": "duplicate of an existing ref", "unit": "m"},
                ],
            )

    out = draft_estimate("ground_investigation", "GI", ["G1"], client=FakeClient())
    refs = [i["item_ref"] for i in out["additional_items"]]
    assert refs == ["G-MOB"]                       # G1 already present -> deduped out
    assert out["scope_of_works"].startswith("Self-perform the GI")
    assert all("qty" not in i and "rate" not in i for i in out["additional_items"])  # never invents a qty/rate


def test_demo_fixture_short_circuits_offline(monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "true")
    for mod in ("anthropic", "openai", "torch", "sentence_transformers", "fitz", "httpx", "requests"):
        monkeypatch.setitem(sys.modules, mod, None)
    out = draft_estimate("ground_investigation", "GI", ["G1"], demo_fixture=ESTIMATE_DRAFT_FIXTURE)
    refs = [i["item_ref"] for i in out["additional_items"]]
    assert "G-MOB" in refs and "G-STANDBY" in refs and out["scope_of_works"]
