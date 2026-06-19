"""Spec for Stage 01 extraction (offline)."""

import sys
from decimal import Decimal

from pipeline.stage_01_extract.extract import extract_facts


def test_extracts_a_clean_claim(load_case):
    facts = extract_facts(load_case("clean"))
    assert facts.claimed_amount.value == Decimal("1250000.00")
    assert facts.claimed_amount.confidence >= 0.6
    assert facts.parties.respondent.value.name.startswith("BigBuild")


def test_messy_source_yields_low_confidence_fields(load_case):
    facts = extract_facts(load_case("messy"))
    # The value is present, but the extractor is unsure.
    assert facts.contract_sum.value is not None
    assert facts.contract_sum.confidence < 0.6


def test_demo_extraction_does_not_import_the_anthropic_sdk(load_case):
    already_imported = "anthropic" in sys.modules
    facts = extract_facts(load_case("clean"))
    assert facts.reference_date.value is not None
    if not already_imported:
        # No SDK import => no network call was made.
        assert "anthropic" not in sys.modules
