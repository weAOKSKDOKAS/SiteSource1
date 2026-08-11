"""An unconserved model warns, is recorded on the signature, and does not block.

WHAT HAPPENED. A probe of the shipped engine found HK$3,038,117.70 of direct cost that no bill item
recovered — eight bases with no claimant at all, carrying the site team, standing time, mobilisation,
setting out, sample tubes, core boxes and backfill grout between them — while `PricedBQ.unpriced` was
`[]` and `placeholders` was `[]`. Every honesty check the engine had came back clean, because they
all answer a different question: *is every BILL line priced?* A basis nothing claims is not a bill
line. It sits outside the bill entirely.

Cost that reaches no rate is not saved. General Preambles ¶6 — *"Items against which no rate is
entered shall be deemed to be covered by the other rates"* — gives it away for the life of a
remeasured contract.

THE DECISION, and it is a decision so it is stated. **Warn and record; never block.** A basis nothing
claims may genuinely not be required by this contract, and arithmetic cannot tell which — refusing a
correct tender would make the product wrong more often than the estimator is, and §0's standing rule
is to report-and-stop on a domain judgement rather than encode a guess. So the verdict goes in front
of the person signing, and is FROZEN onto the signature: an approval given over an unconserved model
becomes a fact on the record instead of a memory.

Frozen rather than looked up, for the same reason the letter is. The model moves after an approval,
and *was this tender conserved when it was approved* must not silently become *is it conserved now*.
"""

from __future__ import annotations

import sqlite3

import pytest

BASE = "/bridge"
SET = "technopole-gi"


@pytest.fixture
def client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    monkeypatch.setenv("DEMO_MODE", "true")
    db = tmp_path / "bridge.db"
    sqlite3.connect(str(db)).close()
    monkeypatch.setenv("SITESOURCE_DB", str(db))
    monkeypatch.setenv("SITESOURCE_WORKDIR", str(tmp_path / "workspace"))
    from api import app

    return TestClient(app)


class TestTheVerdictHasOneOwner:

    def test_the_sentence_comes_from_the_costing_engine_not_a_second_copy(self, client):
        """Three surfaces read this — the costing screen, the approval, and the workbook. Three
        implementations of one law is how two of them come to disagree."""
        import inspect

        from bridge import submission

        source = inspect.getsource(submission.conservation_verdict)
        assert "from client_boq.router import conservation_state" in source

    def test_a_tender_with_no_bill_says_the_check_could_not_run(self, client):
        from bridge.submission import conservation_sentence

        sentence = conservation_sentence("never-priced")
        assert "could not be run" in sentence
        assert sentence, "silence would read as a clean check"

    def test_it_never_raises(self, client):
        """An approval must not fail because a read-only check fell over."""
        from bridge.submission import conservation_sentence

        assert isinstance(conservation_sentence(""), str)
        assert isinstance(conservation_sentence("no-such-tender-at-all"), str)


class TestItReachesTheSignature:

    def test_an_approval_freezes_what_the_arithmetic_said(self, client):
        from bridge.submission import confirm_final_approval, load_final_approval

        confirm_final_approval(SET, "approve", approved_by="SW")
        approval = load_final_approval(SET)
        assert approval is not None
        assert "conservation" in approval
        assert approval["conservation"], "a verdict with no sentence reads as a clean one"

    def test_it_is_frozen_and_not_looked_up(self, client):
        """The stored string must not move when the model does. Written as a direct read of the
        column, because that is the property — not that the value is any particular sentence."""
        from bridge.identity import bridge_conn, run_ref_for
        from bridge.submission import confirm_final_approval, load_final_approval

        confirm_final_approval(SET, "approve", approved_by="SW")
        conn = bridge_conn()
        try:
            conn.execute(
                "UPDATE bridge_final_approvals SET conservation = ? WHERE set_id = ?",
                ("every basis balanced when this was signed", run_ref_for(SET)))
            conn.commit()
        finally:
            conn.close()
        assert load_final_approval(SET)["conservation"] == (
            "every basis balanced when this was signed")

    def test_re_approving_re_freezes_it(self, client):
        """Re-deciding replaces, and the frozen verdict is part of the decision — a stale sentence
        beside a fresh signature would be worse than none."""
        from bridge.identity import bridge_conn, run_ref_for
        from bridge.submission import confirm_final_approval, load_final_approval

        confirm_final_approval(SET, "approve", approved_by="SW")
        conn = bridge_conn()
        try:
            conn.execute("UPDATE bridge_final_approvals SET conservation = 'stale' WHERE set_id = ?",
                         (run_ref_for(SET),))
            conn.commit()
        finally:
            conn.close()
        confirm_final_approval(SET, "revise", "check the site team basis", approved_by="SW")
        assert load_final_approval(SET)["conservation"] != "stale"

    def test_the_live_verdict_is_on_the_offer_surface_too(self, client):
        """Both, deliberately: the frozen one says what was true when somebody signed, the live one
        says what is true now, and a model edited after approval is where they part company."""
        from bridge.submission import submission_state

        state = submission_state(SET)
        assert "conservation" in state
        assert isinstance(state["conservation"], str)
        assert "conservation_clean" in state

    def test_the_offer_endpoint_carries_it(self, client):
        response = client.get(f"{BASE}/{SET}/submission")
        assert response.status_code == 200, response.text
        assert "conservation" in response.json()


class TestItWarnsAndDoesNotBlock:

    def test_an_unconserved_tender_can_still_be_approved(self, client):
        """The decision, as an assertion. Refusing here would refuse a correct tender whenever a
        basis is genuinely not required by this contract, and arithmetic cannot tell which."""
        response = client.post(f"{BASE}/{SET}/final-approval",
                               json={"verdict": "approve", "rationale": ""})
        assert response.status_code == 200, response.text
        body = response.json()
        verdict = (body.get("approval") or body).get("verdict")
        assert verdict == "approve", body

    def test_the_submission_gate_is_still_the_approval_and_only_the_approval(self, client):
        """Conservation adds no second precondition. There is exactly one hard gate on the way out
        and it is the human signature — adding a silent arithmetic one would move the decision
        away from the person the whole design puts it with."""
        import inspect

        from bridge import submission

        source = inspect.getsource(submission.record_submission)
        assert "is_approved" in source
        assert "conservation" not in source.split('"""')[2], (
            "the submission must not gate on conservation")


class TestABlankVerdictNeverReadsAsAGoodOne:
    """Absence reading as health is this codebase's recurring failure. Not here."""

    def test_a_row_written_before_the_column_existed_reads_as_empty_not_clean(self, tmp_path,
                                                                             monkeypatch):
        monkeypatch.setenv("DEMO_MODE", "true")
        db = tmp_path / "old.db"
        old = sqlite3.connect(str(db))
        old.execute("""
            CREATE TABLE bridge_final_approvals (
                set_id TEXT PRIMARY KEY, verdict TEXT NOT NULL,
                rationale TEXT NOT NULL DEFAULT '', approved_by TEXT NOT NULL DEFAULT 'operator',
                approved_at TEXT NOT NULL)
        """)
        old.execute("INSERT INTO bridge_final_approvals VALUES ('t', 'approve', '', 'SW', 'then')")
        old.commit()
        old.close()

        conn = sqlite3.connect(str(db))
        conn.row_factory = sqlite3.Row
        from bridge.submission import _approval_row, ensure_final_approval_table

        ensure_final_approval_table(conn)
        columns = {row[1] for row in conn.execute("PRAGMA table_info(bridge_final_approvals)")}
        assert "conservation" in columns
        row = conn.execute("SELECT * FROM bridge_final_approvals").fetchone()
        assert _approval_row(row)["conservation"] == ""
        conn.close()

    def test_the_column_is_added_only_once(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DEMO_MODE", "true")
        db = tmp_path / "twice.db"
        conn = sqlite3.connect(str(db))
        conn.row_factory = sqlite3.Row
        from bridge.submission import ensure_final_approval_table

        ensure_final_approval_table(conn)
        ensure_final_approval_table(conn)
        columns = [row[1] for row in conn.execute("PRAGMA table_info(bridge_final_approvals)")]
        assert columns.count("conservation") == 1
        conn.close()

    def test_a_check_that_could_not_run_says_so_rather_than_nothing(self, client):
        from bridge.submission import conservation_sentence

        assert "could not be run" in conservation_sentence("a-tender-with-no-bill")


class TestThreeStatesNeverCollapseIntoTwo:
    """The sentence is non-empty on GOOD news too, so branching on it is a false alarm waiting."""

    def test_a_check_that_could_not_run_is_neither_clean_nor_dirty(self, client):
        from bridge.submission import conservation_verdict

        sentence, clean = conservation_verdict("a-tender-with-no-bill")
        assert clean is None, "None is 'we do not know', and it must not be False either"
        assert "could not be run" in sentence

    def test_the_flag_is_what_a_caller_branches_on(self, client):
        """`conservation_sentence` is for the frozen record and is always populated. A screen that
        branched on it being non-empty would print a red alarm over 'every basis balances'."""
        from bridge.submission import conservation_verdict

        sentence, clean = conservation_verdict(SET)
        assert isinstance(sentence, str) and sentence
        assert clean is None or isinstance(clean, bool)

    def test_a_model_that_computed_nothing_is_not_conserved(self, client):
        """`Conservation(bases=[])` had a difference of 0.00 and no miscounted rows, so it reported
        perfect conservation — this module's own failure, arriving through its own front door."""
        from client_boq.boq.conservation import Conservation

        empty = Conservation()
        assert empty.clean() is False
        assert "produced no bases at all" in empty.headline()
        assert "not a clean bill" in empty.headline()
