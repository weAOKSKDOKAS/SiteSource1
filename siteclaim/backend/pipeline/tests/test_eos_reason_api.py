"""EOS reason-suggestions endpoint (Phase P2c) — wired to the gate, offline (DEMO).

The suggestions endpoint proposes; the existing reason POST stays the sole writer. A live
temp DB is set up with one G1 variance record + an attached EOS narrative; DEMO reads the
baked candidate fixture (G1 -> standing_time).
"""

import pytest
from fastapi.testclient import TestClient

from api import app
from db import benchmark as bench, seed, store

client = TestClient(app)

_NARRATIVE = (
    "The rotary drilling rig stood idle for extended periods while utility diversions were "
    "completed, which pushed the achieved rate for the soil drilling item above the tendered rate."
)


@pytest.fixture
def project_with_variance(tmp_path, monkeypatch):
    db = tmp_path / "bench.db"
    seed.build_database(db, profile="live")
    monkeypatch.setenv("SITESOURCE_DB", str(db))
    conn = store.get_connection(db)
    try:
        pid = bench.create_project(conn, name="GI Term Contract", trade="ground_investigation")["id"]
        bench.replace_tender_items(conn, pid, [
            {"item_ref": "G1", "description": "Rotary drilling in soil", "unit": "m",
             "qty": 200.0, "rate": 1200.0, "amount": 240000.0},
        ], source="tender-xlsx")
        bench.replace_actual_items(conn, pid, [
            {"item_ref": "G1", "description": "Rotary drilling in soil", "unit": "m",
             "qty": 200.0, "rate": 1500.0, "amount": 300000.0, "granularity": "item"},
        ], source="actuals-xlsx")
        tid = bench.tender_items(conn, pid)[0]["id"]
        aid = bench.actual_items(conn, pid)[0]["id"]
        bench.confirm_matches(conn, pid, [{"tender_item_id": tid, "actual_item_id": aid, "match_tier": 1}])
    finally:
        conn.close()
    return pid


def test_reason_suggestions_route_registered():
    assert "/benchmark/{project_id}/variance/reason-suggestions" in {r.path for r in app.routes}


def test_suggestions_empty_when_no_eos_attached(project_with_variance):
    pid = project_with_variance
    body = client.get(f"/benchmark/{pid}/variance/reason-suggestions").json()
    assert body["eos_attached"] is False and body["candidates"] == []


def test_suggestions_come_from_the_eos_narrative(project_with_variance):
    pid = project_with_variance
    client.post(f"/benchmark/{pid}/eos-upload", files={"narrative": (None, _NARRATIVE)})
    body = client.get(f"/benchmark/{pid}/variance/reason-suggestions").json()
    assert body["eos_attached"] is True
    g1 = next(c for c in body["candidates"] if c["item_ref"] == "G1")
    assert g1["reason_code"] == "standing_time" and g1["source"] == "reason-from-eos"
    assert g1["snippet"] and g1["record_id"]  # carries evidence + maps to the record


def test_suggestions_are_read_only_and_the_human_still_writes(project_with_variance):
    pid = project_with_variance
    client.post(f"/benchmark/{pid}/eos-upload", files={"narrative": (None, _NARRATIVE)})
    # the record starts untagged; calling suggestions must not write a reason
    before = client.get(f"/benchmark/{pid}/variance").json()[0]
    assert before["reason_code"] == ""
    sugg = client.get(f"/benchmark/{pid}/variance/reason-suggestions").json()["candidates"][0]
    still = client.get(f"/benchmark/{pid}/variance").json()[0]
    assert still["reason_code"] == ""  # GET suggestions did not mutate the record

    # the human confirms the EOS-suggested code (snippet as the note) — the sole writer
    written = client.post(
        f"/benchmark/{pid}/variance/{sugg['record_id']}/reason",
        json={"reason_code": sugg["reason_code"], "note": sugg["snippet"], "tagged_by": "operator"},
    ).json()
    assert written["reason_code"] == "standing_time" and written["reason_note"].startswith("The rotary")


def test_suggestions_reject_unknown_project():
    assert client.get("/benchmark/999999/variance/reason-suggestions").status_code == 404
