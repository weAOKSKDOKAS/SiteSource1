"""Estimate error/omission check (Phase P3d) — L1 checks, corpus-gated rubric, L2 scope gaps."""

import sys

from pipeline.estimate.checks import ESTIMATE_CHECK_FIXTURE, _l1_findings, _rubric_findings, check_estimate

_ESTIMATE = [
    {"item_ref": "G1", "unit": "m", "rate": 1200.0},
    {"item_ref": "G2", "unit": "no", "rate": None},   # unpriced
]
_TENDER = [
    {"item_ref": "G1", "description": "Rotary drilling", "unit": "m"},
    {"item_ref": "G9", "description": "Grouting", "unit": "no"},   # omitted from the estimate
]


def test_l1_flags_omission_and_unpriced():
    kinds = {(f["kind"], f["item_ref"]) for f in _l1_findings(_ESTIMATE, _TENDER)}
    assert ("omission", "G9") in kinds
    assert ("unpriced", "G2") in kinds
    assert not any(k == "unit_mismatch" for k, _ in kinds)   # G1 units match


def test_l1_flags_unit_mismatch():
    est = [{"item_ref": "G1", "unit": "hr", "rate": 10.0}]
    findings = _l1_findings(est, [{"item_ref": "G1", "unit": "m"}])
    assert any(f["kind"] == "unit_mismatch" and f["item_ref"] == "G1" for f in findings)


def test_rubric_is_corpus_gated():
    assert _rubric_findings(_ESTIMATE, []) == []                      # empty rubric -> nothing
    populated = _rubric_findings(_ESTIMATE, [{"item_ref": "R1", "guidance": "Always allow for dewatering."}])
    assert populated and populated[0]["kind"] == "rubric" and "dewatering" in populated[0]["message"]


def test_check_integrates_and_reads_scope_gaps_offline(monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "true")
    for mod in ("anthropic", "openai", "torch", "sentence_transformers", "fitz", "httpx", "requests"):
        monkeypatch.setitem(sys.modules, mod, None)
    out = check_estimate(_ESTIMATE, _TENDER, [], "Reinstate the site on completion.",
                         demo_fixture=ESTIMATE_CHECK_FIXTURE)
    kinds = {f["kind"] for f in out["findings"]}
    assert {"omission", "unpriced", "scope_gap"} <= kinds
    assert out["tender_checked"] is True and out["rubric_size"] == 0


def test_check_fallback_has_no_l2_gaps_but_keeps_l1(monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "true")   # no fixture -> the L2 read is skipped
    out = check_estimate(_ESTIMATE, _TENDER, [], "Reinstate on completion.")
    kinds = {f["kind"] for f in out["findings"]}
    assert "scope_gap" not in kinds and {"omission", "unpriced"} <= kinds
