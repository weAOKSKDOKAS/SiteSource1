"""Spec for the close date as a FINDING.

The desk card's "days to close" has to come from somewhere, and the chain is: the interpreter
quotes the deadline clause verbatim (a citation), deterministic code parses the quote (a
measurement), and a person confirms by hand when the parse honestly refuses. The failure mode
is always ``not_found`` — a wrong deadline silently shown is the one failure this feature
exists to prevent.

DEMO is the sharp edge: the interpret fixtures describe the sample tender, not the upload, so a
date derived from them and labelled "READ FROM COT" would be fabrication. DEMO always lands on
``not_found`` and the confirm-by-hand path (the same rule as CLAUDE.md trap 9, applied here).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from client_boq.ingest.close_date import parse_close_date

fitz = pytest.importorskip("fitz")  # PyMuPDF


# ---------------------------------------------------------------------------
# The parser — conservative on purpose
# ---------------------------------------------------------------------------
class TestParser:
    @pytest.mark.parametrize("quote,want", [
        # Unambiguous formats parse.
        ("no later than 2:00 pm on 14 August 2026", "2026-08-14"),
        ("14th August, 2026", "2026-08-14"),
        ("14 Aug 2026", "2026-08-14"),
        ("Tenders close August 14, 2026 at noon", "2026-08-14"),
        ("submission by 2026-08-14", "2026-08-14"),
        # The same date written twice is still one date.
        ("by 14 August 2026 (2026-08-14)", "2026-08-14"),
    ])
    def test_unambiguous_dates_parse(self, quote, want):
        assert parse_close_date(quote) == want

    @pytest.mark.parametrize("quote", [
        # Numeric forms refuse: day-first and month-first disagree and a deadline has no safe default.
        "by 04/05/2026",
        "on 4.5.2026",
        # Two distinct dates refuse: choosing one is an interpretation, and those belong to people.
        "on 14 August 2026 or 15 August 2026",
        # Nothing to parse.
        "within 30 business days of the award",
        "",
    ])
    def test_ambiguity_refuses_rather_than_guesses(self, quote):
        assert parse_close_date(quote) is None


# ---------------------------------------------------------------------------
# Derivation and confirmation, through the API
# ---------------------------------------------------------------------------
@pytest.fixture
def client(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setenv("SITESOURCE_WORKDIR", str(tmp_path / "workspace"))
    from api import app

    return TestClient(app)


def _binder(pages: int = 12) -> bytes:
    doc = fitz.open()
    for i in range(1, pages + 1):
        doc.new_page().insert_text((72, 100), f"Binder page {i} of {pages}", fontsize=11)
    doc.set_toc([
        [1, "Conditions of Tender", 1],
        [1, "Scope of Works", 5],
        [1, "Pricing Schedule", 9],
    ])
    data = doc.tobytes()
    doc.close()
    return data


@pytest.fixture
def split_set(client: TestClient) -> tuple[TestClient, str]:
    resp = client.post(
        "/client-boq/ingest/upload",
        data={"project_name": "close-date-demo"},
        files={"files": ("binder.pdf", _binder(), "application/pdf")},
    )
    set_id = resp.json()["result"]["set_id"]
    client.post("/client-boq/ingest/manifest/approve", json={"set_id": set_id})
    client.post("/client-boq/ingest/split", json={"set_id": set_id})
    return client, set_id


class TestDerivation:
    def test_demo_is_honest_about_not_reading(self, split_set):
        """In DEMO the cards are fixtures about a different tender; a derived date would be a lie."""
        client, set_id = split_set
        row = next(s for s in client.get("/client-boq/sets").json()["sets"]
                   if s["set_id"] == set_id)
        assert row["meta"]["close_date_status"] == "not_found"
        assert row["meta"]["close_date"] == ""            # nothing invented
        assert row["meta"]["close_date_quote"] == ""      # no citation claimed

    def test_before_split_the_status_is_reading(self, client: TestClient):
        resp = client.post(
            "/client-boq/ingest/upload",
            data={"project_name": "close-date-fresh"},
            files={"files": ("binder.pdf", _binder(), "application/pdf")},
        )
        set_id = resp.json()["result"]["set_id"]
        row = next(s for s in client.get("/client-boq/sets").json()["sets"]
                   if s["set_id"] == set_id)
        # No parts yet: the backfill leaves it alone, the card says READING THE DATE…
        assert row["meta"]["close_date_status"] == "reading"


class TestConfirmation:
    def test_a_person_confirms_by_hand(self, split_set):
        client, set_id = split_set
        resp = client.post(f"/client-boq/sets/{set_id}/close-date",
                           json={"date": "2026-08-14"},
                           headers={"X-CBOQ-Actor": "r-lam"})
        assert resp.status_code == 200
        meta = resp.json()["meta"]
        assert meta["close_date"] == "2026-08-14"
        assert meta["close_date_status"] == "confirmed"
        assert meta["close_date_confirmed_by"] == "r-lam"

    def test_confirmation_survives_rederivation(self, split_set):
        """A person read the clause; a machine re-run does not outrank them."""
        client, set_id = split_set
        client.post(f"/client-boq/sets/{set_id}/close-date", json={"date": "2026-08-14"})
        from client_boq import store
        from client_boq.ingest import close_date as close_date_mod
        conn = store.get_conn()
        try:
            assert close_date_mod.derive(conn, set_id) is None   # refuses to touch confirmed
            meta = store.load_set_meta(conn, set_id)
        finally:
            conn.close()
        assert meta["close_date"] == "2026-08-14"
        assert meta["close_date_status"] == "confirmed"

    def test_a_non_iso_date_is_refused(self, split_set):
        client, set_id = split_set
        assert client.post(f"/client-boq/sets/{set_id}/close-date",
                           json={"date": "14/08/2026"}).status_code == 422

    def test_the_query_cutoff_rides_along(self, split_set):
        client, set_id = split_set
        meta = client.post(f"/client-boq/sets/{set_id}/close-date",
                           json={"date": "2026-08-14", "query_cutoff": "2026-08-07"}).json()["meta"]
        assert meta["query_cutoff"] == "2026-08-07"

    def test_an_expired_cutoff_with_open_queries_blocks(self, split_set):
        client, set_id = split_set
        client.post("/client-boq/rfi", json={
            "set_id": set_id, "origin": "manual",
            "question": "Please confirm the retention release terms.",
        })
        client.post(f"/client-boq/sets/{set_id}/close-date",
                    json={"date": "2020-02-01", "query_cutoff": "2020-01-01"})
        row = next(s for s in client.get("/client-boq/sets").json()["sets"]
                   if s["set_id"] == set_id)
        assert row["counts"]["open_rfis"] >= 1
        assert row["blocked"] is True   # a question that can no longer be asked
