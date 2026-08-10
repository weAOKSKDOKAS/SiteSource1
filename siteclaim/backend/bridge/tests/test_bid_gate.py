"""The bid gate — one decision earlier than the review gate, and the same switch.

The review gate asks "has anybody read the terms?". This one asks the question before it: "has
anybody decided we are pursuing this at all?" Routing and sourcing used to begin on the assumption
that every tender was being chased, and a shortlist assembled for a tender nobody meant to bid is
work spent on nothing.

SAME SEMANTICS AS `REVIEW_GATE`, deliberately — soft by default, an unreadable value reads as soft,
and **soft never means silent**. A gate that stops gating and says nothing is worse than no gate,
because the absence of a warning reads as approval.

THREE NON-BID STATES, THREE SENTENCES. An undecided tender and one somebody deliberately declined
are not the same situation and must not read as though they were.

WHAT IT DOES NOT GATE: the review itself. Deciding whether to bid comes AFTER reading the contract
— gating the Register on a bid decision would invert the order the estimator works in and make the
decision unmakeable. Pinned below.
"""

from __future__ import annotations

import pytest

from bridge import bid, decisions
from bridge.identity import bridge_conn, run_ref_for
from client_boq import gates
from client_boq import models as cb_models
from client_boq import store as cb_store

SET = "bid-gate-test"


@pytest.fixture
def soft(monkeypatch):
    monkeypatch.setenv("BID_GATE", "soft")


@pytest.fixture
def hard(monkeypatch):
    monkeypatch.setenv("BID_GATE", "hard")


@pytest.fixture
def conn():
    handle = bridge_conn()
    try:
        yield handle
    finally:
        handle.close()


@pytest.fixture(autouse=True)
def _undecided(conn):
    """Every case starts with no decision, so a leftover row from another test cannot pass one."""
    conn.execute("DROP TABLE IF EXISTS bridge_bid_decisions")
    conn.commit()


def _decide(verdict: str, rationale: str = "because") -> None:
    bid.confirm_bid(SET, verdict, rationale if verdict != bid.BID else "")


class TestTheMode:
    def test_it_is_soft_by_default(self, monkeypatch):
        monkeypatch.delenv("BID_GATE", raising=False)
        assert gates.bid_gate_mode() == "soft"

    def test_an_unreadable_value_reads_as_soft(self, monkeypatch):
        """A deployment that 409s for a reason nobody typed is the harder failure to diagnose."""
        for value in ("HARDish", "true", "1", "  "):
            monkeypatch.setenv("BID_GATE", value)
            assert gates.bid_gate_mode() == "soft", value

    def test_hard_is_exact_and_case_insensitive(self, monkeypatch):
        for value in ("hard", "HARD", " Hard "):
            monkeypatch.setenv("BID_GATE", value)
            assert gates.bid_gate_mode() == "hard", value


class TestSoftWarnsAndProceeds:
    def test_no_decision_warns(self, soft, conn):
        note = decisions.require_bid_to_proceed(conn, run_ref_for(SET))
        assert note == gates.BID_GATE_UNDECIDED
        assert "nobody has decided to pursue" in note

    def test_no_bid_warns_loudly_and_differently(self, soft, conn):
        _decide(bid.NO_BID, "no rigs free")
        note = decisions.require_bid_to_proceed(conn, run_ref_for(SET))
        assert note == gates.BID_GATE_NO_BID
        assert "marked NO-BID" in note and "proceeding anyway" in note

    def test_clarify_warns_and_says_which_problem(self, soft, conn):
        _decide(bid.CLARIFY, "three questions out")
        note = decisions.require_bid_to_proceed(conn, run_ref_for(SET))
        assert note == gates.BID_GATE_CLARIFY
        assert "CLARIFY" in note and "open questions are unresolved" in note

    def test_the_three_warnings_are_three_different_sentences(self):
        """An undecided tender and one deliberately declined are not the same situation."""
        assert len({gates.BID_GATE_UNDECIDED, gates.BID_GATE_NO_BID, gates.BID_GATE_CLARIFY}) == 3

    def test_a_bid_proceeds_silently(self, soft, conn):
        _decide(bid.BID)
        assert decisions.require_bid_to_proceed(conn, run_ref_for(SET)) is None


class TestHardRefuses:
    @pytest.mark.parametrize("verdict,rationale", [
        (None, ""), (bid.NO_BID, "no rigs free"), (bid.CLARIFY, "three questions out"),
    ])
    def test_every_non_bid_state_raises(self, hard, conn, verdict, rationale):
        if verdict:
            _decide(verdict, rationale)
        with pytest.raises(decisions.BidNotDecided):
            decisions.require_bid_to_proceed(conn, run_ref_for(SET))

    def test_the_refusal_says_how_to_proceed(self, hard, conn):
        with pytest.raises(decisions.BidNotDecided) as raised:
            decisions.require_bid_to_proceed(conn, run_ref_for(SET))
        message = str(raised.value)
        # RE-ANCHORED: pinned "/bid/confirm" — an endpoint. The refusal now names the Bid tab;
        # the operator escape (BID_GATE=soft) stays, labelled as the operator's.
        assert "Bid tab" in message
        assert "BID_GATE=soft" in message
        assert "(BID_GATE=soft)" not in message.split("Record a bid")[0], (
            "the soft-mode suffix does not belong in a hard-mode refusal")

    def test_a_bid_proceeds(self, hard, conn):
        _decide(bid.BID)
        assert decisions.require_bid_to_proceed(conn, run_ref_for(SET)) is None


class TestItDoesNotGateTheReview:
    """Deciding whether to bid comes AFTER reading the contract. Gating the Register on a bid
    decision would invert the order the estimator works in and make the decision unmakeable."""

    def test_the_review_can_be_approved_with_no_bid_decision_in_hard_mode(self, hard, conn):
        cb_store.save_register(conn, cb_models.DepartureRegister(set_id=run_ref_for(SET)))
        cb_store.set_review_approved(conn, run_ref_for(SET), True)
        assert cb_store.review_is_approved(conn, run_ref_for(SET))

    def test_the_bid_brief_itself_is_readable_with_no_decision_in_hard_mode(self, hard):
        """You cannot be required to have decided in order to see the screen where you decide."""
        brief = bid.bid_brief(SET)
        assert brief["decision"] is None and brief["recommendation"]["verdict"]

    def test_recording_a_verdict_is_not_gated_by_the_verdict(self, hard):
        assert bid.confirm_bid(SET, bid.BID)["verdict"] == "bid"


class TestTheSeam:
    def test_the_gate_lives_beside_the_review_gate_not_scattered(self):
        """Both are called from the same two places — the proposal and the confirm — because
        confirming a route IS routing, and a gate covering only the advisory step is bypassed by
        posting straight to the act."""
        import inspect

        source = inspect.getsource(decisions)
        assert source.count("require_bid_to_proceed(conn, ref)") == 2
        assert source.count("require_approved_review(conn, ref)") == 2

    def test_both_exceptions_surface_as_409_on_the_same_two_endpoints(self):
        import inspect

        from bridge import router

        source = inspect.getsource(router)
        assert source.count(
            "except (decisions.ReviewNotApproved, decisions.BidNotDecided) as exc:") == 2

    def test_the_gate_never_writes_the_decision_it_reads(self, soft, conn):
        decisions.require_bid_to_proceed(conn, run_ref_for(SET))
        assert bid.load_bid_decision(SET) is None
