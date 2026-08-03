"""Spec for the editable criteria library.

The markdown seeded it; the DB owns it from first access on. The two rules everything below
enforces: **a referenced criterion must stay resolvable forever** (disable, never delete; ids
never reused), and **editing stamps the editor** — the same authorship rule as scope lines and
context cards, because a house position someone changed with nobody's name on it is exactly the
kind of silent drift a review tool exists to prevent.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from client_boq import criteria_loader, criteria_store, store


@pytest.fixture
def client(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setenv("SITESOURCE_WORKDIR", str(tmp_path / "workspace"))
    from api import app

    return TestClient(app)


class TestSeed:
    def test_first_load_matches_the_markdown(self):
        """The DB serves exactly what the file parse served — the switch is invisible."""
        from_file = criteria_loader.load_criteria()
        conn = store.get_conn()
        try:
            from_db = criteria_store.load(conn)
        finally:
            conn.close()
        assert [c.id for c in from_db.criteria] == [c.id for c in from_file.criteria]
        assert [c.id for c in from_db.placeholders] == [c.id for c in from_file.placeholders]
        assert [r.id for r in from_db.threshold_rules] == [r.id for r in from_file.threshold_rules]
        by_id = {c.id: c for c in from_file.criteria}
        for c in from_db.criteria:
            assert c.acceptable_position == by_id[c.id].acceptable_position

    def test_seeding_is_once_only(self):
        """An edit survives further loads — a non-empty table is never reseeded."""
        conn = store.get_conn()
        try:
            criteria_store.load(conn)
            criteria_store.upsert(conn, id="PS-01", actor="r-lam",
                                  acceptable_position="Edited position.")
            again = criteria_store.load(conn)
        finally:
            conn.close()
        edited = next(c for c in again.criteria if c.id == "PS-01")
        assert edited.acceptable_position == "Edited position."


class TestEditing:
    def test_editing_stamps_the_editor(self, client: TestClient):
        resp = client.post("/client-boq/criteria/PS-01",
                           json={"red_flag": "Anything above 5%."},
                           headers={"X-CBOQ-Actor": "r-lam"})
        assert resp.status_code == 200
        row = resp.json()["criterion"]
        assert row["red_flag"] == "Anything above 5%."
        assert row["updated_by"] == "r-lam" and row["updated_at"]

    def test_disabling_keeps_the_row_resolvable(self, client: TestClient):
        client.post("/client-boq/criteria/PS-01", json={"enabled": False})
        payload = client.get("/client-boq/criteria").json()
        # Still in the full list — a past register that references PS-01 must resolve it…
        assert any(c["id"] == "PS-01" for c in payload["criteria"])
        row = next(r for r in payload["rows"] if r["id"] == "PS-01")
        assert row["enabled"] is False
        # …but a future review run no longer checks it.
        conn = store.get_conn()
        try:
            for_review = criteria_store.load(conn, enabled_only=True)
        finally:
            conn.close()
        assert all(c.id != "PS-01" for c in for_review.criteria)

    def test_adding_derives_the_next_id_and_never_reuses(self, client: TestClient):
        first = client.post("/client-boq/criteria",
                            json={"category_id": "PS", "clause_area": "Bonds",
                                  "acceptable_position": "On-demand bonds refused."},
                            headers={"X-CBOQ-Actor": "k-ho"}).json()["criterion"]
        assert first["id"].startswith("PS-")
        client.post(f"/client-boq/criteria/{first['id']}", json={"enabled": False})
        second = client.post("/client-boq/criteria",
                             json={"category_id": "PS", "clause_area": "Warranties",
                                   "acceptable_position": "Standard form only."}).json()["criterion"]
        # The disabled id's number is not reused — it may be stamped on a historical register.
        assert second["id"] != first["id"]
        assert int(second["id"].split("-")[1]) > int(first["id"].split("-")[1])

    def test_an_unknown_category_is_refused(self, client: TestClient):
        assert client.post("/client-boq/criteria",
                           json={"category_id": "XX", "clause_area": "?"}).status_code == 422

    def test_updating_an_unknown_id_404s(self, client: TestClient):
        assert client.post("/client-boq/criteria/ZZ-99",
                           json={"red_flag": "x"}).status_code == 404

    def test_filling_a_placeholder_promotes_it(self, client: TestClient):
        """OK-01 is the empty extension row; giving it a position makes it a real criterion."""
        payload = client.get("/client-boq/criteria").json()
        placeholder_ids = [c["id"] for c in payload["placeholders"]]
        if not placeholder_ids:
            pytest.skip("no placeholder rows in the seeded library")
        target = placeholder_ids[0]
        client.post(f"/client-boq/criteria/{target}",
                    json={"acceptable_position": "Defined at last."})
        after = client.get("/client-boq/criteria").json()
        assert any(c["id"] == target for c in after["criteria"])
        assert all(c["id"] != target for c in after["placeholders"])


class TestReviewIntegration:
    def test_thresholds_ride_along_read_only(self, client: TestClient):
        payload = client.get("/client-boq/criteria").json()
        assert payload["thresholds"], "the threshold table must survive the DB move"
        # No route exists to edit a threshold rule — asserted via the OpenAPI surface.
        from api import app
        paths = app.openapi()["paths"]
        assert "/client-boq/criteria/{criterion_id}" in paths
        assert not any("threshold" in p for p in paths)
