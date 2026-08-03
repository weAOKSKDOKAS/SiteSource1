"""Phase 3 — the bill is chosen by a human, never by the AI-written category.

``PartSpec.category`` comes from an interpretation stage. It PROPOSES; a person CONFIRMS. And the
confirmation is a SET: a tender can carry a bill of quantities and a separate daywork or
provisional-items schedule, both priceable, so two pricing parts is a choice to make rather than
an error to raise.
"""

import pytest
from fastapi.testclient import TestClient

from bridge import parts
from bridge.identity import bridge_conn


@pytest.fixture
def client():
    import api

    return TestClient(api.app)


def _one_pricing_set(make_set, part_spec):
    make_set("ge-2026-14", "GE/2026/14", [
        part_spec(1, "CT", "Conditions of Tender", "tender-instructions"),
        part_spec(2, "SR", "Schedule of Rates", "pricing"),
        part_spec(3, "PS", "Particular Specification", "specifications"),
    ])


# -- proposal ---------------------------------------------------------------------------------
def test_the_single_pricing_part_is_proposed(make_set, part_spec):
    _one_pricing_set(make_set, part_spec)
    body = parts.bq_candidates("ge-2026-14")

    assert body["proposed"] == ["02-sr"]
    assert [p["part_id"] for p in body["parts"]] == ["01-ct", "02-sr", "03-ps"]  # document order
    assert {p["part_id"]: p["proposed"] for p in body["parts"]} == {
        "01-ct": False, "02-sr": True, "03-ps": False,
    }
    assert body["confirmed"] == []                       # proposing is not confirming


def test_every_pricing_part_is_proposed_and_two_is_not_an_error(make_set, part_spec):
    # A BQ plus a daywork schedule: both priceable. The gate is the human's choice of the set,
    # so this must come back as two proposals, not a raised exception.
    make_set("ge-2026-14", "GE/2026/14", [
        part_spec(1, "BQ", "Bills of Quantities", "pricing"),
        part_spec(2, "DW", "Daywork Schedule", "pricing"),
        part_spec(3, "PS", "Particular Specification", "specifications"),
    ])
    body = parts.bq_candidates("ge-2026-14")

    assert body["proposed"] == ["01-bq", "02-dw"]
    assert "2 pricing parts" in body["message"]


def test_no_pricing_part_proposes_nothing_and_says_so(make_set, part_spec):
    # Degrade honestly: return the full list with nothing proposed. Never guess from the title —
    # "Schedule of Rates" in a part's name is exactly the kind of guess that produces a phantom bill.
    make_set("ge-2026-14", "GE/2026/14", [
        part_spec(1, "CT", "Conditions of Tender", "tender-instructions"),
        part_spec(2, "SR", "Schedule of Rates", "other"),      # title looks like a bill; category does not
    ])
    body = parts.bq_candidates("ge-2026-14")

    assert body["proposed"] == []
    assert len(body["parts"]) == 2                        # the full list is still offered
    assert "No part is categorised 'pricing'" in body["message"]


def test_candidates_expose_what_a_human_needs_to_choose(make_set, part_spec):
    make_set("ge-2026-14", "GE/2026/14",
             [part_spec(1, "SR", "Schedule of Rates", "pricing", start=5, end=62, scanned=True)],
             pdf_paths={"01-sr": ""})
    part = parts.bq_candidates("ge-2026-14")["parts"][0]

    assert part["pages"] == 58 and part["scanned"] is True
    assert part["has_pdf"] is False                       # no cut pdf -> it can contribute no text


# -- confirmation -----------------------------------------------------------------------------
def test_a_confirmation_persists_and_is_read_back_in_document_order(make_set, part_spec):
    make_set("ge-2026-14", "GE/2026/14", [
        part_spec(1, "BQ", "Bills of Quantities", "pricing"),
        part_spec(2, "PS", "Particular Specification", "specifications"),
        part_spec(3, "DW", "Daywork Schedule", "pricing"),
    ])
    # Confirmed in reverse order on purpose — storage must not preserve the click order.
    parts.confirm_bill_parts("ge-2026-14", ["03-dw", "01-bq"])

    conn = bridge_conn()
    try:
        assert parts.confirmed_bill_parts(conn, "ge-2026-14") == ["01-bq", "03-dw"]
    finally:
        conn.close()
    assert parts.bq_candidates("ge-2026-14")["confirmed"] == ["01-bq", "03-dw"]


def test_a_confirmation_for_an_unknown_part_is_rejected(make_set, part_spec):
    _one_pricing_set(make_set, part_spec)
    with pytest.raises(ValueError, match="Unknown part id"):
        parts.confirm_bill_parts("ge-2026-14", ["99-nope"])

    conn = bridge_conn()
    try:
        assert parts.confirmed_bill_parts(conn, "ge-2026-14") == []   # nothing was stored
    finally:
        conn.close()


def test_a_partly_unknown_confirmation_stores_nothing_at_all(make_set, part_spec):
    # All-or-nothing: storing the valid half would silently shrink the bill the human confirmed.
    _one_pricing_set(make_set, part_spec)
    with pytest.raises(ValueError, match="Unknown part id"):
        parts.confirm_bill_parts("ge-2026-14", ["02-sr", "99-nope"])

    conn = bridge_conn()
    try:
        assert parts.confirmed_bill_parts(conn, "ge-2026-14") == []
    finally:
        conn.close()


def test_an_empty_confirmation_is_refused(make_set, part_spec):
    _one_pricing_set(make_set, part_spec)
    with pytest.raises(ValueError, match="at least one bill part"):
        parts.confirm_bill_parts("ge-2026-14", [])


def test_reconfirming_replaces_rather_than_accumulates(make_set, part_spec):
    make_set("ge-2026-14", "GE/2026/14", [
        part_spec(1, "BQ", "Bills of Quantities", "pricing"),
        part_spec(2, "DW", "Daywork Schedule", "pricing"),
    ])
    parts.confirm_bill_parts("ge-2026-14", ["01-bq", "02-dw"])
    parts.confirm_bill_parts("ge-2026-14", ["02-dw"])          # changed their mind

    conn = bridge_conn()
    try:
        assert parts.confirmed_bill_parts(conn, "ge-2026-14") == ["02-dw"]
        n = conn.execute(
            "SELECT COUNT(*) AS n FROM bridge_bill_parts WHERE set_id = ?", ("ge-2026-14",)
        ).fetchone()["n"]
        assert n == 1                                          # UNIQUE(set_id, part_id) holds
    finally:
        conn.close()


def test_confirming_registers_the_umbrella_and_writes_no_client_boq_row(make_set, part_spec):
    _one_pricing_set(make_set, part_spec)
    conn = bridge_conn()
    try:
        before = {
            t: conn.execute(f"SELECT COUNT(*) AS n FROM {t}").fetchone()["n"]
            for (t,) in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'client_boq_%'"
            ).fetchall()
        }
    finally:
        conn.close()

    parts.confirm_bill_parts("ge-2026-14", ["02-sr"])

    conn = bridge_conn()
    try:
        from db import project as uproject

        assert uproject.get(conn, "ge-2026-14") is not None     # umbrella registered on first touch
        after = {t: conn.execute(f"SELECT COUNT(*) AS n FROM {t}").fetchone()["n"] for t in before}
        assert after == before                                  # client_boq untouched
    finally:
        conn.close()


def test_a_confirmation_orphaned_by_a_resplit_is_surfaced_not_dropped(make_set, part_spec):
    make_set("ge-2026-14", "GE/2026/14", [
        part_spec(1, "BQ", "Bills of Quantities", "pricing"),
        part_spec(2, "DW", "Daywork Schedule", "pricing"),
    ])
    parts.confirm_bill_parts("ge-2026-14", ["01-bq", "02-dw"])

    # The manifest is edited and re-split: the daywork part no longer exists.
    from client_boq import store as cb_store

    conn = cb_store.get_conn()
    try:
        cb_store.save_parts(conn, "ge-2026-14", [
            part_spec(1, "BQ", "Bills of Quantities", "pricing"),
        ], {})
    finally:
        conn.close()

    body = parts.bq_candidates("ge-2026-14")
    assert body["stale_confirmed"] == ["02-dw"]                  # visible, not silently discarded
    assert "no longer exist" in body["message"]
    assert body["confirmed"] == ["01-bq"]


# -- the endpoints ----------------------------------------------------------------------------
def test_the_candidates_endpoint_returns_the_proposal(client, make_set, part_spec):
    _one_pricing_set(make_set, part_spec)
    resp = client.get("/bridge/ge-2026-14/bq-candidates")
    assert resp.status_code == 200
    assert resp.json()["proposed"] == ["02-sr"]


def test_the_candidates_endpoint_404s_for_a_set_with_no_parts(client):
    resp = client.get("/bridge/never-ingested/bq-candidates")
    assert resp.status_code == 404
    assert "ingest" in resp.json()["detail"].lower()             # says how to fix it


def test_the_confirm_endpoint_persists_and_rejects_bad_input(client, make_set, part_spec):
    _one_pricing_set(make_set, part_spec)

    ok = client.post("/bridge/ge-2026-14/bq-part", json={"part_ids": ["02-sr"]})
    assert ok.status_code == 200 and ok.json()["confirmed"] == ["02-sr"]

    bad = client.post("/bridge/ge-2026-14/bq-part", json={"part_ids": ["01-ct", "99-nope"]})
    assert bad.status_code == 400 and "Unknown part id" in bad.json()["detail"]

    empty = client.post("/bridge/ge-2026-14/bq-part", json={"part_ids": []})
    assert empty.status_code == 400

    missing = client.post("/bridge/never-ingested/bq-part", json={"part_ids": ["01-x"]})
    assert missing.status_code == 404
