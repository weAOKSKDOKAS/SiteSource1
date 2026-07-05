"""EOS narrative endpoints (Phase P2a) — attach the field account, offline (DEMO).

The narrative text path is deterministic and works offline; a file upload is gated behind
EOS_PDF_PARSE (default off). Every write targets a temp LIVE profile DB via SITESOURCE_DB.
"""

import pytest
from fastapi.testclient import TestClient

from api import app
from db import seed

client = TestClient(app)


@pytest.fixture
def bench_db(tmp_path, monkeypatch):
    db = tmp_path / "bench.db"
    seed.build_database(db, profile="live")
    monkeypatch.setenv("SITESOURCE_DB", str(db))
    return db


def _project(name: str = "GI Term Contract") -> int:
    return client.post("/benchmark/projects", json={"name": name, "trade": "ground_investigation"}).json()["id"]


def test_eos_routes_are_registered():
    paths = {r.path for r in app.routes}
    assert {"/benchmark/{project_id}/eos-upload", "/benchmark/{project_id}/eos"} <= paths


def test_eos_narrative_text_is_stored_offline(bench_db):
    pid = _project()
    assert client.get(f"/benchmark/{pid}/eos").json() is None  # none attached yet
    resp = client.post(
        f"/benchmark/{pid}/eos-upload",
        files={"narrative": (None, "The rig stood idle during utility diversions, pushing the drilling rates up."),
               "summary": (None, "Standing time drove the rate over-runs."),
               "source_doc": (None, "GE-2026-14-EOS.pdf")},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["narrative"].startswith("The rig stood idle")
    assert body["summary"] and body["source_doc"] == "GE-2026-14-EOS.pdf" and body["provenance"] == "live"
    # reflected on the read endpoint
    assert client.get(f"/benchmark/{pid}/eos").json()["id"] == body["id"]


def test_eos_upload_replaces_not_appends(bench_db):
    pid = _project()
    client.post(f"/benchmark/{pid}/eos-upload", files={"narrative": (None, "first account")})
    client.post(f"/benchmark/{pid}/eos-upload", files={"narrative": (None, "second account")})
    assert client.get(f"/benchmark/{pid}/eos").json()["narrative"] == "second account"


def test_eos_upload_requires_a_narrative(bench_db):
    pid = _project()
    resp = client.post(f"/benchmark/{pid}/eos-upload", files={"narrative": (None, "   ")})
    assert resp.status_code == 400 and "No EOS narrative" in resp.json()["detail"]


def test_eos_pdf_upload_is_gated_off_by_default(bench_db):
    pid = _project()
    resp = client.post(f"/benchmark/{pid}/eos-upload",
                       files={"files": ("eos.pdf", b"%PDF-1.4 fake", "application/pdf")})
    assert resp.status_code == 400 and "EOS file parsing is off" in resp.json()["detail"]


def test_eos_pdf_upload_with_flag_still_offline_in_demo(bench_db, monkeypatch):
    # With the opt-in on, a PDF is still refused in DEMO (fitz is blocked offline) — the
    # narrative-text path is the offline route.
    monkeypatch.setenv("EOS_PDF_PARSE", "true")
    pid = _project()
    resp = client.post(f"/benchmark/{pid}/eos-upload",
                       files={"files": ("eos.pdf", b"%PDF-1.4 fake", "application/pdf")})
    assert resp.status_code == 400 and "live engine" in resp.json()["detail"]


def test_eos_upload_to_unknown_project_404s(bench_db):
    assert client.post("/benchmark/999999/eos-upload",
                       files={"narrative": (None, "x")}).status_code == 404
    assert client.get("/benchmark/999999/eos").status_code == 404
