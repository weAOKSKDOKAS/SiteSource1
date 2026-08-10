"""The bid/no-bid verdict store — the same decision+record shape as final approval and closeout.

The estimator's earliest real decision, and the one the system used to assume: routing, sourcing
and pricing all began without anybody recording that the tender was being pursued at all.

What this file holds to: the verdict is validated before it is written, `no_bid` and `clarify` must
say why, re-deciding replaces rather than accumulates, the strategic factors are stored verbatim
because they are the operator's own words, and identity is `run_ref` — an unresolvable name is
refused, never minted.
"""

from __future__ import annotations

import pytest

from bridge import bid

SET = "bid-store-test"


def test_a_bid_needs_no_rationale_because_proceeding_is_the_default_posture():
    stored = bid.confirm_bid(SET, bid.BID, decided_by="SW")
    assert stored["verdict"] == "bid"
    assert stored["rationale"] == ""
    assert stored["decided_by"] == "SW" and stored["decided_at"]


@pytest.mark.parametrize("verdict", [bid.NO_BID, bid.CLARIFY])
def test_declining_or_pausing_must_say_why(verdict):
    """Somebody will be asked about this decision months from now. A verdict with no reason is not
    one they can defend."""
    with pytest.raises(ValueError) as raised:
        bid.confirm_bid(SET, verdict, "   ")
    assert "rationale is required" in str(raised.value)
    assert "defend" in str(raised.value)


@pytest.mark.parametrize("verdict", [bid.NO_BID, bid.CLARIFY])
def test_declining_or_pausing_with_a_reason_is_recorded(verdict):
    stored = bid.confirm_bid(SET, verdict, "the deadline is inside our shutdown", decided_by="SW")
    assert stored["verdict"] == verdict
    assert stored["rationale"] == "the deadline is inside our shutdown"


def test_an_unknown_verdict_is_refused_and_names_the_three():
    with pytest.raises(ValueError) as raised:
        bid.confirm_bid(SET, "maybe", "…")
    assert "'bid'" in str(raised.value) and "'no_bid'" in str(raised.value)
    assert "'clarify'" in str(raised.value)


def test_re_deciding_replaces_and_moves_the_stamp():
    """A tender marked `clarify` that later becomes a `bid` is the same decision revisited, not two
    — and the record is of the position now held."""
    first = bid.confirm_bid(SET, bid.CLARIFY, "three questions with the client", decided_by="SW")
    second = bid.confirm_bid(SET, bid.BID, decided_by="RL")

    assert second["verdict"] == "bid" and second["decided_by"] == "RL"
    assert second["rationale"] == "", "the clarify rationale did not survive onto the bid"
    assert second["decided_at"] >= first["decided_at"]
    assert bid.load_bid_decision(SET)["verdict"] == "bid", "one row, not two"


def test_the_strategic_factors_are_stored_verbatim_and_nothing_computes_them():
    """Fit, capacity and win probability are the three numbers this screen most wants to show and
    the three the machine has no basis for. They are the human's, stored as given."""
    factors = {"fit": "strong — we drilled the adjacent contract",
               "capacity": "two rigs free from March", "win_probability": "unknown",
               "notes": "client has used us twice"}
    stored = bid.confirm_bid(SET, bid.BID, factors=factors, decided_by="SW")
    assert stored["factors"] == factors
    assert stored["factors"]["win_probability"] == "unknown", "never a fabricated number"


def test_factors_default_to_empty_rather_than_to_anything_invented():
    stored = bid.confirm_bid(SET, bid.BID)
    assert stored["factors"] == {}


def test_not_yet_decided_is_a_state_not_an_error():
    assert bid.load_bid_decision("a-tender-nobody-has-ruled-on") is None


def test_an_unresolvable_name_is_refused_never_minted():
    """Identity discipline: a display string never becomes a key."""
    for call in (lambda: bid.confirm_bid("", bid.BID), lambda: bid.load_bid_decision("")):
        with pytest.raises(ValueError):
            call()


def test_a_damaged_factors_blob_is_reported_rather_than_dropped(tmp_path, monkeypatch):
    """Losing somebody's stated reasoning silently is worse than showing it is unreadable."""
    from bridge.identity import bridge_conn, run_ref_for

    bid.confirm_bid(SET, bid.BID, factors={"fit": "strong"})
    conn = bridge_conn()
    try:
        conn.execute("UPDATE bridge_bid_decisions SET factors_json = ? WHERE set_id = ?",
                     ("{not json", run_ref_for(SET)))
        conn.commit()
    finally:
        conn.close()

    stored = bid.load_bid_decision(SET)
    assert stored["factors"] == {"_unreadable": "{not json"}


def test_the_verdicts_are_exactly_three_and_no_bid_is_one_of_them():
    """The RULE never proposes `no_bid` (see `recommend`), but a PERSON must be able to record it —
    that is the whole point of the decision being theirs."""
    assert set(bid.BID_VERDICTS) == {"bid", "no_bid", "clarify"}
