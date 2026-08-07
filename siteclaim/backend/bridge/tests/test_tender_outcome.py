"""The tender outcome — did WE win it. Distinct from the sublet award, and human-recorded."""

import pytest

from bridge import closeout


def test_an_outcome_is_recorded():
    row = closeout.set_outcome("nd-2025-04", "won",
                               "Awarded at HK$1.25m; nearest competitor +6%.", decided_by="R. Lam")
    assert row["status"] == "won"
    assert "1.25m" in row["outcome_notes"]
    assert row["decided_by"] == "R. Lam" and row["decided_at"]


@pytest.mark.parametrize("status", ["submitted", "won", "lost", "withdrawn"])
def test_every_valid_status_is_accepted(status):
    assert closeout.set_outcome("nd-2025-04", status)["status"] == status


@pytest.mark.parametrize("bad", ["", "WON", "awarded", "win", "pending"])
def test_an_unknown_status_is_refused(bad):
    with pytest.raises(ValueError, match="status must be one of"):
        closeout.set_outcome("nd-2025-04", bad)


def test_re_deciding_replaces_and_keeps_who_when():
    closeout.set_outcome("nd-2025-04", "submitted")
    row = closeout.set_outcome("nd-2025-04", "lost", "Price 8% over the winner.", decided_by="S. Wong")

    assert row["status"] == "lost" and row["decided_by"] == "S. Wong"
    assert closeout.load_outcome("nd-2025-04")["status"] == "lost", "one row, replaced"


def test_two_tenders_keep_their_own_outcomes():
    closeout.set_outcome("nd-2025-04", "won")
    closeout.set_outcome("ge-2026-14", "lost")

    assert closeout.load_outcome("nd-2025-04")["status"] == "won"
    assert closeout.load_outcome("ge-2026-14")["status"] == "lost"


def test_notes_are_stored_verbatim_and_optional():
    assert closeout.set_outcome("nd-2025-04", "won")["outcome_notes"] == ""
    assert closeout.set_outcome("nd-2025-04", "won", "  keep this  ")["outcome_notes"] == "keep this"


def test_a_tender_with_no_outcome_reads_back_none():
    assert closeout.load_outcome("never-touched") is None


def test_an_empty_set_id_is_refused():
    with pytest.raises(ValueError):
        closeout.set_outcome("", "won")


def test_the_corpus_outcomes_are_only_won_and_lost():
    """A guard on the constant the feedback hook keys on — submitted/withdrawn feed nothing."""
    assert set(closeout.CORPUS_OUTCOMES) == {"won", "lost"}
