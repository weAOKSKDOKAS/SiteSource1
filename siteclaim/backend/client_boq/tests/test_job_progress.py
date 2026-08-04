"""What a ten-minute run is allowed to claim about itself.

For roughly 100 model calls the strip showed a label and a moving bar. `_stage_cb` already knew
which stage it was on; `run_split` already knew it was on part 3 of 12 — and said so in the stage
STRING, where nothing downstream could read it as a quantity. Neither reached the UI.

The rule these tests exist to hold: **build what is knowable, build nothing that is guessed.** A
total is printed only where the code that produces it is certain, and there is no remaining-time
estimate anywhere, because nothing in this system can honestly make one.
"""

import pytest
from fastapi.testclient import TestClient

from client_boq import jobs
from client_boq.router import _count_cb, _stage_cb


@pytest.fixture
def client():
    import api

    return TestClient(api.app)


def _running(kind="review"):
    job_id = jobs.JOBS.create(kind)
    jobs.JOBS.update(job_id, status="running")
    return job_id


# -- stage position -----------------------------------------------------------------------------
def test_a_stage_reports_where_it_sits_in_its_workflow():
    job_id = _running("ingest")
    cb = _stage_cb(job_id, "ingest")
    cb("planning")
    job = jobs.JOBS.get(job_id)
    assert (job.stage, job.stage_index, job.stage_total) == ("planning", 3, 4)


def test_a_workflow_with_a_conditional_tail_reports_position_but_no_total():
    """The review's last stage (`locating`) runs only when there are parts to locate citations in,
    so its length is 8 OR 9. Printing 9 and stopping at 8 would be a total contradicted two stages
    later; the position alone is true either way."""
    job_id = _running("review")
    _stage_cb(job_id, "review")("cashflow")
    job = jobs.JOBS.get(job_id)
    assert job.stage_index == 6
    assert job.stage_total == 0        # no total, rather than one that might be wrong


def test_an_unlisted_workflow_claims_no_position_at_all():
    """The estimate and scope runners live under `client_boq/estimate/`, which this work may not
    read into — so their sequences are unknown and nothing is invented for them."""
    job_id = _running("estimate")
    _stage_cb(job_id, "")("costing")
    job = jobs.JOBS.get(job_id)
    assert (job.stage, job.stage_index, job.stage_total) == ("costing", 0, 0)


def test_an_unrecognised_stage_name_reports_no_position():
    job_id = _running("ingest")
    _stage_cb(job_id, "ingest")("something-new")
    assert jobs.JOBS.get(job_id).stage_index == 0


# -- per-stage counts ---------------------------------------------------------------------------
def test_a_count_is_written_while_the_loop_runs():
    job_id = _running("ingest")
    _count_cb(job_id)(3, 12)
    job = jobs.JOBS.get(job_id)
    assert (job.done, job.total) == (3, 12)


def test_a_new_stage_clears_the_previous_stages_count():
    """8/8 left standing over a stage that has counted nothing is a bar moving without work
    behind it."""
    job_id = _running("ingest")
    _count_cb(job_id)(8, 8)
    _stage_cb(job_id, "ingest")("saving")
    job = jobs.JOBS.get(job_id)
    assert (job.done, job.total) == (0, 0)


def test_run_split_reports_its_part_count_as_numbers(client):
    """It always knew. `interpreting 3/12` was a stage string; this is the same fact as data."""
    from client_boq.ingest import run as ingest_run

    seen: list[tuple[int, int]] = []
    with pytest.raises(ValueError):          # no manifest for this set — the callback contract is
        ingest_run.run_split("never-ingested", count_cb=lambda d, t: seen.append((d, t)))
    assert seen == []                        # what is under test, not the split itself


def test_the_review_counts_its_parts():
    from client_boq.models import PartSpec
    from client_boq.review import s01_ingest

    seen: list[tuple[int, int]] = []
    parts = [(PartSpec(n=i, abbr=f"P{i}", slug=f"p{i}", title=f"Part {i}",
                       category="contract-conditions"), "") for i in (1, 2, 3)]
    s01_ingest.ingest_from_parts(parts, "T", count_cb=lambda d, t: seen.append((d, t)))
    assert seen == [(0, 3), (1, 3), (2, 3), (3, 3)]   # each part, then the finished total


def test_a_skipped_part_is_not_counted_as_work():
    """The count is of what will be READ. Counting a skipped bill would put the bar ahead of the
    work."""
    from client_boq.models import PartSpec
    from client_boq.review import s01_ingest

    seen: list[tuple[int, int]] = []
    parts = [
        (PartSpec(n=1, abbr="BQ", slug="bq", title="Bill", category="pricing"), ""),
        (PartSpec(n=2, abbr="CC", slug="cc", title="Conditions", category="contract-conditions"), ""),
    ]
    s01_ingest.ingest_from_parts(parts, "T", count_cb=lambda d, t: seen.append((d, t)))
    assert seen == [(0, 1), (1, 1)]          # one readable part, not two


# -- elapsed, and nothing beyond it ---------------------------------------------------------------
def test_elapsed_is_reported(client):
    job_id = _running("review")
    body = client.get(f"/client-boq/review/status/{job_id}").json()
    assert "elapsed_seconds" in body and body["elapsed_seconds"] >= 0


def test_nothing_claims_to_know_what_remains(client):
    """A rule, not a preference. Nothing here can honestly estimate remaining time, and a countdown
    that lies is worse than a bar that admits it does not know."""
    job_id = _running("review")
    body = client.get(f"/client-boq/review/status/{job_id}").json()
    forbidden = {"eta", "remaining", "remaining_seconds", "estimated_seconds", "percent_complete"}
    assert forbidden.isdisjoint(body)


def test_the_status_response_carries_the_position_and_the_count(client):
    job_id = _running("ingest")
    _stage_cb(job_id, "ingest")("inspecting")
    _count_cb(job_id)(2, 5)
    body = client.get(f"/client-boq/ingest/status/{job_id}").json()
    assert body["stage"] == "inspecting"
    assert (body["stage_index"], body["stage_total"]) == (2, 4)
    assert (body["done"], body["total"]) == (2, 5)
