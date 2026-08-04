"""One review per set, and a clock that does not report waiting as working.

Both halves of one incident. Four reviews were started on a single 206-part set — job ids
``f95cf963``, ``cc1f1e3a``, ``853060a0``, ``cdc5bc29``, four separate POSTs, four real server jobs
— and the run being watched reported 34 minutes.

Neither number meant what it looked like:

* Nothing refused the duplicates. ``/review/run`` created and submitted unconditionally, and the
  Run button's guard was ``busy`` state inside a tab component that unmounts on navigation, so
  leaving the tab and returning re-armed it.
* ``elapsed_seconds`` counted from ``create()`` — from ENQUEUE. The pool has two workers shared by
  every workflow, so three of those four jobs sat in a queue, and time spent waiting for a worker
  was being displayed as time spent working.

The two compound: without the split you cannot tell a slow review from a queued one, so you cannot
tell whether the fix is fewer parts or fewer runs.

These live in ``bridge/tests`` rather than ``client_boq/tests`` deliberately — the change they
cover is a narrowly authorised one inside another developer's module, and keeping the tests out of
his tree keeps his diff to the source lines that were actually agreed.
"""

import pytest
from fastapi.testclient import TestClient

from client_boq import jobs


@pytest.fixture(autouse=True)
def _clean_job_store():
    """``jobs.JOBS`` is a module-level singleton, so a job left behind leaks into the next test."""
    jobs.JOBS._jobs.clear()
    yield
    jobs.JOBS._jobs.clear()


@pytest.fixture
def client():
    from api import app

    return TestClient(app)


# ---------------------------------------------------------------------------
# live_for — what counts as "already in flight"
# ---------------------------------------------------------------------------
def test_a_queued_job_counts_as_in_flight():
    """A queued job has a worker coming. The whole point of refusing is that a second run must
    not be lined up behind the first, so `queued` blocks exactly as `running` does."""
    job_id = jobs.JOBS.create("review", set_id="nd-2025-04")
    assert jobs.JOBS.get(job_id).status == "queued"
    assert jobs.JOBS.live_for("review", "nd-2025-04") == job_id


def test_a_running_job_counts_as_in_flight():
    job_id = jobs.JOBS.create("review", set_id="nd-2025-04")
    jobs.JOBS.mark_running(job_id, "ingesting")
    assert jobs.JOBS.live_for("review", "nd-2025-04") == job_id


@pytest.mark.parametrize("ending", ["done", "error", "cancelled"])
def test_a_finished_job_never_blocks_a_re_run(ending):
    """Every way a job can end. A review that failed is the one you most want to run again."""
    job_id = jobs.JOBS.create("review", set_id="nd-2025-04")
    jobs.JOBS.update(job_id, status=ending)
    assert jobs.JOBS.live_for("review", "nd-2025-04") is None


def test_a_job_on_another_set_does_not_block():
    jobs.JOBS.create("review", set_id="other-tender")
    assert jobs.JOBS.live_for("review", "nd-2025-04") is None


def test_a_job_of_another_kind_does_not_block():
    """An ingest and a review on one set are sequential by the manifest gate, not by this."""
    jobs.JOBS.create("ingest", set_id="nd-2025-04")
    assert jobs.JOBS.live_for("review", "nd-2025-04") is None


def test_a_loose_upload_job_belongs_to_no_set_and_is_never_matched():
    """Reviews of loose documents carry no set_id. "Another one for the same set" is not a
    question that can be asked about them, and a blank set_id must not match another blank."""
    jobs.JOBS.create("review", set_id="")
    assert jobs.JOBS.live_for("review", "") is None


# ---------------------------------------------------------------------------
# The endpoint refuses — 409, not a queue
# ---------------------------------------------------------------------------
def test_a_second_review_on_a_set_in_flight_is_refused(client, make_set, part_spec):
    """The guard sits BEFORE the DEMO branch, so it is one code path in both modes rather than a
    fork on `demo_mode()`. Seeding a live job proves it fires without leaving DEMO."""
    from client_boq import store as cb_store

    make_set("nd-2025-04", "ND 2025 04", [part_spec(1, "ACC", "Conditions", "contract-conditions")])
    conn = cb_store.get_conn()
    try:
        cb_store.approve_manifest(conn, "nd-2025-04", True)
    finally:
        conn.close()

    first = jobs.JOBS.create("review", set_id="nd-2025-04")
    resp = client.post("/client-boq/review/run",
                       data={"project_name": "ND 2025 04", "set_id": "nd-2025-04"})
    assert resp.status_code == 409
    detail = resp.json()["detail"]
    # The id is named so the answer is actionable — poll it or cancel it, rather than guess.
    assert first in detail
    assert "refused rather than" in detail


def test_the_refusal_lifts_once_the_first_run_ends(client, make_set, part_spec):
    from client_boq import store as cb_store

    make_set("nd-2025-04", "ND 2025 04", [part_spec(1, "ACC", "Conditions", "contract-conditions")])
    conn = cb_store.get_conn()
    try:
        cb_store.approve_manifest(conn, "nd-2025-04", True)
    finally:
        conn.close()

    first = jobs.JOBS.create("review", set_id="nd-2025-04")
    assert client.post("/client-boq/review/run",
                       data={"set_id": "nd-2025-04"}).status_code == 409
    jobs.JOBS.update(first, status="done")
    # DEMO runs the review inline and returns the register, so a 200 here is the run proceeding.
    assert client.post("/client-boq/review/run",
                       data={"set_id": "nd-2025-04"}).status_code == 200


def test_the_manifest_gate_still_answers_first(client, make_set, part_spec):
    """Two 409s with different causes must not be confused. An unapproved manifest is reported as
    an unapproved manifest even when a job is also in flight — the gate is the earlier problem."""
    make_set("nd-2025-04", "ND 2025 04", [part_spec(1, "ACC", "Conditions", "contract-conditions")])
    jobs.JOBS.create("review", set_id="nd-2025-04")
    resp = client.post("/client-boq/review/run", data={"set_id": "nd-2025-04"})
    assert resp.status_code == 409
    assert "split manifest" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# Two clocks — waiting is not working
# ---------------------------------------------------------------------------
def test_a_queued_job_has_spent_no_running_time(client):
    """The defect in one assertion: a job that has not started reported its whole queue wait as
    elapsed run time, and the screen showed a review "running" for 20 minutes having done nothing."""
    job_id = jobs.JOBS.create("review", set_id="s")
    state = client.get(f"/client-boq/review/status/{job_id}").json()
    assert state["status"] == "queued"
    assert state["running_seconds"] == 0.0
    assert state["queued_seconds"] >= 0.0


def test_the_queue_clock_freezes_when_a_worker_picks_the_job_up():
    """`queued_seconds` must stop moving once work starts, or the two clocks both keep running and
    their sum exceeds the wall clock."""
    from client_boq.router import _job_state

    job_id = jobs.JOBS.create("review", set_id="s")
    jobs.JOBS.mark_running(job_id, "ingesting")
    first = _job_state(job_id, jobs.JOBS.get(job_id))
    second = _job_state(job_id, jobs.JOBS.get(job_id))
    assert first.queued_seconds == second.queued_seconds       # frozen
    assert second.running_seconds >= first.running_seconds     # still moving


def test_running_at_is_stamped_once_and_never_restamped():
    """A second `mark_running` must not reset the run clock — that would make a long job look
    freshly started every time a stage boundary passed."""
    job_id = jobs.JOBS.create("review", set_id="s")
    jobs.JOBS.mark_running(job_id, "ingesting")
    stamped = jobs.JOBS.get(job_id).running_at
    jobs.JOBS.mark_running(job_id, "summarising")
    assert jobs.JOBS.get(job_id).running_at == stamped
    assert jobs.JOBS.get(job_id).stage == "summarising"        # the stage still advances


def test_elapsed_still_means_total_so_nothing_reading_it_changed_under_it():
    """The split is ADDITIVE. `elapsed_seconds` keeps counting from the request, and the two new
    numbers decompose it — otherwise every existing reader silently changed meaning."""
    from client_boq.router import _job_state

    job_id = jobs.JOBS.create("review", set_id="s")
    jobs.JOBS.mark_running(job_id, "ingesting")
    state = _job_state(job_id, jobs.JOBS.get(job_id))
    assert state.elapsed_seconds == pytest.approx(
        state.queued_seconds + state.running_seconds, abs=0.2)


def test_a_never_started_job_reports_all_of_its_time_as_queued():
    from client_boq.router import _job_state

    job_id = jobs.JOBS.create("review", set_id="s")
    state = _job_state(job_id, jobs.JOBS.get(job_id))
    assert state.running_seconds == 0.0
    assert state.elapsed_seconds == pytest.approx(state.queued_seconds, abs=0.2)
