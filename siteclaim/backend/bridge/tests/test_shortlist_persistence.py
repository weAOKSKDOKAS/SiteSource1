"""The shortlist survives a refresh — because the ticks are useless without the list.

`bridge/approvals.py` persists which firms the operator selected, and the tab restores that on
mount. Both shipped, and the shortlist was STILL lost on every refresh: `shortlist` — the candidate
list, not the selection — was React state, written only by `runShortlist`, read by nothing at load,
and stored by no endpoint. After a refresh there was nothing for the restored ticks to land on, so
the operator re-ran a 148-firm screen to get back where they already were.

There is a second, quieter loss in that re-run, pinned below: `runShortlist` filters a restored
selection to the firms the RECOMPUTED list contains, so a firm that no longer makes the new top-k
drops out of the selection without a word. Restoring the list instead of rebuilding it removes that
failure entirely.

A "remount" here is what it is on the wire: a fresh GET of everything the tab reads on mount, with
no memory of the session that wrote it. That is exactly what a browser refresh does.
"""

import pytest
from fastapi.testclient import TestClient

from bridge import shortlist_store
from bridge.identity import bridge_conn

SET_ID = "gi-2026-15"


@pytest.fixture
def client():
    import api

    return TestClient(api.app)


def _shortlist(*firm_ids: str, package: str = "ground_investigation:G") -> dict:
    """A ShortlistSet-shaped payload — only the fields the screen ticks against."""
    return {"per_trade": {package: [
        {"firm": {"firm_id": fid, "name": f"Firm {fid}"}, "score": 0.9,
         "recommended_against": False, "evidence": [], "risk_flags": []}
        for fid in firm_ids
    ]}}


# -- the store ---------------------------------------------------------------------------------------
def test_a_shortlist_round_trips():
    shortlist_store.save_shortlist(SET_ID, _shortlist("F1", "F2"))
    body, created_at = shortlist_store.load_shortlist(SET_ID)

    assert [c["firm"]["firm_id"] for c in body["per_trade"]["ground_investigation:G"]] == ["F1", "F2"]
    assert created_at.endswith("+00:00")


def test_a_set_that_has_never_been_screened_reads_back_none():
    body, created_at = shortlist_store.load_shortlist("never-screened")
    assert body is None and created_at == ""


def test_a_re_run_replaces_rather_than_accumulates():
    shortlist_store.save_shortlist(SET_ID, _shortlist("F1", "F2"))
    shortlist_store.save_shortlist(SET_ID, _shortlist("F3"))

    body, _at = shortlist_store.load_shortlist(SET_ID)
    assert [c["firm"]["firm_id"] for c in body["per_trade"]["ground_investigation:G"]] == ["F3"]
    conn = bridge_conn()
    try:
        n = conn.execute("SELECT COUNT(*) AS n FROM bridge_shortlists WHERE set_id = ?",
                         (SET_ID,)).fetchone()["n"]
    finally:
        conn.close()
    assert n == 1                                   # one row per set — a re-run is a new answer


def test_two_sets_do_not_see_each_other():
    shortlist_store.save_shortlist(SET_ID, _shortlist("F1"))
    shortlist_store.save_shortlist("nd-2025-04", _shortlist("F9"))

    a, _ = shortlist_store.load_shortlist(SET_ID)
    b, _ = shortlist_store.load_shortlist("nd-2025-04")
    assert a["per_trade"]["ground_investigation:G"][0]["firm"]["firm_id"] == "F1"
    assert b["per_trade"]["ground_investigation:G"][0]["firm"]["firm_id"] == "F9"


def test_a_corrupt_row_reads_as_not_screened_rather_than_raising():
    """"Run it again" is what an absent row means too, and raising would break a tab mid-load."""
    conn = bridge_conn()
    try:
        shortlist_store.ensure_tables(conn)
        conn.execute(
            "INSERT INTO bridge_shortlists (set_id, shortlist_json, created_at) VALUES (?, ?, ?)",
            ("broken", "{not json", "2026-08-06T00:00:00+00:00"))
        conn.commit()
    finally:
        conn.close()
    body, _at = shortlist_store.load_shortlist("broken")
    assert body is None


# -- the endpoints -----------------------------------------------------------------------------------
def test_the_endpoints_round_trip(client):
    r = client.post(f"/bridge/{SET_ID}/shortlist", json={"shortlist": _shortlist("F1", "F2")})
    assert r.status_code == 200 and r.json()["stored"] is True

    body = client.get(f"/bridge/{SET_ID}/shortlist").json()
    assert body["set_id"] == SET_ID
    assert [c["firm"]["firm_id"] for c in body["shortlist"]["per_trade"]["ground_investigation:G"]] \
        == ["F1", "F2"]
    assert body["created_at"]


def test_never_screened_is_null_not_a_404(client):
    r = client.get("/bridge/fresh-set/shortlist")
    assert r.status_code == 200
    assert r.json()["shortlist"] is None and r.json()["created_at"] == ""


def test_both_endpoints_are_registered():
    import api

    assert "/bridge/{set_id}/shortlist" in api.app.openapi()["paths"]


# -- the whole point: a remount finds the list AND its ticks -------------------------------------------
def test_a_remount_finds_the_shortlist_and_its_selection(client):
    """The refresh, on the wire: write both, then read everything the tab reads on mount."""
    client.post(f"/bridge/{SET_ID}/shortlist", json={"shortlist": _shortlist("F1", "F2", "F3")})
    client.post(f"/bridge/{SET_ID}/approvals",
                json={"approvals": {"ground_investigation:G": ["F2"]}})

    # --- a browser refresh: nothing is remembered, everything is re-read ---
    listed = client.get(f"/bridge/{SET_ID}/shortlist").json()["shortlist"]
    ticked = client.get(f"/bridge/{SET_ID}/approvals").json()["approvals"]

    candidates = [c["firm"]["firm_id"] for c in listed["per_trade"]["ground_investigation:G"]]
    assert candidates == ["F1", "F2", "F3"]         # the screen the operator worked
    assert ticked == {"ground_investigation:G": ["F2"]}
    # And the tick lands on a candidate that is actually on screen — the whole point of restoring
    # the list rather than recomputing one.
    assert set(ticked["ground_investigation:G"]) <= set(candidates)


def test_the_selection_survives_a_remount_even_for_a_firm_a_re_run_would_drop(client):
    """The quieter loss the re-run caused, and why restoring beats recomputing.

    `runShortlist` filters a restored selection to the firms the recomputed list contains. A firm
    selected today that does not make tomorrow's top-k vanishes from the selection with no word.
    Restoring the stored list keeps it, because the list it was ticked against is the list.
    """
    client.post(f"/bridge/{SET_ID}/shortlist", json={"shortlist": _shortlist("F1", "F-EDGE")})
    client.post(f"/bridge/{SET_ID}/approvals",
                json={"approvals": {"ground_investigation:G": ["F-EDGE"]}})

    listed = client.get(f"/bridge/{SET_ID}/shortlist").json()["shortlist"]
    ticked = client.get(f"/bridge/{SET_ID}/approvals").json()["approvals"]
    assert "F-EDGE" in [c["firm"]["firm_id"] for c in listed["per_trade"]["ground_investigation:G"]]
    assert ticked["ground_investigation:G"] == ["F-EDGE"]


def test_storing_a_shortlist_approves_and_sends_nothing():
    """A candidate list is a Layer-1 answer, not a decision. Asserted over the module's imports:
    if a future edit reaches the mailer, the draft composer or a gate flag, this fails first."""
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(shortlist_store))
    reached = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            reached.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            reached.add(node.module or "")
    assert reached == {"__future__", "datetime", "json", "sqlite3", "typing", "bridge.identity"}
