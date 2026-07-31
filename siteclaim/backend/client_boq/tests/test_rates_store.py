"""Spec for the DB-backed rate book — the swap ``rates.py`` declared itself the seam for.

The contract being protected: ``load_rates()`` returns the same list of ``RateRow`` it always
did, from a different reader, and NOTHING downstream changes. Plus the desk rules: rates archive
rather than delete (an archived rate resolves ``missing_rate``, never a stale price), and a
number someone changed by hand stops claiming to be the seed's.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from client_boq import rates as rates_mod
from client_boq import rates_store, store


@pytest.fixture
def client(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setenv("SITESOURCE_WORKDIR", str(tmp_path / "workspace"))
    from api import app

    return TestClient(app)


class TestSeam:
    def test_the_db_book_matches_the_csv_book(self):
        """The swap is invisible: same ids, same rates, same order."""
        from_csv = rates_mod.load_rates_csv()
        from_db = rates_mod.load_rates()          # no path → the DB source
        csv_index = rates_mod.rate_index(from_csv)
        assert [r.rate_id for r in from_db] == list(csv_index)   # first-wins order
        for r in from_db:
            assert r.rate == csv_index[r.rate_id].rate

    def test_an_explicit_path_still_reads_that_csv(self, tmp_path):
        p = tmp_path / "book.csv"
        p.write_text(
            "rate_id,category,code,description,unit,rate,currency,source,notes\n"
            "TST-1,labour,TST-1,Test gang,hr,123,HKD,test,\n",
            encoding="utf-8",
        )
        rows = rates_mod.load_rates(p)
        assert [r.rate_id for r in rows] == ["TST-1"] and rows[0].rate == 123.0

    def test_an_edit_survives_and_feeds_the_estimate_reader(self):
        conn = store.get_conn()
        try:
            rates_store.upsert(conn, rate_id="LAB-CONC", actor="r-lam", rate=700.0)
        finally:
            conn.close()
        book = {r.rate_id: r for r in rates_mod.load_rates()}
        assert book["LAB-CONC"].rate == 700.0


class TestRoutes:
    def test_the_book_is_served_with_metadata(self, client: TestClient):
        payload = client.get("/client-boq/rates").json()
        assert payload["count"] > 0
        assert payload["seed_duplicates"] == []      # the seed file is clean
        assert {"labour", "plant", "material", "subcontract", "productivity"} <= set(payload["categories"])

    def test_editing_stamps_who_and_disowns_the_seed(self, client: TestClient):
        row = client.post("/client-boq/rates/LAB-CONC", json={"rate": 725},
                          headers={"X-CBOQ-Actor": "k-ho"}).json()["rate"]
        assert row["rate"] == 725.0
        assert row["updated_by"] == "k-ho"
        assert row["source"] == "user"               # no longer the seed's number

    def test_adding_refuses_a_duplicate_id(self, client: TestClient):
        assert client.post("/client-boq/rates",
                           json={"rate_id": "LAB-CONC", "rate": 1}).status_code == 409

    def test_adding_requires_a_numeric_rate(self, client: TestClient):
        assert client.post("/client-boq/rates",
                           json={"rate_id": "NEW-1"}).status_code == 422

    def test_archiving_is_not_deleting(self, client: TestClient):
        resp = client.delete("/client-boq/rates/PLT-CRANE",
                             headers={"X-CBOQ-Actor": "r-lam"})
        assert resp.status_code == 200
        assert "missing_rate" in resp.json()["note"]
        # Gone from the live book…
        live_ids = [r.rate_id for r in rates_mod.load_rates()]
        assert "PLT-CRANE" not in live_ids
        # …still on the record with its metadata.
        rows = client.get("/client-boq/rates").json()["rows"]
        archived = next(r for r in rows if r["rate_id"] == "PLT-CRANE")
        assert archived["archived"] is True and archived["updated_by"] == "r-lam"

    def test_an_archived_rate_prices_as_missing(self, client: TestClient):
        """The consequence stated in the note, proven: the cost build-up flags it."""
        client.delete("/client-boq/rates/MAT-C40")
        from client_boq.estimate import s03_cost_buildup
        from client_boq.models import EstimateSchedule, ResourceLine, ScheduleItem
        schedule = EstimateSchedule(items=[ScheduleItem(
            item_id="A1", description="Concrete supply", category="direct", unit="m3",
            lines=[ResourceLine(description="C40 supply", resource_ref="MAT-C40", qty=10, unit="m3")],
        )])
        activities = s03_cost_buildup.build_cost(schedule, rates_mod.load_rates())
        line = activities[0].lines[0]
        assert line.rate_source == "missing" and line.amount == 0.0

    def test_unknown_rate_404s(self, client: TestClient):
        assert client.post("/client-boq/rates/NOPE", json={"rate": 1}).status_code == 404
        assert client.delete("/client-boq/rates/NOPE").status_code == 404
