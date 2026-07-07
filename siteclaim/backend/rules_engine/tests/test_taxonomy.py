"""Deterministic trade-taxonomy normalisation (Layer 1)."""

from rules_engine.taxonomy import CANONICAL_TRADES, normalize, parent_trade, validate_scope
from schemas.models import ScopePackages, TradeWorkPackage


def test_gi_specialties_are_canonical_and_normalise_to_themselves():
    # v3: the three GI specialty sub-trades are first-class canonical keys (register-tagged firms
    # carry them), so they no longer fall unmapped.
    for key in ("field_testing", "field_installations", "geophysical_survey"):
        assert key in CANONICAL_TRADES
        assert normalize(key) == key


def test_parent_trade_returns_ground_investigation_for_specialties_else_identity():
    for key in ("field_testing", "field_installations", "geophysical_survey"):
        assert parent_trade(key) == "ground_investigation"
    assert parent_trade("ground_investigation") == "ground_investigation"
    assert parent_trade("electrical") == "electrical"  # identity for a non-specialty


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


def test_short_abbreviations_do_not_match_as_substrings():
    # The Layer-1 false positive: short abbreviation synonyms (em/lv/rc/me) used to match
    # inside unrelated words ("dEMolition" -> electrical, "vaLVe" -> electrical). They must
    # now be unmapped (None) and surfaced, per the module's "never silently map" rule.
    for word in ("demolition", "valve", "cement", "basement", "pavement", "temporary works", "commercial"):
        assert normalize(word) is None, word


def test_abbreviations_still_map_as_whole_tokens():
    assert normalize("E&M") == "electrical"
    assert normalize("e&m installation") == "electrical"
    assert normalize("LV switchgear") == "electrical"
    assert normalize("MEP") == "mechanical_plumbing"
    assert normalize("M&E") == "mechanical_plumbing"
    assert normalize("RC works") == "reinforced_concrete"
    assert normalize("reinforced concrete") == "reinforced_concrete"


def test_long_synonyms_and_ordering_still_resolve():
    assert normalize("HVAC") == "mechanical_plumbing"
    assert normalize("drainage") == "mechanical_plumbing"
    assert normalize("bored piling") == "foundation_substructure"   # foundation/pile before GI
    assert normalize("rotary drilling ground investigation") == "ground_investigation"
    assert normalize("electrical") == "electrical"


def test_validate_scope_keeps_a_formerly_mis_mapped_trade_unmapped():
    scope = ScopePackages(
        project_name="P",
        packages=[TradeWorkPackage(trade="Demolition", scope_summary="soft strip")],
    )
    normalised, unmapped = validate_scope(scope)
    assert unmapped == ["Demolition"]                          # surfaced, not silently mapped
    assert normalised.packages[0].trade == "Demolition"        # kept unchanged in the output


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
