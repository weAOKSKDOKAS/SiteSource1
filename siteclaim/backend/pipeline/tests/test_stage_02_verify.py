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


def test_the_gotcha_extracts_cleanly_but_is_invalid_on_wrong_party(load_case, today):
    # Clean extraction (high confidence, no review) BUT a latent LEGAL defect: the
    # claim was served on a different legal entity than the contracting party, so
    # notice.correct_party is FATAL and the report is INVALID. The judge does not
    # flag it — it only checks whether facts are supported by the source.
    source = load_case("gotcha")
    facts = extract_facts(source)
    review = verify_extraction(source, facts)
    assert review.review_flags == []  # extraction quality is fine
    assert review.disputed_fields == []  # both party names are supported by the source

    _, report = run_stage_02(source, facts, today)
    assert report.has_fatal and not report.is_valid
    correct_party = next(c for c in report.checks if c.name == "notice.correct_party")
    assert correct_party.severity.value == "fatal" and not correct_party.passed
    # The single fatal stays crisp — service method is a clean INFO, no competing warning.
    method = next(c for c in report.checks if c.name == "notice.method")
    assert method.severity.value == "info"
