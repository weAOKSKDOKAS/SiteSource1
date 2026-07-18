"""Unit tests for REVIEW s05 (program check) + the deterministic LD/mobilisation recompute."""

from __future__ import annotations

from client_boq import rules
from client_boq.models import (
    SOURCE_PROGRAM,
    STATUS_CANDIDATE,
    STATUS_RULE_FLAGGED,
    ContextSummary,
    ProgramFinding,
)
from client_boq.review.s01_ingest import ingest_review_documents
from client_boq.review.s05_program_check import _line_from_finding, check_program


def test_ld_recompute_and_mobilisation() -> None:
    assert rules.recompute_ld_exposure(1000, 30) == 30000.0
    assert rules.recompute_ld_exposure(None, 30) == 0.0
    assert rules.ld_exceeds_cap(30000, 20000) is True
    assert rules.ld_exceeds_cap(30000, 50000) is False
    assert rules.ld_exceeds_cap(30000, None) is False   # absent cap judged elsewhere (TP-04)
    assert rules.mobilisation_mismatch(3, 2) is True
    assert rules.mobilisation_mismatch(2, 2) is False
    assert rules.mobilisation_mismatch(None, 2) is False


def test_ld_exposure_over_cap_is_rule_flagged_by_recompute() -> None:
    # The AI supplies the numbers; the RULE computes exposure and flags — not the AI.
    f = ProgramFinding(kind="ld_exposure", description="delay exposure", contract_ref="8.3",
                       cited_text="Liquidated damages", ld_rate_per_day=25000, program_days=30,
                       ld_cap_value=100000)
    item = _line_from_finding(f)
    assert item.status == STATUS_RULE_FLAGGED and item.rule_ref == "ld_exposure"
    assert "750000" in item.extracted_value           # 25000 × 30 recomputed deterministically


def test_mobilisation_mismatch_is_rule_flagged() -> None:
    f = ProgramFinding(kind="mobilisation", description="mob mismatch", contract_ref="6.1",
                       cited_text="", scope_mobilisations=4, program_mobilisations=2)
    item = _line_from_finding(f)
    assert item.status == STATUS_RULE_FLAGGED and item.rule_ref == "mobilisation"


def test_program_demo_flags_missing_programme() -> None:
    # The DEMO tender has no programme document → program_not_provided rule_flagged, plus the AI
    # candidate finding. All tagged program.
    lines = check_program(ingest_review_documents([], "demo"), ContextSummary())
    assert all(l.source == SOURCE_PROGRAM for l in lines)
    npp = [l for l in lines if l.kind == "program_not_provided"]
    assert npp and npp[0].status == STATUS_RULE_FLAGGED
    assert any(l.status == STATUS_CANDIDATE for l in lines)
