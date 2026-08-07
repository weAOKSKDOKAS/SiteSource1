"""Submission: freeze the offer at the moment it goes out, record the proof, refuse the unapproved.

The three guarantees the brief names — no submission without an approve (hard), an immutable
snapshot, and an honest `on_time` (NULL when the deadline is unknown) — each get a test.
"""

import pytest

from bridge import submission
from client_boq import store
from client_boq.models import LetterOfOffer


def _seed_letter(set_id: str, price: float = 1_250_000.0, markdown: str = "OFFER v1") -> None:
    conn = store.get_conn()
    try:
        store.upsert_document_set(conn, set_id=set_id, name=set_id, slug=set_id, status="estimated")
        store.save_letter(conn, LetterOfOffer(
            set_id=set_id, price=price, price_str=f"HK${price:,.0f}", markdown=markdown))
    finally:
        conn.close()


def _set_deadline(set_id: str, date: str, status: str = "confirmed") -> None:
    conn = store.get_conn()
    try:
        store.upsert_set_meta(conn, set_id, close_date=date, close_date_status=status)
    finally:
        conn.close()


def _approve(set_id: str) -> None:
    submission.confirm_final_approval(set_id, "approve", approved_by="R. Lam")


# -- refused without an approve (HARD) --------------------------------------------------------------
def test_submission_is_refused_without_a_final_approve():
    _seed_letter("nd-2025-04")
    with pytest.raises(submission.NotApproved, match="no final approval"):
        submission.record_submission("nd-2025-04", proof="portal-ref-123")


def test_a_revise_verdict_does_not_authorise_submission():
    _seed_letter("nd-2025-04")
    submission.confirm_final_approval("nd-2025-04", "revise", "fix exclusion 4")
    with pytest.raises(submission.NotApproved):
        submission.record_submission("nd-2025-04", proof="x")


def test_an_approved_tender_with_no_letter_is_still_refused():
    """Approved but nothing to submit — the estimate never assembled the letter."""
    _approve("nd-2025-04")
    with pytest.raises(submission.NotApproved, match="no offer letter"):
        submission.record_submission("nd-2025-04", proof="x")


def test_an_approved_tender_with_a_letter_submits():
    _seed_letter("nd-2025-04")
    _approve("nd-2025-04")
    rec = submission.record_submission("nd-2025-04", proof="e-portal 2026-000481",
                                       submitted_by="S. Wong")

    assert rec["proof"] == "e-portal 2026-000481"
    assert rec["submitted_by"] == "S. Wong" and rec["submitted_at"]
    assert rec["price_snapshot"] == 1_250_000.0
    assert "R. Lam" in rec["approval_ref"]
    assert submission.is_submitted("nd-2025-04") is True


# -- the snapshot is frozen -------------------------------------------------------------------------
def test_a_later_letter_edit_does_not_change_a_recorded_submission():
    """The immutability guarantee: what was submitted is what was submitted."""
    _seed_letter("nd-2025-04", price=1_000_000.0, markdown="OFFER v1")
    _approve("nd-2025-04")
    submission.record_submission("nd-2025-04", proof="ref-1")

    # the estimate is re-run and the letter changes underneath
    _seed_letter("nd-2025-04", price=9_999_999.0, markdown="OFFER v2 REPRICED")

    frozen = submission.load_submission("nd-2025-04")
    assert frozen["price_snapshot"] == 1_000_000.0
    assert frozen["letter_snapshot"]["markdown"] == "OFFER v1"
    assert store_letter_price("nd-2025-04") == 9_999_999.0, "the live letter did move"


def store_letter_price(set_id: str) -> float:
    conn = store.get_conn()
    try:
        return store.load_letter(conn, set_id).price
    finally:
        conn.close()


def test_proof_is_stored_verbatim_never_fabricated():
    _seed_letter("nd-2025-04")
    _approve("nd-2025-04")
    rec = submission.record_submission("nd-2025-04", proof="")
    assert rec["proof"] == "", "no proof supplied means no proof recorded, not an invented one"


# -- on_time honesty --------------------------------------------------------------------------------
def test_on_time_when_submitted_before_a_known_deadline():
    _seed_letter("nd-2025-04")
    _set_deadline("nd-2025-04", "2099-12-31")            # far future, so 'now' is before it
    _approve("nd-2025-04")
    assert submission.record_submission("nd-2025-04", proof="x")["on_time"] == 1


def test_late_when_submitted_after_a_known_deadline():
    _seed_letter("nd-2025-04")
    _set_deadline("nd-2025-04", "2000-01-01")            # long past
    _approve("nd-2025-04")
    rec = submission.record_submission("nd-2025-04", proof="x")

    assert rec["on_time"] == 0, "a past-deadline submission still records, but flags on_time=0"
    assert rec["deadline"] == "2000-01-01"


def test_on_time_is_unknown_when_no_deadline_is_parsed():
    """`None`, never a fabricated pass. The desk shows 'deadline unknown'."""
    _seed_letter("nd-2025-04")
    _approve("nd-2025-04")
    rec = submission.record_submission("nd-2025-04", proof="x")

    assert rec["on_time"] is None and rec["deadline"] == ""


def test_a_reading_deadline_is_treated_as_unknown():
    """`close_date_status` 'reading'/'not_found' means we do not have one — it must not become a pass."""
    _seed_letter("nd-2025-04")
    _set_deadline("nd-2025-04", "2099-12-31", status="not_found")
    _approve("nd-2025-04")
    assert submission.record_submission("nd-2025-04", proof="x")["on_time"] is None


# -- identity ---------------------------------------------------------------------------------------
def test_an_empty_set_id_is_refused():
    with pytest.raises(ValueError):
        submission.record_submission("", proof="x")


def test_a_tender_never_submitted_reads_back_none():
    assert submission.load_submission("never-touched") is None
    assert submission.is_submitted("never-touched") is False


def test_re_submission_replaces_and_re_freezes():
    _seed_letter("nd-2025-04", price=1_000_000.0)
    _approve("nd-2025-04")
    submission.record_submission("nd-2025-04", proof="first")
    _seed_letter("nd-2025-04", price=1_100_000.0)        # a corrected letter before the deadline
    rec = submission.record_submission("nd-2025-04", proof="corrected")

    assert rec["proof"] == "corrected" and rec["price_snapshot"] == 1_100_000.0
    assert submission.load_submission("nd-2025-04")["proof"] == "corrected", "one record, replaced"
