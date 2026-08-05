"""What is this set doing right now — the question a screen has to ask when it opens.

The bug, exactly: start a review, navigate to another tab, come back. The Register tab renders its
Run button, because `busy` is component state and the component unmounted. Press it and the server
answers 409 — a refusal of an action the UI had just invited. The job was running the whole time;
nothing on the screen could find it, because the only handle on it was a job id living in the
closure of a poll loop belonging to a component that no longer existed.

Every other status endpoint needs that id. This one needs only the set, which the URL always has.

Note it never 404s. "This set has no job" is a state, not an error — the same reasoning as
`/route/proposal` returning an empty list for a set nobody has routed. Making the caller
distinguish "no job" from "no set" on every poll would buy nothing: both mean render normally.
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
# live_any_for — any kind, not just one
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("kind", ["review", "ingest", "scope", "estimate", "archive"])
def test_a_job_of_any_kind_is_found(kind):
    """`live_for` asks "may this workflow start?" and is per-kind. This asks "is this set busy?"
    and must not care which workflow — the screen's question is about the set."""
    job_id = jobs.JOBS.create(kind, set_id="nd-2025-04")
    assert jobs.JOBS.live_any_for("nd-2025-04") == job_id


@pytest.mark.parametrize("ending", ["done", "error", "cancelled"])
def test_a_finished_job_is_not_live(ending):
    job_id = jobs.JOBS.create("review", set_id="nd-2025-04")
    jobs.JOBS.update(job_id, status=ending)
    assert jobs.JOBS.live_any_for("nd-2025-04") is None


def test_another_sets_job_is_not_returned():
    jobs.JOBS.create("review", set_id="other")
    assert jobs.JOBS.live_any_for("nd-2025-04") is None


def test_a_set_with_nothing_running_answers_none():
    assert jobs.JOBS.live_any_for("nd-2025-04") is None


def test_a_blank_set_id_matches_nothing():
    """Loose-upload jobs carry no set_id, and a blank must never match another blank — that would
    make every set look busy the moment somebody reviewed a loose document."""
    jobs.JOBS.create("review", set_id="")
    assert jobs.JOBS.live_any_for("") is None


def test_the_oldest_live_job_wins_when_two_are_queued():
    """Insertion order, so the answer is the one that will finish first. Either would be true —
    the set is busy — but the screen should follow the run that ends soonest."""
    first = jobs.JOBS.create("review", set_id="s")
    jobs.JOBS.create("estimate", set_id="s")
    assert jobs.JOBS.live_any_for("s") == first


# ---------------------------------------------------------------------------
# The endpoint
# ---------------------------------------------------------------------------
def test_the_endpoint_returns_the_running_job(client):
    job_id = jobs.JOBS.create("review", set_id="nd-2025-04")
    jobs.JOBS.mark_running(job_id, "ingesting")
    body = client.get("/client-boq/jobs/live/nd-2025-04").json()
    assert body["job_id"] == job_id
    assert body["kind"] == "review"
    assert body["status"] == "running"
    assert body["stage"] == "ingesting"


def test_the_endpoint_carries_progress_so_the_strip_resumes_mid_run(client):
    """A recovered job must come back with its counters, not a bare "running" — the strip should
    resume where the run actually is, not restart at zero."""
    from client_boq.router import _count_cb

    job_id = jobs.JOBS.create("review", set_id="s")
    jobs.JOBS.mark_running(job_id, "ingesting")
    _count_cb(job_id)(7, 33)
    body = client.get("/client-boq/jobs/live/s").json()
    assert (body["done"], body["total"]) == (7, 33)


def test_an_unknown_set_is_not_a_404(client):
    """The whole point. A 404 would make every screen treat "nothing running" as an error."""
    resp = client.get("/client-boq/jobs/live/never-heard-of-it")
    assert resp.status_code == 200
    assert resp.json()["job_id"] is None


def test_a_set_whose_job_has_finished_reports_no_job(client):
    job_id = jobs.JOBS.create("review", set_id="s")
    jobs.JOBS.update(job_id, status="done")
    assert client.get("/client-boq/jobs/live/s").json()["job_id"] is None


def test_the_status_enum_was_not_widened(client):
    """No sixth status meaning "idle". A null id already says it, and two ways to say one thing is
    how a client ends up handling only one of them."""
    body = client.get("/client-boq/jobs/live/nothing-here").json()
    assert body["status"] in ("queued", "running", "done", "error", "cancelled")


def test_the_recovered_id_polls_on_its_own_kinds_status_endpoint(client):
    """What the client does next: read `kind`, pick the matching status endpoint, join the poll."""
    job_id = jobs.JOBS.create("scope", set_id="s")
    jobs.JOBS.mark_running(job_id, "scoping")
    live = client.get("/client-boq/jobs/live/s").json()
    assert live["kind"] == "scope"
    assert client.get(f"/client-boq/estimate/status/{live['job_id']}").json()["job_id"] == job_id


# ---------------------------------------------------------------------------
# The set_id has to actually be recorded, or none of the above finds anything
# ---------------------------------------------------------------------------
def test_the_split_job_records_its_set(client, make_set, part_spec, monkeypatch):
    """Four of the five `JOBS.create` calls passed no set_id, so `live_any_for` would have found
    only reviews. The split is the one a person is most likely to navigate away from."""
    monkeypatch.setenv("DEMO_MODE", "")          # leave DEMO so the job path is taken
    from client_boq import store as cb_store

    make_set("split-set", "Split Set", [part_spec(1, "CC", "Conditions", "contract-conditions")])
    conn = cb_store.get_conn()
    try:
        cb_store.approve_manifest(conn, "split-set", True)
    finally:
        conn.close()
    client.post("/client-boq/ingest/split", json={"set_id": "split-set"})
    # The worker may already have finished or errored; what is under test is that the job was
    # CREATED against the set, which is what the recovery endpoint needs.
    assert any(j.set_id == "split-set" for j in jobs.JOBS._jobs.values())


def test_the_upload_job_deliberately_has_no_set(client):
    """Not an omission. That job CREATES the set — its id does not exist until the manifest is
    planned, so there is nothing to match on and no screen that could be asking about it yet."""
    import inspect

    from client_boq import router

    source = inspect.getsource(router.post_ingest_upload)
    assert 'jobs.JOBS.create("ingest")' in source        # no set_id, on purpose
