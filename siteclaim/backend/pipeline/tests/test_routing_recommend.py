"""Routing Layer-2 recommendation (Phase P1c) — fallback, fixture, offline discipline."""

from pipeline.routing.recommend import ROUTE_SUGGESTIONS_FIXTURE, fallback_route, recommend_routes


def test_fallback_covers_every_signal_shape_with_a_valid_route():
    # specialist thin pool with a sublet pool -> sublet
    r, why = fallback_route({"thin_pool": True, "assessable_firm_count": 4, "trade_firm_count": 4})
    assert r == "sublet" and "thin" in why.lower()
    # strong in-house history + broad pool -> self-perform
    r, _ = fallback_route({"thin_pool": False, "in_house_history": 3, "assessable_firm_count": 5, "trade_firm_count": 20})
    assert r == "self_perform"
    # no pool at all -> self-perform
    r, _ = fallback_route({"thin_pool": True, "assessable_firm_count": 0, "trade_firm_count": 0})
    assert r == "self_perform"
    # plenty of subs -> sublet
    r, _ = fallback_route({"thin_pool": False, "assessable_firm_count": 6, "trade_firm_count": 30, "in_house_history": 0})
    assert r == "sublet"


def test_recommend_uses_model_suggestions_and_falls_back_for_uncovered(monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "false")  # consult the injected client (no real network — it's a fake)

    class FakeClient:
        def complete_json(self, *, user, target_model, **_):
            return target_model(suggestions=[
                {"package_key": "electrical", "recommended_route": "sublet", "rationale": "deep pool"},
            ])

    packages = [
        {"package_key": "electrical", "trade": "electrical", "signals": {"assessable_firm_count": 5}},
        {"package_key": "joinery_fitting_out", "trade": "joinery_fitting_out",
         "signals": {"in_house_history": 2, "thin_pool": False, "assessable_firm_count": 3, "trade_firm_count": 10}},
    ]
    out = {p["package_key"]: p for p in recommend_routes(packages, client=FakeClient())}
    assert out["electrical"]["recommended_route"] == "sublet" and out["electrical"]["source"] == "route-suggest"
    assert out["joinery_fitting_out"]["recommended_route"] == "self_perform"  # not covered -> fallback
    assert out["joinery_fitting_out"]["source"] == "fallback"


def test_recommend_ignores_an_invalid_model_route_and_falls_back(monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "false")

    class BadClient:
        def complete_json(self, *, user, target_model, **_):
            return target_model(suggestions=[{"package_key": "x", "recommended_route": "banana", "rationale": "?"}])

    out = recommend_routes([{"package_key": "x", "signals": {"assessable_firm_count": 0, "trade_firm_count": 0}}],
                           client=BadClient())
    assert out[0]["recommended_route"] in ("self_perform", "sublet") and out[0]["source"] == "fallback"


def test_demo_fixture_short_circuits_offline(monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "true")
    import sys

    for mod in ("anthropic", "openai", "torch", "sentence_transformers", "fitz"):
        monkeypatch.setitem(sys.modules, mod, None)
    packages = [{"package_key": "electrical", "trade": "electrical", "signals": {}}]
    out = recommend_routes(packages, demo_fixture=ROUTE_SUGGESTIONS_FIXTURE)
    assert out[0]["recommended_route"] == "sublet" and out[0]["source"] == "route-suggest"


def test_demo_without_fixture_uses_fallback_only(monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "true")
    # no fixture + DEMO -> the model is never called; the deterministic fallback drives it
    out = recommend_routes([{"package_key": "electrical", "signals": {"assessable_firm_count": 5, "trade_firm_count": 20}}])
    assert out[0]["source"] == "fallback" and out[0]["recommended_route"] == "sublet"
