"""The bid brief: navy signals with their sources, and a brass rule that shows its reasons.

THE LINE THIS FILE DEFENDS, in three parts.

**Nothing is computed for this screen.** Every signal is a deterministic read of an artifact that
already exists — the review's approval flag, the register's own lines, the close date, the open
questions, the coverage lists. A bid screen's natural temptation is a win-probability, a capacity
score, a strategic-fit score; those are the three numbers this machine has no basis for, and a
fabricated one would arrive in the same typeface as the real counts beside it.

**Unknown says "unknown".** A close date whose status is `reading` or `not_found` is not a
deadline — the same rule `submission.deadline_for` already applies to `on_time`, for the identical
reason. Coverage before a bill is imported is unknown rather than zero, because "0 bills without a
list" would be true and useless.

**The rule never proposes `no_bid`.** It can say "we cannot price this yet" and "nothing is in the
way". Declining a tender is a judgement about workload, relationship and risk appetite, none of
which is in this database.
"""

from __future__ import annotations

import datetime as _dt

import pytest

from bridge import bid
from bridge.identity import bridge_conn, run_ref_for
from client_boq import models as cb_models
from client_boq import store as cb_store

SET = "bid-brief-test"


@pytest.fixture
def conn():
    handle = bridge_conn()
    try:
        yield handle
    finally:
        handle.close()


def _register(*items: cb_models.DepartureItem) -> cb_models.DepartureRegister:
    return cb_models.DepartureRegister(set_id=run_ref_for(SET), items=list(items))


def _meta(conn, **fields):
    cb_store.upsert_set_meta(conn, run_ref_for(SET), **fields)


def _line(**kw) -> cb_models.DepartureItem:
    return cb_models.DepartureItem(**{"item": 1, "status": cb_models.STATUS_CANDIDATE, **kw})


def _save(conn, register, *, approved=False):
    cb_store.save_register(conn, register)
    cb_store.set_review_approved(conn, run_ref_for(SET), approved)


# ---------------------------------------------------------------------------
# The rule — exercised directly, so each trigger is isolated from the others
# ---------------------------------------------------------------------------
def _signals(**over) -> dict:
    base = {
        "open_clarifications": {"count": 0},
        "review_approved": {"value": True},
        "departures": {"total": 0, "unresolved": 0},
        "scope_gaps": {"gaps": 0, "inputs_missing": 0},
        "coverage": {"bills_without_list": [], "waiting": 0},
        "deadline": {"days_remaining": 30},
    }
    base.update(over)
    return base


class TestTheRule:
    def test_a_clean_brief_recommends_bid(self):
        out = bid.recommend(_signals())
        assert out["verdict"] == "bid"
        assert out["reasons"], "a recommendation with no visible reasons is an opinion"

    def test_open_clarifications_alone_trigger_clarify(self):
        out = bid.recommend(_signals(open_clarifications={"count": 3}))
        assert out["verdict"] == "clarify"
        assert any("3 clarification(s)" in r for r in out["reasons"])

    def test_missing_inputs_alone_trigger_clarify(self):
        out = bid.recommend(_signals(scope_gaps={"gaps": 0, "inputs_missing": 2}))
        assert out["verdict"] == "clarify"
        assert any("2 input(s) the contract did not give us" in r for r in out["reasons"])

    def test_scope_gaps_alone_trigger_clarify(self):
        out = bid.recommend(_signals(scope_gaps={"gaps": 4, "inputs_missing": 0}))
        assert out["verdict"] == "clarify"
        assert any("4 scope-alignment finding(s)" in r for r in out["reasons"])

    def test_an_unapproved_review_alone_triggers_clarify(self):
        out = bid.recommend(_signals(review_approved={"value": False}))
        assert out["verdict"] == "clarify"
        assert out["reasons"] == ["the review register is not approved"]
        assert "terms nobody has read" in out["basis"]

    def test_every_reason_names_the_signal_that_produced_it(self):
        out = bid.recommend(_signals(open_clarifications={"count": 1},
                                     scope_gaps={"gaps": 2, "inputs_missing": 1}))
        assert len(out["reasons"]) == 3, "three signals fired, three reasons"

    def test_the_rule_never_recommends_no_bid(self):
        """Declining a tender is a judgement about workload, relationship and risk appetite — none
        of which is in this database. No combination of signals may propose it."""
        for over in (
            {"open_clarifications": {"count": 99}},
            {"scope_gaps": {"gaps": 99, "inputs_missing": 99}},
            {"review_approved": {"value": False}},
            {"deadline": {"days_remaining": -30}},
            {"coverage": {"bills_without_list": ["1", "4", "7"], "waiting": 40}},
            {"departures": {"total": 500, "unresolved": 500}},
        ):
            assert bid.recommend(_signals(**over))["verdict"] != "no_bid", over

    def test_a_tight_deadline_is_reported_but_does_not_drive_the_verdict(self):
        """A deadline is a capacity question and capacity is the estimator's. The signal is on the
        brief; it is not a reason a machine should propose pausing."""
        assert bid.recommend(_signals(deadline={"days_remaining": 1}))["verdict"] == "bid"

    def test_missing_coverage_is_reported_but_does_not_drive_the_verdict(self):
        out = bid.recommend(_signals(coverage={"bills_without_list": ["1", "7"], "waiting": 12}))
        assert out["verdict"] == "bid", "a completeness risk to weigh, not a reason to pause"

    def test_the_bid_basis_says_the_pursuit_decision_is_still_the_humans(self):
        assert "never proposes no-bid" in bid.recommend(_signals())["basis"]


# ---------------------------------------------------------------------------
# The signals — read against the REAL shapes the stages write
# ---------------------------------------------------------------------------
class TestTheSignals:
    def test_the_register_supplies_both_the_departures_and_the_scope_gaps(self, conn):
        """Scope alignment has no store of its own: s04's findings are assembled INTO the register
        tagged `source='scope_alignment'`, so both signals are one read of one artifact — which is
        also why neither can drift from what the Register tab shows."""
        _save(conn, _register(
            _line(item=1, source=cb_models.SOURCE_CRITERIA),
            _line(item=2, source=cb_models.SOURCE_CRITERIA, status=cb_models.STATUS_CONFIRMED),
            _line(item=3, source=cb_models.SOURCE_SCOPE_ALIGNMENT, kind="precedence"),
            _line(item=4, source=cb_models.SOURCE_SCOPE_ALIGNMENT, kind="input_missing"),
        ))
        signals = bid.signals_for(SET)

        assert signals["departures"]["total"] == 4
        assert signals["departures"]["unresolved"] == 3, "the confirmed one has been ruled on"
        assert signals["scope_gaps"]["gaps"] == 2
        assert signals["scope_gaps"]["inputs_missing"] == 1

    def test_a_ruled_on_line_is_not_counted_as_unresolved(self, conn):
        _save(conn, _register(
            _line(item=1, status=cb_models.STATUS_CONFIRMED),
            _line(item=2, status=cb_models.STATUS_DISMISSED),
        ))
        assert bid.signals_for(SET)["departures"]["unresolved"] == 0

    def test_every_signal_names_where_it_came_from(self, conn):
        _save(conn, _register())
        for key, block in bid.signals_for(SET).items():
            assert block.get("source"), key

    def test_the_review_flag_is_read_from_the_authoritative_column(self, conn):
        _save(conn, _register(), approved=False)
        assert bid.signals_for(SET)["review_approved"]["value"] is False
        _save(conn, _register(), approved=True)
        assert bid.signals_for(SET)["review_approved"]["value"] is True

    def test_a_tender_with_no_register_reports_unknown_and_says_why(self, conn):
        """RE-ANCHORED 2026-08-11, disclosed: the pinned behaviour is deliberately changing.

        This asserted `total == 0` with a source of "no review register yet". Zero is what a
        register that WAS read and came out clean reports, and on the screen where bid or no-bid is
        decided the two rendered identically — `warn` false, ordinary tone, only a 7.5px source line
        distinguishing them. The two neighbouring signals in this same function
        (`_deadline_signal`, `_coverage_signal`) already return the UNKNOWN sentinel plus a
        `why_unknown` sentence; this one did not. It does now, which is why the assertion moves.
        """
        signals = bid.signals_for("bid-brief-nothing-run")
        assert signals["departures"]["total"] == "unknown"
        assert signals["departures"]["unresolved"] == "unknown"
        assert signals["scope_gaps"]["gaps"] == "unknown"
        assert "no review register has been assembled" in signals["departures"]["why_unknown"]
        assert "the review register" in signals["departures"]["source"]


class TestUnknownSaysUnknown:
    def test_a_close_date_nobody_confirmed_is_not_a_deadline(self, conn):
        """The SAME honesty rule `submission.deadline_for` applies to `on_time`. `reading` and
        `not_found` both mean "we do not have one"."""
        _meta(conn, close_date="2026-09-30", close_date_status="not_found")
        deadline = bid.signals_for(SET)["deadline"]
        assert deadline["days_remaining"] == "unknown"
        assert deadline["close_date"] == "unknown"
        # RE-ANCHORED IN THE OPEN: this pinned the raw enum ("'not_found'") in a sentence shown to
        # the estimator. The claim is unchanged — the reason is stated — but stated in words:
        assert "no close date was found in the pack" in deadline["why_unknown"]
        assert "A date nobody read is not a deadline" in deadline["why_unknown"]

    def test_a_confirmed_close_date_gives_a_real_count(self, conn):
        due = (_dt.date.today() + _dt.timedelta(days=21)).isoformat()
        _meta(conn, close_date=due, close_date_status="confirmed")
        deadline = bid.signals_for(SET)["deadline"]
        assert deadline["days_remaining"] == 21
        assert "found in the pack or confirmed" in deadline["source"]

    def test_a_found_close_date_is_trusted_too(self, conn):
        due = (_dt.date.today() + _dt.timedelta(days=5)).isoformat()
        _meta(conn, close_date=due, close_date_status="found")
        assert bid.signals_for(SET)["deadline"]["days_remaining"] == 5

    def test_a_stored_date_that_will_not_parse_degrades_to_unknown(self, conn):
        _meta(conn, close_date="next Tuesday", close_date_status="confirmed")
        deadline = bid.signals_for(SET)["deadline"]
        assert deadline["days_remaining"] == "unknown"
        assert "not a date this can read" in deadline["why_unknown"]

    def test_coverage_before_a_bill_is_unknown_rather_than_zero(self, conn):
        """"0 bills without a list" would be true and useless — coverage is per bill item, so with
        no bill there is nothing to have coverage OF."""
        coverage = bid.signals_for("bid-brief-no-bill-yet")["coverage"]
        assert coverage["bills_without_list"] == "unknown"
        assert coverage["waiting"] == "unknown"
        assert "nothing to have item coverage of" in coverage["why_unknown"]


class TestTheBriefAsAWhole:
    def test_it_carries_signals_a_recommendation_and_the_decision(self, conn):
        _save(conn, _register(), approved=True)
        brief = bid.bid_brief(SET)
        assert set(brief) == {"set_id", "signals", "recommendation", "decision"}
        assert brief["decision"] is None, "not yet decided is a state"

    def test_opening_the_brief_records_nothing(self, conn):
        _save(conn, _register(), approved=True)
        bid.bid_brief(SET)
        assert bid.load_bid_decision(SET) is None, "the machine assembles; it never decides"

    def test_the_human_verdict_appears_on_the_brief_once_recorded(self, conn):
        _save(conn, _register(), approved=True)
        bid.confirm_bid(SET, bid.NO_BID, "no rigs free in that window", decided_by="SW")
        brief = bid.bid_brief(SET)

        assert brief["decision"]["verdict"] == "no_bid"
        assert brief["recommendation"]["verdict"] != "no_bid", (
            "the rule still says what it says — the human overrode it, and both are visible")

    def test_the_brief_keys_on_run_ref(self, conn):
        assert bid.bid_brief(SET)["set_id"] == run_ref_for(SET)
