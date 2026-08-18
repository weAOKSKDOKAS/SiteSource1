"""Three ways to say "0 findings", and only one of them is the truth.

WHAT THE OWNER SAW, on a real tender with 206 parts, an approved manifest, a register and a bill:

    Reads — legal: 0 finding(s) · scope: 0 · site: 0 · costing: 0
    PROPOSED NEXT ACTIONS — It proposed nothing, which is itself information.

It is not information, because that screen is what ALL THREE of these look like:

1. the reads ran over real content and the tender is genuinely clean;
2. the reads ran over almost nothing — the slices carry the tender's name and the gate sentences
   whatever state the tender is in, so a `site` read on a tender with no take-off was handed ONE
   line, the project title, and cost a full call to come back empty;
3. the model answered WELL, in the wrong shape — `{"actions": [...]}` instead of
   `{"proposed_actions": [...]}` — and pydantic's default `extra="ignore"` deleted it before
   anything could notice. Empty lists, empty `stripped`, no error, full price.

The third is the one that matters, because it is indistinguishable from the first and it defeats
this module's own stated defence: "an invented action reads exactly like a real one, and the only
defence is saying one was removed". Something removed has to be SAID, whatever removed it.

WHAT WAS PROBABLY CAUSING IT. Neither prompt named a single JSON key, or asked for JSON at all,
while the reply was parsed with `model_validate_json` — `boq/ask.py` next door has always printed
its object out in full. Prose fails validation and burns the corrective retry at double cost; a
plausible reply under a different key fails silently, which is worse.

So: both prompts now print their object, extras are KEPT so they can be named, and the receipt
counts what went IN as well as what came out.
"""

from __future__ import annotations

import json

import pytest

from client_boq import brain
from client_boq.boq.ask import Ground


def _ground(**sources) -> Ground:
    ground = Ground()
    ground.sources = dict(sources)
    return ground


class TestAnAnswerInTheWrongShapeIsNamed:
    def test_actions_under_the_wrong_key_are_reported_not_silently_dropped(self):
        """The exact failure: the model proposed things, and the screen said it proposed nothing."""
        raw = brain.RawBriefing.model_validate_json(json.dumps({
            "understanding": "the tender is at the price",
            "actions": [{"action_id": "decide_bid", "reasoning": "the terms are read"}],
        }))
        briefing = brain.validate(raw.model_dump(), _ground(tender="ND/2025/04"))

        assert briefing.actions == [], "an unregistered shape still proposes nothing — correct"
        assert any("'actions'" in line for line in briefing.stripped), (
            "but it must SAY the key was there. Silence here is the one failure mode that looks "
            "exactly like an honest empty answer.")
        assert any("wrong shape rather than finding nothing" in line
                   for line in briefing.stripped)

    def test_the_extras_survive_validation_so_they_can_be_named(self):
        """`extra="allow"` is the opposite of loosening the type: the model still has nowhere to
        put a verdict, and an unknown key now reaches the doorman instead of being deleted."""
        raw = brain.RawBriefing.model_validate_json(json.dumps({"whatever": [1, 2]}))
        assert "whatever" in raw.model_dump()

    def test_a_genuinely_empty_answer_reports_nothing_stripped(self):
        """The honest zero has to stay clean, or the new line is just noise on every briefing."""
        raw = brain.RawBriefing.model_validate_json(json.dumps(
            {"understanding": "nothing to report", "proposed_actions": []}))
        briefing = brain.validate(raw.model_dump(), _ground(tender="X"))
        assert briefing.stripped == []

    def test_the_model_still_has_nowhere_to_write_a_verdict(self):
        """The structural guard must survive the change — extras are reported, never USED."""
        raw = brain.RawBriefing.model_validate_json(json.dumps({
            "understanding": "",
            "approved": True, "verdict": "confirmed", "rate": 1234.5,
        }))
        briefing = brain.validate(raw.model_dump(), _ground(tender="X"))
        dumped = briefing.model_dump()
        for forbidden in ("approved", "verdict", "rate"):
            assert forbidden not in dumped
        assert len(briefing.stripped) == 3, "each one named"


class TestBothPromptsSayWhatShapeToAnswerIn:
    def test_the_read_prompt_prints_its_keys(self):
        assert "Answer with JSON only" in brain.READ_SYSTEM
        assert '"findings"' in brain.READ_SYSTEM and '"citations"' in brain.READ_SYSTEM

    def test_the_synthesis_prompt_prints_its_keys(self):
        assert "Answer with JSON only" in brain.SYNTH_SYSTEM
        for key in ("understanding", "disagreements", "cannot_assess", "proposed_actions"):
            assert f'"{key}"' in brain.SYNTH_SYSTEM

    def test_every_key_named_in_a_prompt_is_a_real_field(self):
        """A prompt that asks for a key the type does not have manufactures the very defect
        above, from the other end."""
        for key in ("understanding", "disagreements", "cannot_assess", "proposed_actions"):
            assert key in brain.RawBriefing.model_fields
        for key in ("findings", "citations"):
            assert key in brain.RawFindings.model_fields

    def test_the_read_prompt_says_empty_is_a_correct_answer(self):
        """Or a model under pressure to produce something will produce something."""
        assert "That is a correct answer" in brain.READ_SYSTEM


class TestScaffoldingIsNotContent:
    def test_the_tender_name_and_the_gates_do_not_count_as_something_to_read(self):
        """Every slice carries these whatever state the tender is in. Counting them is what made
        the old empty-slice guard dead code — five model calls always fired."""
        ground = _ground(**{"tender": "ND/2025/04", "gate:manifest": "not approved",
                            "gate:review": "not approved"})
        assert brain.substantive_sources(ground) == []

    def test_real_content_counts(self):
        ground = _ground(**{"tender": "X", "gate:review": "y", "register: cl 8.3": "LDs uncapped"})
        assert brain.substantive_sources(ground) == ["register: cl 8.3"]

    def test_every_slice_can_say_what_it_is_waiting_for(self):
        """A skipped read has to explain itself. Reporting "0 findings" about a read that never
        happened is the claim this whole file exists to stop."""
        assert set(brain.SLICE_NEEDS) == set(brain.READ_SLICES)
        for name, need in brain.SLICE_NEEDS.items():
            assert need and not need.endswith("."), f"{name} reads mid-sentence"


class TestTheEndpointReceipt:
    @pytest.fixture
    def client(self, tmp_path, monkeypatch):
        from fastapi.testclient import TestClient
        monkeypatch.setenv("SITESOURCE_WORKDIR", str(tmp_path / "ws"))
        from api import app
        return TestClient(app)

    def test_a_tender_with_nothing_read_still_refuses_to_run(self, client):
        """Unchanged, and worth pinning beside the rest: the cheapest honest answer to an empty
        tender is not to spend five model calls on it."""
        reply = client.post("/client-boq/brain/run", json={"set_id": "nothing-here"})
        assert reply.status_code == 409
        assert "nothing has been read" in reply.json()["detail"]
