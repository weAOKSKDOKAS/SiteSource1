"""Stopping a run.

A full pass over a real tender was roughly 100 model calls at 20-120 seconds each with no way to
stop it. Cancelling cannot kill what is running — the work between stages is a blocking HTTP
request on a pool thread and Python cannot interrupt one — but it can stop the NEXT call from
starting, which on a run that shape is nearly all of the saving. These tests pin that distinction,
because a cancel that implied "stopped now" would be a lie told at the worst moment.
"""

import pytest
from fastapi.testclient import TestClient

from client_boq import jobs


@pytest.fixture
def client():
    import api

    return TestClient(api.app)


def _fresh(kind="review"):
    return jobs.JOBS.create(kind)


# -- the store ----------------------------------------------------------------------------------
def test_a_queued_job_is_cancelled_outright():
    """There is no boundary to wait for: nothing has started."""
    job_id = _fresh()
    assert jobs.JOBS.cancel(job_id) is True
    job = jobs.JOBS.get(job_id)
    assert job.status == "cancelled" and job.cancel_requested is True


def test_a_running_job_is_asked_rather_than_stopped():
    job_id = _fresh()
    jobs.JOBS.update(job_id, status="running", stage="summarising")
    assert jobs.JOBS.cancel(job_id) is True
    job = jobs.JOBS.get(job_id)
    assert job.cancel_requested is True
    assert job.status == "running"      # still running — the current call cannot be interrupted
    assert job.stage == "summarising"   # and it is still honestly reported as where it is


def test_cancelling_a_finished_job_is_a_no_op_not_an_error():
    """By the time a person reaches the button the run may have ended. That is not a failure."""
    for status in ("done", "error", "cancelled"):
        job_id = _fresh()
        jobs.JOBS.update(job_id, status=status)
        assert jobs.JOBS.cancel(job_id) is False


def test_cancelling_an_unknown_job_is_false_not_a_raise():
    assert jobs.JOBS.cancel("no-such-job") is False
    assert jobs.JOBS.cancelled("no-such-job") is False


# -- the stage boundary -------------------------------------------------------------------------
def test_the_stage_callback_stops_the_run_at_the_next_boundary():
    from client_boq.router import _stage_cb

    job_id = _fresh()
    jobs.JOBS.update(job_id, status="running")   # past the queue: a boundary is what stops it now
    cb = _stage_cb(job_id)
    cb("ingesting")                                   # no cancel yet — records and continues
    assert jobs.JOBS.get(job_id).stage == "ingesting"

    jobs.JOBS.cancel(job_id)
    with pytest.raises(jobs.JobCancelled):
        cb("summarising")
    # The stage is NOT advanced past where it stopped: the run never reached summarising.
    assert jobs.JOBS.get(job_id).stage == "ingesting"


def test_a_worker_records_a_cancel_as_cancelled_not_as_an_error():
    """A stopped run is not a failed one, and must not be reported as one."""
    from client_boq.router import _run_split_job

    job_id = _fresh("ingest")
    jobs.JOBS.cancel(job_id)     # cancelled while queued — the worker must not resurrect it
    _run_split_job(job_id, "no-such-set")
    job = jobs.JOBS.get(job_id)
    assert job.status == "cancelled"
    assert job.error == ""
    assert "stopped before" in job.stage


# -- the endpoint -------------------------------------------------------------------------------
def test_one_endpoint_serves_every_workflow(client):
    """One job store, one cancel. The kind is the job's business, not the caller's."""
    for kind in ("ingest", "review", "estimate", "scope"):
        job_id = _fresh(kind)
        jobs.JOBS.update(job_id, status="running")
        body = client.post(f"/client-boq/jobs/{job_id}/cancel").json()
        assert body["cancel_requested"] is True
        assert body["kind"] == kind


def test_cancelling_an_unknown_job_404s(client):
    assert client.post("/client-boq/jobs/never-existed/cancel").status_code == 404


def test_the_response_reports_the_request_before_the_boundary_lands(client):
    """`cancel_requested` true with status still running is the state the UI needs to say
    "stopping at the next step" rather than "stopped"."""
    job_id = _fresh()
    jobs.JOBS.update(job_id, status="running", stage="summarising")
    body = client.post(f"/client-boq/jobs/{job_id}/cancel").json()
    assert body["status"] == "running" and body["cancel_requested"] is True


def test_status_polls_carry_the_cancel_flag(client):
    job_id = _fresh("review")
    jobs.JOBS.update(job_id, status="running")
    jobs.JOBS.cancel(job_id)
    body = client.get(f"/client-boq/review/status/{job_id}").json()
    assert body["cancel_requested"] is True
