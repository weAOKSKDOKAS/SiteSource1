"""Deterministic trade-taxonomy normalisation (Layer 1)."""

from rules_engine.taxonomy import CANONICAL_TRADES, normalize, validate_scope
from schemas.models import ScopePackages, TradeWorkPackage


def test_canonical_keys_loaded_from_the_rubric():
    # Parsed from references/rubrics/trade_taxonomy.md, not hard-coded in the test.
    assert {"electrical", "mechanical_plumbing", "fire_services", "joinery_fitting_out"} <= CANONICAL_TRADES


def test_exact_key_passes_through():
    assert normalize("electrical") == "electrical"


def test_labels_and_synonyms_map_to_canonical():
    assert normalize("Mechanical & Plumbing") == "mechanical_plumbing"
    assert normalize("Fire Services") == "fire_services"
    assert normalize("Joinery & Fitting-out") == "joinery_fitting_out"
    assert normalize("E&M — Electrical") == "electrical"
    assert normalize("Reinforced Concrete") == "reinforced_concrete"


def test_ground_investigation_is_canonical_and_synonyms_resolve():
    # v2: the GI trade and its label/synonyms, shared by scope split and doc classifier.
    assert "ground_investigation" in CANONICAL_TRADES
    for label in (
        "Ground investigation", "Ground Investigation Field Work", "GI field works",
        "Site Investigation", "geotechnical", "Geotechnical Works", "drilling",
    ):
        assert normalize(label) == "ground_investigation", label


def test_ground_investigation_synonyms_do_not_steal_foundation_scopes():
    # 'drilling' maps to GI, but a bored-pile scope must still be foundation work
    # (foundation/pile synonyms are checked before the GI synonyms).
    assert normalize("bored pile drilling") == "foundation_substructure"
    assert normalize("piling") == "foundation_substructure"


def test_unmapped_trade_returns_none():
    assert normalize("Astrophysics") is None


def test_validate_scope_normalises_and_surfaces_unmapped():
    scope = ScopePackages(
        project_name="P",
        packages=[
            TradeWorkPackage(trade="Mechanical & Plumbing", scope_summary="x"),
            TradeWorkPackage(trade="Quantum Widgets", scope_summary="y"),
        ],
    )
    normalised, unmapped = validate_scope(scope)
    assert normalised.packages[0].trade == "mechanical_plumbing"
    # the unmapped trade is surfaced AND kept (never silently dropped)
    assert unmapped == ["Quantum Widgets"]
    assert normalised.packages[1].trade == "Quantum Widgets"
