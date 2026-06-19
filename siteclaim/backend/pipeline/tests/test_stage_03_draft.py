"""Spec for Stage 03 drafting (offline): template structure, placeholders, banners."""

from datetime import date
from decimal import Decimal

from rules_engine.engine import run_validation
from schemas.models import FactField

from pipeline.stage_01_extract.extract import extract_facts
from pipeline.stage_02_validate.verify import verify_extraction
from pipeline.stage_03_draft.draft import draft_claim

_TODAY = date(2026, 3, 2)

_TEMPLATE_SECTIONS = (
    "# PAYMENT CLAIM",
    "## 1. Parties",
    "## 2. The contract",
    "## 3. Amount claimed",
    "## 4. Particulars",
    "## 5. Supporting documents",
    "## 6. Statutory statement",
    "## 7. Service",
)


def _draft_for(load_case, case_id):
    source = load_case(case_id)
    facts = extract_facts(source)
    facts = verify_extraction(source, facts).facts  # confidence-adjusted
    report = run_validation(facts, _TODAY)
    return draft_claim(facts, report)


def test_clean_claim_drafts_a_fileable_document(load_case):
    draft = _draft_for(load_case, "clean")
    md = draft.rendered_markdown
    assert "NOT FILEABLE" not in md
    assert "[⚠️" not in md  # no placeholders
    assert "Ready for review" in md
    # structured fields mapped straight from facts
    assert draft.claimant_name == "Acme Subcontracting Ltd"
    assert draft.claimed_amount == Decimal("1250000.00")
    assert "Cap. 652" in (draft.statutory_statement or "")


def test_draft_follows_the_cic_template_structure(load_case):
    md = _draft_for(load_case, "clean").rendered_markdown
    for section in _TEMPLATE_SECTIONS:
        assert section in md, f"missing template section: {section}"


def test_messy_claim_drafts_with_warning_banner_and_placeholders(load_case):
    draft = _draft_for(load_case, "messy")
    md = draft.rendered_markdown
    assert "NOT FILEABLE" not in md  # messy is valid (no fatal)
    assert "DRAFT — not ready to file" in md  # warning banner
    assert "[⚠️" in md and "UNVERIFIED" in md  # low-confidence placeholders
    # the value is still carried in the structured field (not dropped/invented)
    assert draft.claimed_amount == Decimal("1250000.00")


def test_gotcha_draft_carries_a_not_fileable_banner_citing_the_engine(load_case):
    draft = _draft_for(load_case, "gotcha")
    md = draft.rendered_markdown
    assert "NOT FILEABLE" in md
    # The banner quotes the engine's fatal finding — the drafter does not re-judge.
    assert "notice.correct_party" in md


def test_a_missing_mandatory_field_becomes_a_placeholder_not_invention(load_case):
    facts = extract_facts(load_case("clean"))
    facts.claimed_amount = FactField(value=None)  # drop the claimed amount
    report = run_validation(facts, _TODAY)
    draft = draft_claim(facts, report)
    assert "MISSING: claimed amount" in draft.rendered_markdown
    assert draft.claimed_amount is None  # not invented


def test_draft_notes_the_bilingual_todo(load_case):
    # The Traditional Chinese (bilingual) phase is flagged, not implemented.
    assert "TODO(i18n)" in _draft_for(load_case, "clean").rendered_markdown
