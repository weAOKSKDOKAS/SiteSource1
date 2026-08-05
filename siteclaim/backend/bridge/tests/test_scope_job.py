"""The scope split runs as a JOB on the live path — stage, N/M, and a stop that works.

`POST /bridge/{set_id}/scope` read every part's pdf, ran the extraction and indexed every document
inside the request. On the real pack that is ~170 documents and minutes. It was a sync `def`, so it
never blocked the event loop — which is exactly why the failure was invisible: the server stayed up
and the only symptom was one request that never came back.

DEMO still answers inline (there is nothing to wait for), which is why every other bridge test in
this directory is untouched by the change.

Offline throughout: a stub client stands in for Layer 2, and the parts are real one-page PDFs.
"""

import pytest
from fastapi.testclient import TestClient

from bridge import parts as parts_mod
from bridge import scope as scope_mod
from client_boq import jobs
from schemas.models import ScopePackages, SorItem, TradeWorkPackage


@pytest.fixture
def client():
    import api

    return TestClient(api.app)


@pytest.fixture
def live(monkeypatch):
    """DEMO off — the branch that makes a job. The split itself still runs offline."""
    monkeypatch.setenv("DEMO_MODE", "false")


@pytest.fixture
def make_pdf(tmp_path):
    def _make(name: str, pages: list[str]) -> str:
        import fitz

        doc = fitz.open()
        for body in pages:
            page = doc.new_page()
            y = 80
            for line in body.splitlines():
                page.insert_text((60, y), line, fontsize=11)
                y += 16
        path = tmp_path / name
        doc.save(str(path))
        doc.close()
        return str(path)

    return _make


class StubClient:
    def complete_json(self, *, system, user, target_model, **_kw):
        return ScopePackages(project_name="GE/2026/14", packages=[TradeWorkPackage(
            trade="foundation_substructure", scope_summary="Piling",
            sor_items=[SorItem(item_ref="G1", description="Bored piling", unit="m", qty=100.0,
                               section="G")],
        )])


@pytest.fixture
def a_set(make_set, part_spec, make_pdf, tmp_path, monkeypatch):
    """A set with one confirmed bill part and three context parts, each a real pdf."""
    monkeypatch.setenv("SITESOURCE_WORKDIR", str(tmp_path / "ws"))
    specs = [
        part_spec(1, "SR", "Schedule of Rates", "pricing"),
        part_spec(2, "PS", "Particular Specification", "specifications"),
        part_spec(3, "GS", "General Specification", "specifications"),
        part_spec(4, "CL", "Clarification", "correspondence"),
    ]
    paths = {
        s.part_id: make_pdf(f"{s.part_id}.pdf", ["SECTION G : PILING\nG1  Bored piling  m  100"])
        for s in specs
    }
    make_set("ge-2026-14", "Contract No. GE/2026/14", specs, pdf_paths=paths)
    parts_mod.confirm_bill_parts("ge-2026-14", [specs[0].part_id])
    return "ge-2026-14"


def _drain(job_id: str, timeout: float = 30.0):
    """Wait for the pool to finish a job. The pool is real; this is not a sleep-and-hope."""
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = jobs.JOBS.get(job_id)
        if job and job.status in ("done", "error", "cancelled"):
            return job
        time.sleep(0.05)
    raise AssertionError(f"job {job_id} did not finish within {timeout}s")


# -- the envelope --------------------------------------------------------------------------------
def test_demo_still_answers_inline(client, a_set, monkeypatch):
    """The reason every other test in this directory needed no edit."""
    monkeypatch.setattr("pipeline.stage_01_ingest.ingest.LLMClient", lambda *a, **k: StubClient())
    body = client.post(f"/bridge/{a_set}/scope").json()
    assert "scope" in body and "job_id" not in body


def test_the_live_path_returns_a_job_envelope(client, a_set, live, monkeypatch):
    monkeypatch.setattr("pipeline.stage_01_ingest.ingest.LLMClient", lambda *a, **k: StubClient())
    body = client.post(f"/bridge/{a_set}/scope").json()
    assert body["kind"] == "scope_split" and body["status"] == "queued"
    assert body["job_id"]
    _drain(body["job_id"])


def test_the_finished_result_is_the_shape_the_endpoint_used_to_return(
    client, a_set, live, monkeypatch,
):
    """The whole compatibility claim: set_id, scope, unrecognised_items, notes."""
    monkeypatch.setattr("pipeline.stage_01_ingest.ingest.LLMClient", lambda *a, **k: StubClient())
    job_id = client.post(f"/bridge/{a_set}/scope").json()["job_id"]
    job = _drain(job_id)

    assert job.status == "done"
    assert set(job.result) == {"set_id", "scope", "unrecognised_items", "notes"}
    assert job.result["set_id"] == a_set
    assert job.result["scope"]["packages"][0]["trade"] == "foundation_substructure"


def test_the_split_is_persisted_by_the_job_not_by_the_endpoint(client, a_set, live, monkeypatch):
    monkeypatch.setattr("pipeline.stage_01_ingest.ingest.LLMClient", lambda *a, **k: StubClient())
    _drain(client.post(f"/bridge/{a_set}/scope").json()["job_id"])
    # The persisted read is what the routing gate uses, and it must be there when the job is done.
    assert client.get(f"/bridge/{a_set}/scope").status_code == 200


def test_the_existing_poll_and_cancel_endpoints_serve_it(client, a_set, live, monkeypatch):
    """One job store, so no second poll route to keep in step with the first."""
    monkeypatch.setattr("pipeline.stage_01_ingest.ingest.LLMClient", lambda *a, **k: StubClient())
    job_id = client.post(f"/bridge/{a_set}/scope").json()["job_id"]
    assert client.get(f"/client-boq/ingest/status/{job_id}").status_code == 200
    _drain(job_id)


# -- progress and stop ---------------------------------------------------------------------------
def test_progress_counts_documents_and_reports_the_stage(a_set, live, monkeypatch):
    """N/M is per DOCUMENT — the only boundary indexing has."""
    monkeypatch.setattr("pipeline.stage_01_ingest.ingest.LLMClient", lambda *a, **k: StubClient())
    stages: list[str] = []
    counts: list[tuple[int, int]] = []
    scope_mod.scope_from_set(
        a_set, progress_cb=stages.append, count_cb=lambda d, t: counts.append((d, t)),
    )
    assert stages == ["reading", "splitting", "indexing"]
    # One confirmed bill + three context parts, and the denominator is known from the FIRST tick.
    assert counts == [(1, 4), (2, 4), (3, 4), (4, 4)]


def test_a_cancel_takes_effect_at_a_part_boundary(a_set, live, monkeypatch):
    """`count_cb` may raise, and that is the whole cancel mechanism for this stage."""
    monkeypatch.setattr("pipeline.stage_01_ingest.ingest.LLMClient", lambda *a, **k: StubClient())
    seen: list[int] = []

    def _stop_after_two(done: int, total: int) -> None:
        seen.append(done)
        if done == 2:
            raise jobs.JobCancelled("indexing")

    with pytest.raises(jobs.JobCancelled):
        scope_mod.scope_from_set(a_set, count_cb=_stop_after_two)
    assert seen == [1, 2]                        # it stopped, it did not run all four


def test_a_cancelled_job_is_reported_as_cancelled_not_as_an_error(a_set, live, monkeypatch):
    from bridge.scope_job import run_scope_split_job

    monkeypatch.setattr("pipeline.stage_01_ingest.ingest.LLMClient", lambda *a, **k: StubClient())
    job_id = jobs.JOBS.create("scope_split", set_id=a_set)
    jobs.JOBS.cancel(job_id)                     # cancelled while it sat in the queue
    run_scope_split_job(job_id, a_set)

    job = jobs.JOBS.get(job_id)
    assert job.status == "cancelled" and job.error in (None, "")


def test_the_index_is_not_written_when_the_run_is_cancelled(a_set, live, monkeypatch, tmp_path):
    """Nothing half-written: the index is persisted only once the whole loop is past."""
    from pipeline.workspace import Workspace

    monkeypatch.setattr("pipeline.stage_01_ingest.ingest.LLMClient", lambda *a, **k: StubClient())

    def _stop_at_once(done: int, total: int) -> None:
        raise jobs.JobCancelled("indexing")

    with pytest.raises(jobs.JobCancelled):
        scope_mod.scope_from_set(a_set, count_cb=_stop_at_once)
    assert not Workspace().doc_index_path(a_set).is_file()


# -- one at a time -------------------------------------------------------------------------------
def test_a_second_split_on_the_same_set_is_refused_not_queued(client, a_set, live, monkeypatch):
    monkeypatch.setattr("pipeline.stage_01_ingest.ingest.LLMClient", lambda *a, **k: StubClient())
    first = client.post(f"/bridge/{a_set}/scope").json()["job_id"]
    # Held open deliberately: the pool is two wide, so without the guard a second run would index
    # the same documents concurrently and overwrite the first's split.
    jobs.JOBS.update(first, status="running")
    second = client.post(f"/bridge/{a_set}/scope")

    assert second.status_code == 409
    assert first in second.json()["detail"]
    jobs.JOBS.update(first, status="done")
    _drain(first)


def test_the_estimate_scope_workflow_does_not_collide_with_it(client, a_set, live):
    """`scope` is already `/client-boq/estimate/scope`'s kind — sharing it would have each
    workflow 409 the other with a job the operator never started."""
    other = jobs.JOBS.create("scope", set_id=a_set)
    jobs.JOBS.update(other, status="running")
    assert client.post(f"/bridge/{a_set}/scope").status_code != 409
