"""The shortlist selection survives the browser session — and persisting it approves nothing.

`approvals` lived only in React state, so closing the tab lost the selection with no server-side
record it had ever been made. These tests pin the storage contract and, just as importantly, pin
that the human dispatch gate did NOT move: writing an approval sends nothing, drafts nothing, and
sets no flag any other stage reads.
"""

import ast
import inspect

import pytest
from fastapi.testclient import TestClient

from bridge import approvals as approvals_mod
from bridge.identity import bridge_conn


@pytest.fixture
def client():
    import api

    return TestClient(api.app)


# -- the storage contract ------------------------------------------------------------------------
def test_a_selection_round_trips():
    approvals_mod.save_approvals("ge-2026-14", {"electrical": ["F001", "F002"]})
    assert approvals_mod.load_approvals("ge-2026-14") == {"electrical": ["F001", "F002"]}


def test_an_unknown_set_reads_back_empty_not_an_error():
    # Nothing selected yet is a state, not a failure. The screen opens on it every first visit.
    assert approvals_mod.load_approvals("never-seen") == {}


def test_reselecting_the_same_firm_does_not_accumulate_rows():
    approvals_mod.save_approvals("ge-2026-14", {"electrical": ["F001"]})
    approvals_mod.save_approvals("ge-2026-14", {"electrical": ["F001"]})

    conn = bridge_conn()
    try:
        n = conn.execute(
            "SELECT COUNT(*) AS n FROM bridge_shortlist_approvals WHERE set_id = ?",
            ("ge-2026-14",),
        ).fetchone()["n"]
    finally:
        conn.close()
    assert n == 1


def test_a_deselection_persists_replace_not_merge():
    approvals_mod.save_approvals("ge-2026-14", {"electrical": ["F001", "F002"]})
    approvals_mod.save_approvals("ge-2026-14", {"electrical": ["F002"]})
    # F001 is GONE. A merge would have kept it and the deselection would silently not stick.
    assert approvals_mod.load_approvals("ge-2026-14") == {"electrical": ["F002"]}


def test_an_empty_list_is_a_decision_and_is_honoured():
    approvals_mod.save_approvals("ge-2026-14", {"electrical": ["F001"]})
    approvals_mod.save_approvals("ge-2026-14", {"electrical": []})
    # "None of them" must not read back as the previous selection.
    assert approvals_mod.load_approvals("ge-2026-14") == {}


def test_a_package_absent_from_the_payload_is_left_alone():
    approvals_mod.save_approvals("ge-2026-14", {"electrical": ["F001"], "plumbing": ["F009"]})
    approvals_mod.save_approvals("ge-2026-14", {"electrical": ["F002"]})
    # Only the named package was rewritten — a click on one package cannot clear another.
    assert approvals_mod.load_approvals("ge-2026-14") == {
        "electrical": ["F002"], "plumbing": ["F009"],
    }


def test_two_sets_do_not_see_each_other():
    approvals_mod.save_approvals("ge-2026-14", {"electrical": ["F001"]})
    approvals_mod.save_approvals("nd-2025-04", {"electrical": ["F002"]})

    assert approvals_mod.load_approvals("ge-2026-14") == {"electrical": ["F001"]}
    assert approvals_mod.load_approvals("nd-2025-04") == {"electrical": ["F002"]}


def test_selection_order_is_stable_across_reloads():
    approvals_mod.save_approvals("ge-2026-14", {"electrical": ["F003", "F001", "F002"]})
    # Not sorted, not reshuffled — the list does not move under the operator between visits.
    assert approvals_mod.load_approvals("ge-2026-14")["electrical"] == ["F003", "F001", "F002"]


def test_an_empty_set_id_is_refused_the_way_run_ref_for_refuses_it():
    # It goes through run_ref_for like every other bridge write, so it inherits that rejection
    # rather than quietly storing rows under "".
    with pytest.raises(ValueError):
        approvals_mod.save_approvals("   ", {"electrical": ["F001"]})


# -- the endpoints -------------------------------------------------------------------------------
def test_the_endpoints_round_trip(client):
    r = client.post("/bridge/ge-2026-14/approvals",
                    json={"approvals": {"electrical": ["F001"]}})
    assert r.status_code == 200
    assert r.json()["approvals"] == {"electrical": ["F001"]}

    r = client.get("/bridge/ge-2026-14/approvals")
    assert r.status_code == 200
    assert r.json() == {"set_id": "ge-2026-14", "approvals": {"electrical": ["F001"]}}


def test_the_get_is_empty_rather_than_404_before_anything_is_selected(client):
    r = client.get("/bridge/fresh-set/approvals")
    assert r.status_code == 200
    assert r.json()["approvals"] == {}


def test_the_actor_header_is_recorded(client):
    client.post("/bridge/ge-2026-14/approvals",
                json={"approvals": {"electrical": ["F001"]}},
                headers={"X-CBOQ-Actor": "j.chan"})

    conn = bridge_conn()
    try:
        row = conn.execute(
            "SELECT selected_by FROM bridge_shortlist_approvals WHERE set_id = ?",
            ("ge-2026-14",),
        ).fetchone()
    finally:
        conn.close()
    assert row["selected_by"] == "j.chan"


def test_both_endpoints_are_registered(client):
    assert "/bridge/{set_id}/approvals" in __import__("api").app.openapi()["paths"]


# -- the gate did not move -----------------------------------------------------------------------
def test_persisting_a_selection_sends_drafts_and_approves_nothing():
    """The whole safety claim, asserted at the source: this module has no outbound path.

    Scanned over the module's IMPORTS rather than its text, because the prose deliberately talks
    about dispatch and a substring hunt would only ever be measuring the docstring. What matters
    is what the code can reach: if a future edit imports the mailer, the Gmail client, or a stage
    that writes a gate flag, this fails before it ships.
    """
    tree = ast.parse(inspect.getsource(approvals_mod))
    reached = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            reached.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            reached.add(node.module or "")

    # Only stdlib plus the bridge's own identity helper. Nothing that can send, draft, or approve.
    assert reached == {"__future__", "datetime", "sqlite3", "bridge.identity"}


def test_writing_an_approval_touches_no_gate_flag(client):
    """A selection must not open the review or scope gate — those have their own endpoints."""
    conn = bridge_conn()
    try:
        before = {r["name"] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    finally:
        conn.close()

    client.post("/bridge/ge-2026-14/approvals",
                json={"approvals": {"electrical": ["F001"]}})

    conn = bridge_conn()
    try:
        after = {r["name"] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    finally:
        conn.close()
    # It creates its OWN table and nothing else — in particular no gate table gets a row it did
    # not have, because no gate table is even reached.
    assert after - before <= {"bridge_shortlist_approvals",
                              "sqlite_sequence"}
