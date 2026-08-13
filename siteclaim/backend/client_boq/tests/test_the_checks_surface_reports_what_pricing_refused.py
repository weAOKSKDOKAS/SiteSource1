"""The aggregating surfaces agree with the engine — closures found by the alignment recheck.

Phase 1 put `loading_unapplied` on the /priced payload and Phase 2 gave the ask two return paths.
The recheck found the seams: /checks (the surface that COUNTS flags) never saw the new kind
because `run_checks` cannot re-derive it without the loadings map; the ask's no-ground
short-circuit returned a payload missing three keys the frontend type declares required; the
discussion badge could keep wearing green after its condition was rejected; and the ground's
condition window kept the OLDEST 40 while the log keeps the newest 12.

Each test here pins the closed seam, not the feature — the features have their own files.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

BASE = "/client-boq"
SET = "technopole-gi"


@pytest.fixture
def client(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setenv("SITESOURCE_WORKDIR", str(tmp_path / "ws"))
    from api import app

    return TestClient(app)


def _import_bill(client, tmp_path) -> None:
    pytest.importorskip("openpyxl")
    from client_boq.tests._bqfixture import build_bill_workbook

    path = build_bill_workbook(tmp_path / "bq-0.xlsx", 0)
    with open(path, "rb") as fh:
        assert client.post(
            f"{BASE}/boq/import", data={"set_id": SET},
            files={"file": (path.name, fh.read(), "application/vnd.ms-excel")},
        ).status_code == 200


def _seed_register(client) -> None:
    from client_boq import models, store

    register = models.DepartureRegister(set_id=SET, items=[models.DepartureItem(
        item=1, clause="GCC 12", criterion_id="CRIT-LD-01",
        clause_area="Liquidated damages",
        rationale="LDs are 0.1% per day, capped at 10%.", cited_text="clause 12 text")])
    conn = store.get_conn()
    try:
        store.save_register(conn, register)
    finally:
        conn.close()


class TestChecksCountsTheRefusedLoading:
    def test_a_load_routed_onto_an_unpriced_item_reaches_the_checks_counts(self, client, tmp_path):
        """The nastiest refusal shape, seen from the aggregating surface: the /priced payload
        already flagged it; now /checks — the screen a reviewer reads — counts it too."""
        _import_bill(client, tmp_path)
        ref = next(i["full_ref"] for i in client.get(f"{BASE}/boq/{SET}").json()["items"]
                   if not i["is_parent"] and not i["pre_priced"] and i["qty"])
        assert client.post(f"{BASE}/price/sweep", headers={"X-CBOQ-Actor": "SW"},
                           json={"set_id": SET, "key": "platforms", "label": "Class B platforms",
                                 "amount": 50000.0, "route": "load",
                                 "target_ref": ref}).status_code == 200
        body = client.get(f"{BASE}/boq/{SET}/checks").json()
        assert body["counts"].get("loading_unapplied") == 1, (
            "price_bill refused the loading (no rate for it to live inside) — the refusal must "
            "reach the surface that counts refusals")
        assert body["counts"].get("unpriced_item", 0) >= 1, "and the item is still unpriced"

    def test_the_kinds_both_surfaces_emit_are_not_double_counted(self, client, tmp_path):
        """The merge takes ONLY loading_unapplied from the priced flags. unpriced_item is emitted
        by run_checks itself — merging all priced flags would count it twice."""
        _import_bill(client, tmp_path)
        body = client.get(f"{BASE}/boq/{SET}/checks").json()
        priced = client.get(f"{BASE}/boq/{SET}/priced").json()
        unpriced_refs = {f["item_id"] for f in priced["flags"] if f["kind"] == "unpriced_item"}
        assert body["counts"].get("unpriced_item", 0) == len(unpriced_refs)


class TestTheAskResponseIsOneShape:
    def test_the_no_ground_refusal_carries_every_key_the_grounded_path_does(self, client):
        """The frontend type declares figures/log_seq/asked_by required; the refusal path used to
        omit all three — `Object.keys(reply.figures)` was a TypeError waiting on that branch."""
        reply = client.post(f"{BASE}/costing/ask", headers={"X-CBOQ-Actor": "SW"},
                            json={"set_id": SET, "question": "anything?"}).json()
        assert reply["cannot_answer"]
        assert reply["figures"] == {}
        assert reply["log_seq"] == 0, "0 = deliberately not logged; seq is 1-based on purpose"
        assert reply["asked_by"] == "SW"


class TestARejectedConditionCannotWearAGreenBadge:
    def test_the_log_reports_the_born_conditions_current_status(self, client):
        _seed_register(client)
        reply = client.post(f"{BASE}/costing/ask", headers={"X-CBOQ-Actor": "SW"},
                            json={"set_id": SET, "question": "platform needed?"}).json()
        client.post(f"{BASE}/costing/conditions", headers={"X-CBOQ-Actor": "SW"},
                    json={"set_id": SET, "condition_id": "c-reject",
                          "text": "hillside platform before any rig stands",
                          "born_of_seq": reply["log_seq"]})
        client.post(f"{BASE}/costing/conditions/decide", headers={"X-CBOQ-Actor": "SW"},
                    json={"set_id": SET, "condition_id": "c-reject", "status": "rejected"})
        entry = client.get(f"{BASE}/costing/{SET}/log").json()["entries"][0]
        assert entry["became_condition"] == "c-reject"
        assert entry["became_status"] == "rejected"

    def test_two_conditions_born_of_one_discussion_keep_the_first_link(self, client):
        """rowid order — the first condition recorded is the one closest to the exchange."""
        _seed_register(client)
        reply = client.post(f"{BASE}/costing/ask",
                            json={"set_id": SET, "question": "q"}).json()
        for cid in ("c-first", "c-second"):
            client.post(f"{BASE}/costing/conditions",
                        json={"set_id": SET, "condition_id": cid, "text": cid,
                              "born_of_seq": reply["log_seq"]})
        entry = client.get(f"{BASE}/costing/{SET}/log").json()["entries"][0]
        assert entry["became_condition"] == "c-first"


class TestTheGroundKeepsTheNewestConditions:
    def test_the_window_drops_the_oldest_not_the_latest(self, client):
        """A memory that forgets what was decided LAST WEEK while remembering the first forty
        entries ever written is backwards. The window now matches the log's newest-N shape."""
        _seed_register(client)
        for n in range(45):
            client.post(f"{BASE}/costing/conditions",
                        json={"set_id": SET, "condition_id": f"c-{n:02d}", "text": f"condition {n}"})
        from client_boq import store
        from client_boq.router import _ground_for

        conn = store.get_conn()
        try:
            sources = _ground_for(conn, SET).sources
        finally:
            conn.close()
        assert "condition:c-44" in sources, "the newest condition must be in the ground"
        assert "condition:c-00" not in sources, "the oldest past the window is the one dropped"
