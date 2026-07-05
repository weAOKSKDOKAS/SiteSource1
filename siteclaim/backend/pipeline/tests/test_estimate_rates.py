"""Corpus-gated rate suggestion (Phase P3c) — tiers, rate band, rate warnings, empty state."""

from pipeline.estimate.rates import suggest_rates

_CORPUS = [
    {"item_ref": "G1", "description": "Rotary drilling in soil", "tender_rate": 1200.0,
     "reason_code": "standing_time", "rate_delta": 300.0},
    {"item_ref": "G2", "description": "Rotary drilling in rock", "tender_rate": 1800.0,
     "reason_code": "standing_time", "rate_delta": 300.0},
    {"item_ref": "G3", "description": "Standard penetration test", "tender_rate": 450.0,
     "reason_code": "quantity_remeasure", "rate_delta": 0.0},
]


def test_exact_ref_gives_tier1_band_and_rate_warning():
    out = suggest_rates([{"id": 1, "item_ref": "G1"}], _CORPUS)
    assert out["corpus_empty"] is False and out["corpus_size"] == 3
    s = out["suggestions"][0]
    assert s["tier"] == 1 and s["matched_ref"] == "G1" and s["rate_median"] == 1200.0
    assert s["rate_warnings"] == [{"reason_code": "standing_time", "count": 1}]


def test_rate_warning_only_fires_when_the_rate_moved():
    # G3 varied on quantity, not rate (rate_delta 0) -> a precedent, but no RATE warning.
    s = suggest_rates([{"id": 2, "item_ref": "G3"}], _CORPUS)["suggestions"][0]
    assert s["tier"] == 1 and s["rate_median"] == 450.0 and s["rate_warnings"] == []


def test_tier2_matches_on_description_when_ref_differs():
    s = suggest_rates([{"id": 3, "item_ref": "NEW-1", "description": "Rotary drilling in soil"}], _CORPUS)["suggestions"][0]
    assert s["tier"] == 2 and s["matched_ref"] == "G1" and s["rate_median"] == 1200.0
    assert (s["similarity"] or 0) >= 0.72


def test_no_precedent_is_tier0():
    s = suggest_rates([{"id": 4, "item_ref": "ZZ", "description": "bespoke ironmongery widget"}], _CORPUS)["suggestions"][0]
    assert s["tier"] == 0 and s["sample_count"] == 0 and s["rate_median"] is None and s["rate_warnings"] == []


def test_empty_corpus_is_the_honest_empty_state():
    out = suggest_rates([{"id": 1, "item_ref": "G1"}], [])
    assert out["corpus_empty"] is True and out["corpus_size"] == 0
    assert out["suggestions"][0]["tier"] == 0 and out["suggestions"][0]["rate_median"] is None
