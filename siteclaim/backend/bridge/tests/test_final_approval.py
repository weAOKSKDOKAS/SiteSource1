"""The tender's last human gate: approve or revise, and the revise must say what to correct.

Mirrors the route-decision store tests. The machine assembles the letter; the verdict is always the
human's, recorded here and nowhere else.
"""

import pytest

from bridge import submission


# -- verdict validation ----------------------------------------------------------------------------
def test_an_approve_verdict_is_recorded():
    row = submission.confirm_final_approval("nd-2025-04", "approve", approved_by="R. Lam")

    assert row["verdict"] == "approve"
    assert row["approved_by"] == "R. Lam" and row["approved_at"]
    assert submission.is_approved("nd-2025-04") is True


def test_a_revise_verdict_carries_its_rationale():
    row = submission.confirm_final_approval("nd-2025-04", "revise",
                                            "Exclusion 4 contradicts the priced scope.")
    assert row["verdict"] == "revise"
    assert row["rationale"] == "Exclusion 4 contradicts the priced scope."
    assert submission.is_approved("nd-2025-04") is False


@pytest.mark.parametrize("bad", ["", "approved", "reject", "APPROVE ", "yes"])
def test_an_unknown_verdict_is_refused(bad):
    with pytest.raises(ValueError, match="verdict must be one of"):
        submission.confirm_final_approval("nd-2025-04", bad)


# -- rationale required for revise ------------------------------------------------------------------
@pytest.mark.parametrize("blank", ["", "   ", "\n\t"])
def test_a_revise_without_a_rationale_is_refused(blank):
    """Node 47 is 'what to correct'. A revise that says nothing to correct is not actionable."""
    with pytest.raises(ValueError, match="must say what to correct"):
        submission.confirm_final_approval("nd-2025-04", "revise", blank)


def test_an_approve_needs_no_rationale():
    row = submission.confirm_final_approval("nd-2025-04", "approve")
    assert row["verdict"] == "approve" and row["rationale"] == ""


# -- upsert keeps who/when --------------------------------------------------------------------------
def test_re_deciding_replaces_in_place():
    submission.confirm_final_approval("nd-2025-04", "revise", "fix exclusion 4", approved_by="R. Lam")
    row = submission.confirm_final_approval("nd-2025-04", "approve", approved_by="S. Wong")

    assert row["verdict"] == "approve"
    assert row["approved_by"] == "S. Wong"
    assert row["rationale"] == "", "the revise rationale does not linger on a later approve"
    # one row, not two contradictory verdicts read back in insertion order
    assert submission.load_final_approval("nd-2025-04")["verdict"] == "approve"


def test_two_tenders_keep_their_own_verdicts():
    submission.confirm_final_approval("nd-2025-04", "approve")
    submission.confirm_final_approval("ge-2026-14", "revise", "raise the prelims")

    assert submission.is_approved("nd-2025-04") is True
    assert submission.is_approved("ge-2026-14") is False


# -- identity resolution + refusal ------------------------------------------------------------------
def test_an_empty_set_id_is_refused_not_minted():
    """`run_ref_for` refuses an empty id — an unresolvable name is never turned into a row."""
    with pytest.raises(ValueError):
        submission.confirm_final_approval("", "approve")


def test_a_tender_never_decided_reads_back_none():
    assert submission.load_final_approval("never-touched") is None
    assert submission.is_approved("never-touched") is False


def test_load_resolves_the_same_id_it_was_written_under():
    submission.confirm_final_approval("nd-2025-04", "approve")
    assert submission.load_final_approval("nd-2025-04")["set_id"] == "nd-2025-04"
