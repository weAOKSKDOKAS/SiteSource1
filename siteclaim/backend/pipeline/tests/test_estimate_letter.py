"""Letter-of-offer draft (Phase P3e) — fallback, fixture, offline discipline."""

import sys

from pipeline.estimate.letter import LETTER_FIXTURE, draft_letter

_ESTIMATE = {"name": "GI Term Contract", "trade": "ground_investigation", "client": "Works Bureau",
             "scope_of_works": "Rotary drilling and testing.", "total": 120000.0}
_ITEMS = [{"item_ref": "G1", "rate": 1200.0}, {"item_ref": "G2", "rate": None}]


def test_fallback_builds_a_letter_with_the_computable_total(monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "true")   # no fixture -> deterministic fallback
    letter = draft_letter(_ESTIMATE, _ITEMS)
    assert letter["subject"].startswith("Letter of Offer")
    assert "HK$120,000.00" in letter["body"]           # the rolled-up computable total
    assert letter["inclusions"] and letter["exclusions"] and letter["assumptions"]


def test_fallback_without_a_total_states_the_schedule(monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "true")
    letter = draft_letter({**_ESTIMATE, "total": None}, _ITEMS)
    assert "attached priced schedule" in letter["body"]  # no fabricated figure


def test_draft_uses_the_model_when_available(monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "false")

    class FakeClient:
        def complete_json(self, *, user, target_model, **_):
            return target_model(subject="Offer", body="Our offer follows.",
                                inclusions=["Drilling"], exclusions=["Fees"], assumptions=["90 days"])

    letter = draft_letter(_ESTIMATE, _ITEMS, client=FakeClient())
    assert letter["body"] == "Our offer follows." and letter["inclusions"] == ["Drilling"]


def test_demo_fixture_short_circuits_offline(monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "true")
    for mod in ("anthropic", "openai", "torch", "sentence_transformers", "fitz", "httpx", "requests"):
        monkeypatch.setitem(sys.modules, mod, None)
    letter = draft_letter(_ESTIMATE, _ITEMS, demo_fixture=LETTER_FIXTURE)
    assert any("Mobilisation" in inc for inc in letter["inclusions"])
    assert any("Statutory" in exc for exc in letter["exclusions"]) and letter["assumptions"]
