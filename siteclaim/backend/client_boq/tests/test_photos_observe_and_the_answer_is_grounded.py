"""Site photographs are OBSERVED, and a question about a tender is answered from its own ground.

Two surfaces with the same red line under them, enforced by SHAPE rather than by asking nicely.

**A photograph produces observations, never a classification.** `Observation` has no
`access_class`, no `cost`, no `status`. A machine looking at a picture of a hillside cannot tell
you it is Class B, and if it said so it would be believed. What it can do is say what is visible
and name the photograph — and an observation that names no photograph in the set is DROPPED and the
drop is reported, because an observation nobody can go back and check is exactly the confident
sentence this product exists to keep out of an estimate.

**A chat box is the front door for a made-up rate.** Ask a language model what to price rock
drilling at and it will answer, fluently, in the same typeface as the numbers the engine computed.
So `Answer` has no field for a rate, a duration, a class or a verdict: it may QUOTE a figure it was
given (by key, so a reader can see which), it may cite a source it was given, and a citation naming
something that was never supplied is stripped and reported. There is nowhere to put the other kind
of answer.

The chain a photograph travels is six steps with a human at two of them:
photo → observation → a person keeps it → condition → proposal → a person confirms → the model moves.
"""

from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient

from client_boq.boq import ask as boq_ask
from client_boq.boq import photos as boq_photos

BASE = "/client-boq"
SET = "photos-and-answers"

# A one-pixel PNG. The reading path is fixture-backed in DEMO; what these tests exercise is the
# upload, the index, the validation and the refusals — not a vision model.
PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000a49444154789c6360000002000100" "05fe02fe" "a7d5c8590000000049454e44ae426082")


@pytest.fixture
def client(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setenv("SITESOURCE_WORKDIR", str(tmp_path / "workspace"))
    from api import app

    return TestClient(app)


def _upload(client, name="site-01.jpg", caption="", station="") -> dict:
    reply = client.post(
        f"{BASE}/site/photos",
        data={"set_id": SET, "caption": caption, "station": station},
        files={"file": (name, io.BytesIO(PNG), "image/png")},
        headers={"X-CBOQ-Actor": "SW"})
    assert reply.status_code == 200, reply.text
    return reply.json()["photo"]


class TestUploadingAPhotograph:
    def test_it_is_indexed_with_who_and_when_and_can_be_read_back(self, client):
        photo = _upload(client, caption="track ends at the gate", station="BH14")
        assert photo["caption"] == "track ends at the gate"
        assert photo["station"] == "BH14"
        assert photo["uploaded_by"] == "SW" and photo["uploaded_at"]

        listed = client.get(f"{BASE}/site/{SET}/photos").json()
        assert listed["count"] == 1

        blob = client.get(f"{BASE}/site/{SET}/photos/{photo['photo_id']}/file")
        assert blob.status_code == 200 and blob.content == PNG

    def test_the_station_is_the_photographers_and_is_never_read_off_the_image(self, client):
        """A model guessing which hole a picture is of would attach real evidence to the wrong
        location, which is worse than a picture with no location at all."""
        photo = _upload(client, name="unlabelled.jpg")
        assert photo["station"] == "", "nothing invented one"

    def test_a_document_is_refused_with_the_reason(self, client):
        reply = client.post(
            f"{BASE}/site/photos", data={"set_id": SET},
            files={"file": ("spec.pdf", io.BytesIO(b"%PDF-1.4"), "application/pdf")})
        assert reply.status_code == 422
        assert "not an image" in reply.json()["detail"]
        assert "Documents step" in reply.json()["detail"]

    def test_an_empty_file_is_refused(self, client):
        reply = client.post(f"{BASE}/site/photos", data={"set_id": SET},
                            files={"file": ("x.jpg", io.BytesIO(b""), "image/jpeg")})
        assert reply.status_code == 422

    def test_deleting_says_a_condition_already_recorded_stays(self, client):
        photo = _upload(client)
        gone = client.delete(f"{BASE}/site/{SET}/photos/{photo['photo_id']}").json()
        assert "stays" in gone["note"]
        assert client.get(f"{BASE}/site/{SET}/photos").json()["count"] == 0


class TestReadingThem:
    def test_with_no_photographs_it_says_so_rather_than_returning_a_fixture(self, client):
        """THE DEGRADATION RULE. `s02_interpret` once returned its fixture before checking whether
        the input was readable, so a scanned page came back with a confident summary of pages
        nobody had seen. The images are counted FIRST, in every mode."""
        body = client.post(f"{BASE}/site/photos-nothing-uploaded/photos/read").json()
        assert body["observations"] == []
        assert "no photographs have been uploaded" in body["waiting_on"]

    def test_observations_come_back_attributed_to_the_photographs(self, client):
        _upload(client, name="site-01.jpg")
        _upload(client, name="site-02.jpg")
        body = client.post(f"{BASE}/site/{SET}/photos/read").json()

        assert body["photos_read"] == ["site-01.jpg", "site-02.jpg"]
        assert body["observations"], "the fixture has three"
        for observation in body["observations"]:
            assert observation["photo_refs"], "an observation you cannot attribute is not one"
            assert set(observation["photo_refs"]) <= set(body["photos_read"])
            assert observation["topic"] in boq_photos.TOPICS

    def test_no_observation_can_carry_a_class_or_a_cost(self):
        fields = set(boq_photos.Observation.model_fields)
        for forbidden in ("access_class", "cost", "rate", "status", "days", "quantity"):
            assert forbidden not in fields

    def test_each_observation_arrives_with_the_sentence_it_would_become(self, client):
        _upload(client, name="site-01.jpg")
        body = client.post(f"{BASE}/site/{SET}/photos/read").json()
        first = body["observations"][0]
        assert first["as_condition"].startswith(first["what_i_see"].rstrip("."))
        assert "[Seen in site-01.jpg" in first["as_condition"], "the evidence travels with it"

    def test_what_the_photographs_do_not_show_is_reported(self, client):
        _upload(client, name="site-01.jpg")
        body = client.post(f"{BASE}/site/{SET}/photos/read").json()
        assert "No photograph shows" in body["could_not_see"]


class TestWhatTheReadingRefusesToKeep:
    def test_an_observation_naming_no_photograph_in_the_set_is_dropped_and_said(self):
        read = boq_photos.validate({"observations": [
            {"topic": "access", "what_i_see": "the track is washed out",
             "photo_refs": ["a-photo-nobody-uploaded.jpg"]},
            {"topic": "ground", "what_i_see": "granite outcrop", "photo_refs": ["site-01.jpg"]},
        ]}, available=["site-01.jpg"])

        assert len(read.observations) == 1
        assert read.observations[0].what_i_see == "granite outcrop"
        assert any("DROPPED" in p for p in read.problems)
        assert any("cannot attribute" in p for p in read.problems)

    def test_an_unknown_topic_lands_in_other_rather_than_being_dropped(self):
        read = boq_photos.validate({"observations": [
            {"topic": "vibes", "what_i_see": "something", "photo_refs": ["p.jpg"]}]},
            available=["p.jpg"])
        assert read.observations[0].topic == boq_photos.TOPIC_OTHER

    def test_an_observation_with_nothing_said_about_the_image_is_dropped(self):
        read = boq_photos.validate({"observations": [
            {"topic": "access", "what_i_see": "  ", "photo_refs": ["p.jpg"]}]},
            available=["p.jpg"])
        assert not read.observations and read.problems

    def test_an_indexed_photograph_whose_file_is_gone_is_named_not_ignored(self, client, tmp_path):
        photo = _upload(client, name="site-01.jpg")
        _upload(client, name="site-02.jpg")
        from pipeline.workspace import Workspace

        (Workspace().docs_dir(SET) / photo["rel_path"]).unlink()
        body = client.post(f"{BASE}/site/{SET}/photos/read").json()
        assert any("files are gone" in p for p in body["problems"])
        assert "site-01.jpg" not in body["photos_read"]


class TestAskingAboutATender:
    def test_with_nothing_read_it_says_there_is_no_ground(self, client):
        body = client.post(f"{BASE}/costing/ask",
                           json={"set_id": "never-touched", "question": "how deep are the holes?"})
        assert body.status_code == 200
        assert body.json()["cannot_answer"]
        assert body.json()["citations"] == []

    def test_an_empty_question_is_refused(self, client):
        reply = client.post(f"{BASE}/costing/ask", json={"set_id": SET, "question": "   "})
        assert reply.status_code == 422

    def test_a_photograph_caption_becomes_ground_an_answer_can_cite(self, client):
        _upload(client, name="site-01.jpg", caption="the track ends at a locked gate")
        body = client.post(f"{BASE}/costing/ask",
                           json={"set_id": SET, "question": "what did we see on the walk?"}).json()
        assert "photo:site-01.jpg" in body["grounded_in"]


class TestTheAnswerCannotSayMoreThanItWasGiven:
    def test_it_has_no_field_for_a_rate_a_class_or_a_verdict(self):
        fields = set(boq_ask.Answer.model_fields)
        for forbidden in ("rate", "price", "access_class", "status", "verdict", "decision",
                          "work_days"):
            assert forbidden not in fields

    def test_a_citation_to_a_source_that_was_never_supplied_is_stripped_and_reported(self):
        """The failure mode that matters: a fabricated citation reads exactly like a real one, and
        it is how a model's own knowledge gets laundered into a tender file."""
        ground = boq_ask.Ground(sources={"programme": "…"})
        answer = boq_ask.validate({
            "answer": "…",
            "citations": [{"source": "programme", "quote": "a"},
                          {"source": "BS 5930:2015 §4.2", "quote": "b"}],
        }, ground)

        assert [c.source for c in answer.citations] == ["programme"]
        assert any("STRIPPED" in s and "BS 5930" in s for s in answer.stripped)

    def test_a_figure_the_engine_did_not_compute_is_stripped_and_the_prose_is_flagged(self):
        ground = boq_ask.Ground(sources={"programme": "…"}, figures={"work_days": "1,046"})
        answer = boq_ask.validate({
            "answer": "…", "citations": [{"source": "programme", "quote": "a"}],
            "figures_used": ["work_days", "rock_drilling_rate"],
        }, ground)

        assert answer.figures_used == ["work_days"]
        assert any("rock_drilling_rate" in s for s in answer.stripped)
        assert any("the model's, not this tender's" in s for s in answer.stripped)

    def test_an_answer_with_no_citation_is_marked_as_not_a_finding(self):
        answer = boq_ask.validate({"answer": "Rock drilling usually runs about 2.5 m a day."},
                                  boq_ask.Ground(sources={"programme": "…"}))
        assert answer.not_grounded_in_anything
        assert "suggestion rather than a finding" in answer.cannot_answer

    def test_the_ground_prompt_names_every_figure_by_key_so_quoting_is_traceable(self):
        ground = boq_ask.Ground(sources={"programme": "x"},
                                figures={"work_days": "work-days at P50: 1,046"})
        prompt = ground.as_prompt()
        assert "[work_days]" in prompt and "[programme]" in prompt
        assert "never invent another" in prompt

    def test_the_only_thing_it_may_suggest_is_recording_a_condition(self):
        """`proposes` is prose for a person to accept or ignore. It writes nothing, and it goes
        through the ordinary propose-and-confirm path like any other condition."""
        answer = boq_ask.validate({
            "answer": "…", "citations": [{"source": "programme", "quote": "a"}],
            "proposes": "Record that two holes are over water.",
        }, boq_ask.Ground(sources={"programme": "…"}))
        assert answer.proposes == "Record that two holes are over water."
        assert "applied" not in boq_ask.Answer.model_fields


def test_every_new_route_is_registered(client):
    paths = client.get("/openapi.json").json()["paths"]
    for path in (f"{BASE}/site/{{set_id}}/photos",
                 f"{BASE}/site/photos",
                 f"{BASE}/site/{{set_id}}/photos/{{photo_id}}/file",
                 f"{BASE}/site/{{set_id}}/photos/read",
                 f"{BASE}/costing/ask"):
        assert path in paths
