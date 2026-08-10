"""The assumptions register is editable, and a condition nobody had a field for has a home.

TWO THINGS THAT WERE MISSING, and the same reason under both.

**A register you can only sign goes stale.** Every row could be Accepted, Revised or Rejected, and
not one of them could be CHANGED — so somebody who disagreed with a number went and changed it
somewhere else, and the page of confirmations quietly stopped being about the model in force. Every
judgement row now names the model path it is about (``Assumption.edit_path``), typing on the row
writes THAT, and the programme, the rig curve, the group durations and every rate recompute from
it. One write path, and no number that lives only on a register.

**A condition with no field went in a notebook.** *"No night work through the village section"* is a
real thing about a real tender and the engine has no knob called that. Now it is a stored row, the
model PROPOSES which existing input it moves and by how much with its reasoning, and a person
confirms — and only the confirmation writes anything. An unmapped condition stays on the register,
visible and unpriced, because that is the honest state and it is the one that loses money if it is
hidden.

The red line is the same one this product keeps everywhere: the machine proposes with its evidence
named; a person decides; deterministic code writes.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from client_boq.boq import conditions as boq_conditions
from client_boq.boq.model import default_model
from client_boq.tests._bqfixture import build_bill_workbook

openpyxl = pytest.importorskip("openpyxl")

BASE = "/client-boq"
SET = "register-editable"


@pytest.fixture
def client(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setenv("SITESOURCE_WORKDIR", str(tmp_path / "workspace"))
    from api import app

    return TestClient(app)


@pytest.fixture
def imported(client, tmp_path):
    path = build_bill_workbook(tmp_path / "bq-0.xlsx", 0)
    with open(path, "rb") as handle:
        reply = client.post(
            f"{BASE}/boq/import", data={"set_id": SET},
            files={"file": (path.name, handle.read(),
                            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert reply.status_code == 200, reply.text
    return reply.json()


def _rows(client) -> dict:
    return {r["key"]: r for r in client.get(f"{BASE}/costing/{SET}").json()["register"]["rows"]}


class TestEveryJudgementRowNamesWhatItEdits:
    def test_the_judgement_rows_carry_a_path_and_the_derived_ones_do_not(self, client, imported):
        rows = _rows(client)
        for key in ("residual_site_factor", "calendar_ratio", "standing_allowance",
                    "supervision_ratio", "site_count", "site_team_per_site", "nec_fee"):
            assert rows[key]["edit_path"], f"{key} is a judgement with nowhere to type it"
        for key in ("rock_fraction", "rigs", "site_teams", "gfts", "band_rate"):
            assert not rows[key]["edit_path"], f"{key} is derived — typing over it invents a fact"

    def test_a_percentage_row_says_so_so_it_is_not_shown_as_a_tenth(self, client, imported):
        rows = _rows(client)
        assert rows["standing_allowance"]["edit_percent"] is True
        assert rows["nec_fee"]["edit_percent"] is True
        assert rows["site_count"]["edit_percent"] is False

    def test_a_markup_step_built_from_several_inputs_is_not_editable_from_one_box(self, client,
                                                                                  imported):
        """A step summing three overheads has no honest single number to write, so it names no
        path — rather than picking one of the three and being wrong quietly."""
        model = default_model()
        multi = [s.key for s in model.markup if len(s.components) > 1]
        rows = _rows(client)
        for key in multi:
            row = rows.get(f"markup_{key}")
            if row:
                assert not row["edit_path"]


class TestTypingOnTheRegisterMovesTheModel:
    def test_it_writes_the_input_and_the_row_reads_back_changed(self, client, imported):
        reply = client.post(f"{BASE}/costing/assumption-value",
                            json={"set_id": SET, "key": "supervision_ratio", "value": 3.0})
        assert reply.status_code == 200, reply.text
        body = reply.json()
        assert body["path"] == "inputs.gft_ratio"
        assert body["was"] == "6" and body["value"] == 3.0
        assert "3 rigs per GFT" in body["now"]
        assert client.get(f"{BASE}/costing/{SET}").json()["model"]["inputs"]["gft_ratio"] == 3.0

    def test_it_is_copy_on_write_so_the_library_does_not_move(self, client, imported):
        before = client.get(f"{BASE}/costing/model").json()["model"]["inputs"]["margin"]
        client.post(f"{BASE}/costing/assumption-value",
                    json={"set_id": SET, "key": "markup_margin", "value": 0.18})
        assert client.get(f"{BASE}/costing/model").json()["model"]["inputs"]["margin"] == before
        body = client.get(f"{BASE}/costing/{SET}").json()
        assert body["using_own_model"] is True
        assert body["model"]["inputs"]["margin"] == 0.18

    def test_the_whole_engine_recomputes_not_just_the_row(self, client, imported):
        """The point of one write path: change a judgement and the programme, the rig curve and the
        priced total all follow, because they were all derived from it in the first place."""
        before = client.get(f"{BASE}/costing/{SET}").json()
        reply = client.post(f"{BASE}/costing/assumption-value",
                            json={"set_id": SET, "key": "calendar_ratio", "value": 1.60}).json()

        assert "recomputed" in reply
        assert reply["recomputed"]["rigs_required"] >= before["programme"]["rigs_required"], (
            "a worse calendar ratio cannot need fewer rigs")
        assert reply["recomputed"]["proposal_n"] is not None, "the rig curve re-ran"

        after = client.get(f"{BASE}/costing/{SET}").json()
        assert after["programme"]["calendar_days"] > before["programme"]["calendar_days"]

    def test_a_percentage_row_is_written_as_the_fraction_the_model_stores(self, client, imported):
        client.post(f"{BASE}/costing/assumption-value",
                    json={"set_id": SET, "key": "standing_allowance", "value": 0.30})
        model = client.get(f"{BASE}/costing/{SET}").json()["model"]
        assert model["inputs"]["standing_allowance"] == 0.30

    def test_a_spread_rate_row_writes_the_spread_line(self, client, imported):
        """The GFT ships at rate 0 on purpose. This is where somebody enters their own number."""
        reply = client.post(f"{BASE}/costing/assumption-value",
                            json={"set_id": SET, "key": "gft_rate", "value": 4200.0}).json()
        assert reply["path"] == "spread.gft.rate"
        model = client.get(f"{BASE}/costing/{SET}").json()["model"]
        assert next(l for l in model["spread"] if l["key"] == "gft")["rate"] == 4200.0
        assert "4,200" in _rows(client)["gft_rate"]["value"]


class TestWhatItRefuses:
    def test_a_derived_row_is_refused_with_the_reason(self, client, imported):
        reply = client.post(f"{BASE}/costing/assumption-value",
                            json={"set_id": SET, "key": "rock_fraction", "value": 0.9})
        assert reply.status_code == 422
        assert "inventing a fact" in reply.json()["detail"]

    def test_a_caveat_row_with_no_single_number_is_refused(self, client, imported):
        reply = client.post(f"{BASE}/costing/assumption-value",
                            json={"set_id": SET, "key": "item_coverage", "value": 1.0})
        assert reply.status_code == 422
        assert "nothing here to write" in reply.json()["detail"]

    def test_an_unknown_row_is_a_404_not_a_silent_no_op(self, client, imported):
        reply = client.post(f"{BASE}/costing/assumption-value",
                            json={"set_id": SET, "key": "not-a-row", "value": 1.0})
        assert reply.status_code == 404

    def test_the_verdict_endpoint_still_only_writes_verdicts(self, client, imported):
        """Two different acts, two different endpoints. Signing a row must not move a number."""
        before = client.get(f"{BASE}/costing/{SET}").json()["model"]["inputs"]["residual_site_factor"]
        client.post(f"{BASE}/costing/assumption",
                    json={"set_id": SET, "key": "residual_site_factor", "status": "Accepted"})
        after = client.get(f"{BASE}/costing/{SET}").json()
        assert after["model"]["inputs"]["residual_site_factor"] == before
        assert _rows(client)["residual_site_factor"]["status"] == "Accepted"


class TestAConditionIsRecordedThenProposedThenConfirmed:
    def test_writing_one_down_records_it_and_proposes_a_mapping(self, client, imported):
        reply = client.post(f"{BASE}/costing/conditions", json={
            "set_id": SET,
            "text": "No night work or Sunday work through the village section.",
        })
        assert reply.status_code == 200, reply.text
        body = reply.json()

        assert body["condition"]["text"].startswith("No night work")
        assert body["condition"]["status"] == "", "recording is not deciding"
        assert body["condition"]["applied_value"] is None, "nothing written yet"
        assert body["proposal"]["path"] == "inputs.calendar_to_work_day"
        assert body["proposal"]["basis"], "a proposal states its reasoning or it is not one"
        assert "your confirmation" in body["awaiting"]
        # And the model has NOT moved.
        model = client.get(f"{BASE}/costing/{SET}").json()["model"]
        assert model["inputs"]["calendar_to_work_day"] == 1.18

    def test_confirming_is_the_only_thing_that_writes(self, client, imported):
        made = client.post(f"{BASE}/costing/conditions", json={
            "set_id": SET,
            "text": "No night work or Sunday work through the village section.",
        }).json()
        cid = made["condition"]["condition_id"]

        decided = client.post(f"{BASE}/costing/conditions/decide",
                              json={"set_id": SET, "condition_id": cid, "status": "confirmed"},
                              headers={"X-CBOQ-Actor": "SW"})
        assert decided.status_code == 200, decided.text
        assert decided.json()["applied"] == 1.35
        assert decided.json()["condition"]["decided_by"] == "SW", "a name against the decision"

        model = client.get(f"{BASE}/costing/{SET}").json()["model"]
        assert model["inputs"]["calendar_to_work_day"] == 1.35

    def test_a_person_may_confirm_a_different_number_than_the_one_proposed(self, client, imported):
        made = client.post(f"{BASE}/costing/conditions", json={
            "set_id": SET, "text": "No night work through the village section."}).json()
        cid = made["condition"]["condition_id"]
        client.post(f"{BASE}/costing/conditions/decide",
                    json={"set_id": SET, "condition_id": cid, "status": "confirmed", "value": 1.45})

        model = client.get(f"{BASE}/costing/{SET}").json()["model"]
        assert model["inputs"]["calendar_to_work_day"] == 1.45, "the person's number, not the machine's"

    def test_rejecting_writes_nothing_and_keeps_the_condition_visible(self, client, imported):
        made = client.post(f"{BASE}/costing/conditions", json={
            "set_id": SET, "text": "No night work through the village section."}).json()
        cid = made["condition"]["condition_id"]
        client.post(f"{BASE}/costing/conditions/decide",
                    json={"set_id": SET, "condition_id": cid, "status": "rejected"})

        model = client.get(f"{BASE}/costing/{SET}").json()["model"]
        assert model["inputs"]["calendar_to_work_day"] == 1.18
        listed = client.get(f"{BASE}/costing/{SET}/conditions").json()
        row = next(c for c in listed["conditions"] if c["condition_id"] == cid)
        assert row["status"] == "rejected"
        assert row["applied_value"] is None

    def test_a_condition_can_be_written_before_a_bill_exists(self, client):
        """A condition arrives when somebody reads the tender, which is before any spreadsheet.
        Refusing to record it because a bill has not been imported puts it back in a notebook."""
        reply = client.post(f"{BASE}/costing/conditions",
                            json={"set_id": "no-bill-here", "text": "Two holes are over water."})
        assert reply.status_code == 200, reply.text
        assert reply.json()["condition"]["text"] == "Two holes are over water."

    def test_deleting_says_plainly_that_it_does_not_unwind_the_number(self, client, imported):
        made = client.post(f"{BASE}/costing/conditions", json={
            "set_id": SET, "text": "No night work through the village section."}).json()
        cid = made["condition"]["condition_id"]
        client.post(f"{BASE}/costing/conditions/decide",
                    json={"set_id": SET, "condition_id": cid, "status": "confirmed"})

        gone = client.delete(f"{BASE}/costing/{SET}/conditions/{cid}").json()
        assert "NOT reverted" in gone["note"]
        model = client.get(f"{BASE}/costing/{SET}").json()["model"]
        assert model["inputs"]["calendar_to_work_day"] == 1.35, "still the model's number"


class TestTheProposalCannotSayMoreThanItIsAllowedTo:
    def test_the_proposal_type_has_no_status_and_no_applied_field(self):
        """Structurally, not by habit — the same guard DepartureProposal and PlannedSplit carry."""
        fields = set(boq_conditions.ConditionProposal.model_fields)
        assert "status" not in fields and "applied" not in fields and "confirmed" not in fields

    def test_a_path_the_model_does_not_have_is_refused_before_anybody_sees_it(self):
        proposal = boq_conditions.validate(
            {"path": "inputs.night_work_allowance", "value": 2.0, "basis": "…"}, default_model())
        assert proposal.path == "" and not proposal.maps
        assert any("REFUSED" in c for c in proposal.checked)
        assert "does not exist" in proposal.cannot_map

    def test_a_path_with_no_usable_number_is_treated_as_unmapped(self):
        proposal = boq_conditions.validate(
            {"path": "inputs.margin", "value": "quite a lot"}, default_model())
        assert not proposal.maps
        assert any("nothing to confirm" in c for c in proposal.checked)

    def test_declining_to_map_is_a_correct_answer_not_a_failure(self):
        proposal = boq_conditions.validate(
            {"path": "", "cannot_map": "this is a programme wish, not a rate"}, default_model())
        assert not proposal.maps
        assert proposal.cannot_map == "this is a programme wish, not a rate"
        assert not any("REFUSED" in c for c in proposal.checked)

    def test_a_wild_value_is_flagged_and_still_shown(self):
        """Not refused — a condition really can triple a number. Read twice, then decide."""
        proposal = boq_conditions.validate(
            {"path": "inputs.calendar_to_work_day", "value": 9.0, "basis": "…"}, default_model())
        assert proposal.maps
        assert any("three times" in c for c in proposal.checked)

    def test_the_prompt_carries_the_models_own_inputs_and_never_a_typed_list(self):
        model = default_model()
        prompt = boq_conditions.prompt_for("no night work", model)
        for key in ("inputs.calendar_to_work_day", "inputs.gft_ratio", "inputs.margin"):
            assert key in prompt
        assert "1.18" in prompt, "the CURRENT value, so a proposal is a change from something"

    def test_only_declared_scalars_are_mappable(self):
        """A condition must not talk the model into a spread RATE — that is a number somebody
        should change deliberately with the rate in front of them."""
        paths = boq_conditions.editable_paths(default_model())
        assert all(p.startswith("inputs.") for p in paths)
        assert "spread.gft.rate" not in paths
