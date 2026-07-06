"""Async ingest transport: /ingest-upload kicks off a BACKGROUND job and returns immediately;
/ingest-status polls to done|error. DEMO stays inline (no job). The extraction body and the
per-section split are unchanged — only the transport is async now, so a big tender can extract
for as long as it needs without a client/proxy timeout killing one long request.

DEMO_MODE is forced true by the autouse fixture; the live-job tests opt out with monkeypatch and
stub the extraction seam (_ingest_live) so nothing touches a provider.
"""

import threading
import time

from fastapi.testclient import TestClient

from api import IngestUploadResponse, app
from pipeline.stage_01_ingest import ingest as ingest_mod
from pipeline.stage_01_ingest.ingest import ingest_tender
from schemas.models import ScopePackages, TenderPackage, TradeWorkPackage

client = TestClient(app)

_PDF = {"files": ("t.pdf", b"%PDF-1.4 fake", "application/pdf")}


def _wait_status(job_id: str, *, timeout_s: float = 10.0) -> dict:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        state = client.get(f"/ingest-status/{job_id}").json()
        if state["status"] in ("done", "error"):
            return state
        time.sleep(0.02)
    raise AssertionError(f"job {job_id} did not finish within {timeout_s}s")


def test_kickoff_returns_a_job_id_without_awaiting_extraction(monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "false")
    gate = threading.Event()

    def blocking(files_data, project_name, *, progress_cb=None, on_error=None):
        gate.wait(timeout=5)  # hold the "extraction" open so the kick-off can't be awaiting it
        return IngestUploadResponse(
            scope=ScopePackages(project_name="X", packages=[]),
            tender=TenderPackage(project_name="X"), tender_slug="x",
        )
    monkeypatch.setattr("api._ingest_live", blocking)

    body = client.post("/ingest-upload", files=_PDF).json()
    assert body["status"] == "queued" and body["job_id"]  # returned before extraction ran
    mid = client.get(f"/ingest-status/{body['job_id']}").json()
    assert mid["status"] in ("queued", "running") and mid["result"] is None  # still extracting

    gate.set()  # let the extraction finish
    final = _wait_status(body["job_id"])
    assert final["status"] == "done" and final["result"]["scope"]["project_name"] == "X"


def test_status_transitions_to_done_and_returns_the_scope(monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "false")

    def fake(files_data, project_name, *, progress_cb=None, on_error=None):
        return IngestUploadResponse(
            scope=ScopePackages(project_name="GE/2026/14", packages=[
                TradeWorkPackage(trade="ground_investigation", scope_summary="GI", sor_items=[])]),
            tender=TenderPackage(project_name="GE/2026/14"), tender_slug="ge-2026-14",
        )
    monkeypatch.setattr("api._ingest_live", fake)

    start = client.post("/ingest-upload", files=_PDF).json()
    assert start["status"] == "queued"                       # queued -> ... -> done
    final = _wait_status(start["job_id"])
    assert final["status"] == "done"
    assert final["result"]["scope"]["project_name"] == "GE/2026/14"  # the ScopePackages on done


def test_extraction_error_surfaces_as_job_error_not_a_crash(monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "false")

    def boom(files_data, project_name, *, progress_cb=None, on_error=None):
        raise RuntimeError("chunk 3 failed: provider rate limit")
    monkeypatch.setattr("api._ingest_live", boom)

    start = client.post("/ingest-upload", files=_PDF).json()
    final = _wait_status(start["job_id"])
    assert final["status"] == "error"                        # not a 500, not a hung job
    assert "rate limit" in final["error"] and final["result"] is None


def test_a_per_section_extraction_error_attaches_to_the_job_as_a_warning(monkeypatch):
    # A section the extractor can't read (truncated even at the floor) surfaces as a non-fatal
    # warning on the job — the run still completes with the sections that did extract.
    monkeypatch.setenv("DEMO_MODE", "false")

    def fake_live(files_data, project_name, *, progress_cb=None, on_error=None):
        if on_error:
            on_error("section H (PILING): the extractor's JSON was truncated and could not be split further, so this batch was skipped")
        return IngestUploadResponse(
            scope=ScopePackages(project_name="GE/2026/14", packages=[
                TradeWorkPackage(trade="ground_investigation", scope_summary="GI", sor_items=[])]),
            tender=TenderPackage(project_name="GE/2026/14"), tender_slug="ge-2026-14",
        )
    monkeypatch.setattr("api._ingest_live", fake_live)

    start = client.post("/ingest-upload", files=_PDF).json()
    final = _wait_status(start["job_id"])
    assert final["status"] == "done"                          # a per-section miss is not a total failure
    assert final["result"]["scope"]["project_name"] == "GE/2026/14"
    assert any("section H" in w for w in final["warnings"])   # the section is named on the job


def test_demo_path_returns_packages_without_creating_a_job():
    start = client.post("/ingest-upload", files=_PDF).json()
    assert start["status"] == "done" and start["job_id"] is None  # inline, no job
    assert start["result"]["scope"]["packages"]
    assert client.get("/ingest-status/deadbeef").status_code == 404  # nothing was registered


def test_extraction_reports_chunk_progress_to_the_callback(monkeypatch):
    # The optional per-chunk counter: ingest_tender fires progress_cb(done, total) as each chunk
    # completes — offline, a fake client, MAX_CHUNK_CHARS forced small to make 3 section chunks.
    monkeypatch.setattr(ingest_mod, "MAX_CHUNK_CHARS", 45)

    class SectionFakeClient:
        def complete_json(self, *, user, target_model, **_):
            return target_model(project_name="GI", packages=[])

    doc_text = (
        "SECTION A\nA-01 rotary drilling in rock\n"
        "SECTION B\nB-01 trial pit excavation\n"
        "SECTION C\nC-01 laboratory testing suite"
    )
    seen: list[tuple[int, int]] = []
    ingest_tender(
        TenderPackage(project_name="GI"), client=SectionFakeClient(), doc_text=doc_text,
        progress_cb=lambda done, total: seen.append((done, total)),
    )
    total = seen[0][1]
    assert total >= 2                                  # the SoR chunked into several calls
    assert seen[0] == (0, total)                       # total announced up front
    assert seen[-1] == (total, total)                  # every chunk completed
    assert [d for d, _ in seen] == list(range(total + 1))  # monotonic, no double-count under concurrency
