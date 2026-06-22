"""Deterministic work-package taxonomy normalisation (Layer 1) — generic across
building and civil / ground-investigation tenders."""

from rules_engine.taxonomy import CANONICAL_TRADES, normalize, validate_scope
from schemas.models import ScopePackages, TradeWorkPackage


def test_canonical_keys_loaded_from_the_rubric():
    # Parsed from references/rubrics/trade_taxonomy.md, not hard-coded in the test.
    assert {"electrical", "mechanical_plumbing", "fire_services", "joinery_fitting_out"} <= CANONICAL_TRADES
    # the civil / ground-investigation group is present too
    assert {"drilling", "sampling", "field_testing", "field_installations", "drainage_works"} <= CANONICAL_TRADES


def test_exact_key_passes_through():
    assert normalize("electrical") == "electrical"


def test_building_labels_and_synonyms_map_to_canonical():
    assert normalize("Mechanical & Plumbing") == "mechanical_plumbing"
    assert normalize("Fire Services") == "fire_services"
    assert normalize("Joinery & Fitting-out") == "joinery_fitting_out"
    assert normalize("E&M — Electrical") == "electrical"
    assert normalize("Reinforced Concrete") == "reinforced_concrete"


def test_civil_ground_investigation_labels_map_to_canonical():
    assert normalize("Ground investigation") == "ground_investigation"
    assert normalize("Drilling") == "drilling"
    assert normalize("rotary drilling") == "drilling"
    assert normalize("Sampling") == "sampling"
    assert normalize("Field testing") == "field_testing"
    assert normalize("Field installations") == "field_installations"
    assert normalize("piezometer installation") == "field_installations"
    assert normalize("permeability test") == "field_testing"
    assert normalize("Drainage works") == "drainage_works"
    assert normalize("Slope") == "slope_works"


def test_drainage_field_test_is_not_building_mechanical_plumbing():
    # the bug this fixes: a civil drainage field test used to mis-map to building M&P
    result = normalize("drainage field test")
    assert result != "mechanical_plumbing"
    assert result == "field_testing"


def test_unmapped_trade_returns_none():
    assert normalize("Astrophysics") is None


def test_validate_scope_normalises_and_slugifies_unmapped():
    scope = ScopePackages(
        project_name="P",
        packages=[
            TradeWorkPackage(trade="Mechanical & Plumbing", scope_summary="x"),
            TradeWorkPackage(trade="Quantum Widgets", scope_summary="y"),
        ],
    )
    normalised, unmapped = validate_scope(scope)
    assert normalised.packages[0].trade == "mechanical_plumbing"
    # the non-canonical package is kept under a slugified key (a valid work-package
    # key), and its original label is surfaced for transparency — not an error
    assert normalised.packages[1].trade == "quantum_widgets"
    assert unmapped == ["Quantum Widgets"]


def test_validate_scope_runs_a_ground_investigation_tender_cleanly():
    gi = ScopePackages(
        project_name="Drainage field-test ground investigation",
        packages=[
            TradeWorkPackage(trade="Drilling", scope_summary="rotary boreholes"),
            TradeWorkPackage(trade="Sampling", scope_summary="undisturbed soil samples"),
            TradeWorkPackage(trade="Field testing", scope_summary="SPT and permeability"),
            TradeWorkPackage(trade="Field installations", scope_summary="piezometers and standpipes"),
            TradeWorkPackage(trade="Drainage works", scope_summary="channels and culverts"),
        ],
    )
    normalised, unmapped = validate_scope(gi)
    assert unmapped == []  # a GI tender maps cleanly — no "unmapped" failure
    assert [p.trade for p in normalised.packages] == [
        "drilling",
        "sampling",
        "field_testing",
        "field_installations",
        "drainage_works",
    ]
