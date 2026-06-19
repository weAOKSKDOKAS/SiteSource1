"""Spec for Stage 02 self-verification: judge + deterministic engine (offline)."""

from pipeline.stage_01_extract.extract import extract_facts
from pipeline.stage_02_validate.verify import (
    fields_for_review,
    run_stage_02,
    verify_extraction,
)


def test_a_clean_claim_has_no_disputes_or_review_flags(load_case):
    source = load_case("clean")
    review = verify_extraction(source, extract_facts(source))
    assert review.disputed_fields == []
    assert review.review_flags == []


def test_a_messy_claim_is_flagged_for_human_review(load_case):
    source = load_case("messy")
    review = verify_extraction(source, extract_facts(source))
    assert review.review_flags  # non-empty
    flagged = {f.field for f in review.review_flags}
    assert {"contract_sum", "reference_date"} <= flagged
    assert review.disputed_fields  # the judge lowered some confidences


def test_the_judge_lowers_confidence_without_mutating_the_input(load_case):
    source = load_case("messy")
    facts = extract_facts(source)
    original = facts.reference_date.confidence
    review = verify_extraction(source, facts)
    assert review.facts.reference_date.confidence < original  # judge lowered it
    assert facts.reference_date.confidence == original  # original facts untouched


def test_run_stage_02_returns_facts_and_a_validity_report_with_deadlines(load_case, today):
    source = load_case("clean")
    facts, report = run_stage_02(source, extract_facts(source), today)
    assert report.is_valid
    assert report.deadlines is not None
    assert len(report.deadlines.deadlines) == 3


def test_fields_for_review_only_flags_present_low_confidence_fields(load_case):
    facts = extract_facts(load_case("messy"))
    flags = fields_for_review(facts)
    assert flags and all(f.confidence < 0.6 for f in flags)
    # A high-confidence field is not flagged.
    assert "parties.respondent" not in {f.field for f in flags}


def test_the_gotcha_extracts_cleanly_and_passes_stage_02(load_case, today):
    # Extraction is confident; the latent notice/timeline defect is for Stage 04.
    source = load_case("gotcha")
    facts = extract_facts(source)
    review = verify_extraction(source, facts)
    assert review.review_flags == []
    _, report = run_stage_02(source, facts, today)
    assert report.is_valid
