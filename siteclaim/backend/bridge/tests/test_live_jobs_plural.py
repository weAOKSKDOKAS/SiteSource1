"""FIX 8 — the strip can describe a different job than the banner beside it.

Observed: the strip read ``INGEST · INTERPRETING · STAGE 2 OF 3`` while a REVIEW ran on the same
set and the banner beside it discussed the review.

``live_any_for`` returned the first match — the oldest — and its docstring reasoned that either
answer is true because "the pool serialises anyway". **That reasoning was wrong, and it was mine.**
``jobs.POOL`` is ``ThreadPoolExecutor(max_workers=2)``: an ingest and a review genuinely run at the
same time, and the singular answer was then being asked to carry a choice it could not make.

The plural is the fix. A screen that knows which tab is in view can prefer that tab's job; a screen
that does not still gets the oldest; and where more than one is live, the fact is visible rather
than silently resolved.
"""

import pytest
from fastapi.testclient import TestClient

from client_boq import jobs


@pytest.fixture(autouse=True)
def _clean_job_store():
    jobs.JOBS._jobs.clear()
    yield
    jobs.JOBS._jobs.clear()


@pytest.fixture
def client():
    from api import app

    return TestClient(app)


# ---------------------------------------------------------------------------
# The premise: two workers, so two jobs really can be live
# ---------------------------------------------------------------------------
def test_the_pool_is_two_wide_which_is_why_the_old_reasoning_failed():
    """Pinned, because the discarded justification rested on this being 1."""
    assert jobs.POOL._max_workers == 2


def test_the_docstring_no_longer_claims_the_pool_serialises():
    """The old text stated a justification now known to be false. A wrong reason left in place is
    worse than none: the next person reads it and trusts it."""
    assert "serialises anyway" not in (jobs.JobStore.live_any_for.__doc__ or "")


# ---------------------------------------------------------------------------
# live_all_for
# ---------------------------------------------------------------------------
def test_every_live_job_comes_back_oldest_first():
    first = jobs.JOBS.create("ingest", set_id="s")
    second = jobs.JOBS.create("review", set_id="s")
    assert jobs.JOBS.live_all_for("s") == [first, second]


def test_finished_jobs_are_excluded():
    done = jobs.JOBS.create("ingest", set_id="s")
    jobs.JOBS.update(done, status="done")
    live = jobs.JOBS.create("review", set_id="s")
    assert jobs.JOBS.live_all_for("s") == [live]


def test_another_sets_jobs_are_excluded():
    jobs.JOBS.create("review", set_id="other")
    assert jobs.JOBS.live_all_for("s") == []


def test_the_singular_still_answers_the_oldest():
    """`live_any_for` keeps its contract — "is this set busy?" — and is now derived from the list,
    so the two can never disagree about what is live."""
    first = jobs.JOBS.create("ingest", set_id="s")
    jobs.JOBS.create("review", set_id="s")
    assert jobs.JOBS.live_any_for("s") == first


def test_a_blank_set_id_matches_nothing():
    jobs.JOBS.create("review", set_id="")
    assert jobs.JOBS.live_all_for("") == []


# ---------------------------------------------------------------------------
# The endpoint
# ---------------------------------------------------------------------------
def test_the_endpoint_returns_both_runs_with_their_kinds(client):
    """What the screen needs in order to pick: the KIND of each, so it can find the one its tab
    owns instead of being handed an arbitrary one."""
    ingest = jobs.JOBS.create("ingest", set_id="nd-2025-04")
    jobs.JOBS.mark_running(ingest, "interpreting")
    review = jobs.JOBS.create("review", set_id="nd-2025-04")
    jobs.JOBS.mark_running(review, "ingesting")

    body = client.get("/client-boq/jobs/live-all/nd-2025-04").json()
    assert [j["kind"] for j in body["jobs"]] == ["ingest", "review"]
    assert [j["job_id"] for j in body["jobs"]] == [ingest, review]
    assert [j["stage"] for j in body["jobs"]] == ["interpreting", "ingesting"]


def test_each_carries_its_own_progress(client):
    """One strip describes one run, so each has to arrive with its own counters — a shared or
    last-write-wins number is exactly how the wrong stage got shown."""
    from client_boq.router import _count_cb

    a = jobs.JOBS.create("ingest", set_id="s")
    jobs.JOBS.mark_running(a, "interpreting")
    _count_cb(a)(2, 3)
    b = jobs.JOBS.create("review", set_id="s")
    jobs.JOBS.mark_running(b, "ingesting")
    _count_cb(b)(7, 33)

    by_kind = {j["kind"]: j for j in client.get("/client-boq/jobs/live-all/s").json()["jobs"]}
    assert (by_kind["ingest"]["done"], by_kind["ingest"]["total"]) == (2, 3)
    assert (by_kind["review"]["done"], by_kind["review"]["total"]) == (7, 33)


def test_a_set_with_nothing_running_is_an_empty_list_not_a_404(client):
    resp = client.get("/client-boq/jobs/live-all/never-heard-of-it")
    assert resp.status_code == 200
    assert resp.json()["jobs"] == []


def test_the_singular_endpoint_still_works(client):
    """Unchanged for every caller that only needs "is this set busy?"."""
    job_id = jobs.JOBS.create("review", set_id="s")
    assert client.get("/client-boq/jobs/live/s").json()["job_id"] == job_id
