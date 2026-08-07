"""Re-running the analysis destroyed every route the operator had confirmed.

`write_proposal` deleted the run's rows and re-inserted them with `chosen_route = NULL`. So
pressing "Analyse routing" a second time — which an operator does after a re-split, after an
addendum, after any change at all — silently threw away every Layer-4 decision on the run. Probed
before the fix:

    after confirm    : {'gi:2': 'self_perform', 'gi:3': 'sublet'}
    after RE-analyze : {'gi:2': None,           'gi:3': None}

A Layer-1 recomputation erasing the Layer-4 gate it exists to inform, and the wrong way round:
the advisory columns (`recommended_route`, `rationale`, `signals`) are the proposal's to replace,
and `chosen_route` is not the proposal's to hold an opinion about at all. Downstream this is
indistinguishable from "nobody has decided yet", so the sourcing screen — which filters on
`chosen_route == 'sublet'` — simply showed nothing, which is the reported symptom.

A key the new proposal does NOT carry still loses its decision, and correctly: it named a package
that no longer exists. That is the one case worth being loud about, so `orphaned_decisions` reads
those keys BEFORE the write and the caller names them.
"""

import pytest

from db import routing, seed, store

GI2 = {"package_key": "gi:2", "trade": "ground_investigation", "scope_summary": "Bill 2",
       "recommended_route": "sublet", "rationale": "specialist pool", "signals": {"n": 6},
       "source": "route-suggest"}
GI3 = {"package_key": "gi:3", "trade": "ground_investigation", "scope_summary": "Bill 3",
       "recommended_route": "sublet", "rationale": "specialist pool", "signals": {"n": 6},
       "source": "route-suggest"}


@pytest.fixture
def conn(tmp_path):
    path = tmp_path / "routes.db"
    seed.build_database(path, profile="live")
    c = store.get_connection(path)
    yield c
    c.close()


def _routes(rows) -> dict:
    return {r["package_key"]: r["chosen_route"] for r in rows}


# -- the decision survives -------------------------------------------------------------------------
def test_a_confirmed_route_survives_a_re_proposal(conn):
    routing.write_proposal(conn, "nd-2025-04", [GI2, GI3])
    routing.confirm_decisions(conn, "nd-2025-04", {"gi:2": "self_perform", "gi:3": "sublet"})

    again = routing.write_proposal(conn, "nd-2025-04", [GI2, GI3])

    assert _routes(again) == {"gi:2": "self_perform", "gi:3": "sublet"}


def test_who_decided_and_when_survive_with_it(conn):
    """A decision with no provenance is not a decision anybody can stand behind at an award."""
    routing.write_proposal(conn, "nd-2025-04", [GI2])
    confirmed = routing.confirm_decisions(conn, "nd-2025-04", {"gi:2": "sublet"}, decided_by="ops")
    stamp = confirmed[0]["decided_at"]

    row = routing.write_proposal(conn, "nd-2025-04", [GI2])[0]

    assert row["decided_by"] == "ops" and row["decided_at"] == stamp


def test_the_advisory_columns_are_still_replaced(conn):
    """The proposal owns these — a re-run exists to change them, and must."""
    routing.write_proposal(conn, "nd-2025-04", [GI2])
    routing.confirm_decisions(conn, "nd-2025-04", {"gi:2": "self_perform"})

    revised = routing.write_proposal(conn, "nd-2025-04", [
        {**GI2, "recommended_route": "self_perform", "rationale": "the pool thinned",
         "signals": {"n": 1}}])[0]

    assert revised["recommended_route"] == "self_perform"
    assert revised["rationale"] == "the pool thinned" and revised["signals"] == {"n": 1}
    assert revised["chosen_route"] == "self_perform", "and the human's answer is untouched"


def test_an_undecided_package_stays_undecided(conn):
    """Preservation must not invent a decision — `None` is a state, and the gate reads it."""
    routing.write_proposal(conn, "nd-2025-04", [GI2, GI3])
    routing.confirm_decisions(conn, "nd-2025-04", {"gi:2": "sublet"})

    assert _routes(routing.write_proposal(conn, "nd-2025-04", [GI2, GI3])) == {
        "gi:2": "sublet", "gi:3": None}


def test_the_decision_survives_however_many_times_the_analysis_is_re_run(conn):
    routing.write_proposal(conn, "nd-2025-04", [GI2])
    routing.confirm_decisions(conn, "nd-2025-04", {"gi:2": "sublet"})
    for _ in range(4):
        rows = routing.write_proposal(conn, "nd-2025-04", [GI2])
    assert _routes(rows) == {"gi:2": "sublet"}


def test_another_runs_decisions_are_not_borrowed(conn):
    """The carry-over is keyed on `(run_ref, package_key)`, not `package_key` — two tenders can
    hold the same key and one must never answer for the other."""
    routing.write_proposal(conn, "nd-2025-04", [GI2])
    routing.confirm_decisions(conn, "nd-2025-04", {"gi:2": "self_perform"})

    other = routing.write_proposal(conn, "ge-2026-14", [GI2])

    assert _routes(other) == {"gi:2": None}
    assert _routes(routing.read_proposal(conn, "nd-2025-04")) == {"gi:2": "self_perform"}


# -- a key the new proposal does not carry ------------------------------------------------------------
def test_a_decision_for_a_package_that_no_longer_exists_is_dropped(conn):
    """A re-split re-keys, and a decision naming a package nobody proposed describes nothing."""
    routing.write_proposal(conn, "nd-2025-04", [GI2, GI3])
    routing.confirm_decisions(conn, "nd-2025-04", {"gi:2": "sublet", "gi:3": "sublet"})

    after = routing.write_proposal(conn, "nd-2025-04", [GI2])

    assert _routes(after) == {"gi:2": "sublet"}, "and only the surviving key is carried"


def test_the_dropped_decisions_can_be_named_before_they_are_dropped(conn):
    routing.write_proposal(conn, "nd-2025-04", [GI2, GI3])
    routing.confirm_decisions(conn, "nd-2025-04", {"gi:2": "sublet", "gi:3": "self_perform"})

    assert routing.orphaned_decisions(conn, "nd-2025-04", {"gi:2"}) == ["gi:3"]
    assert routing.orphaned_decisions(conn, "nd-2025-04", {"gi:2", "gi:3"}) == []


def test_an_undecided_package_is_not_reported_as_a_lost_decision(conn):
    """There is nothing to lose, and a report every re-route fires is a report nobody reads."""
    routing.write_proposal(conn, "nd-2025-04", [GI2, GI3])
    routing.confirm_decisions(conn, "nd-2025-04", {"gi:2": "sublet"})

    assert routing.orphaned_decisions(conn, "nd-2025-04", {"gi:2"}) == []


def test_orphaned_decisions_on_a_db_with_no_routing_table_is_empty_not_an_error(tmp_path):
    import sqlite3

    c = sqlite3.connect(str(tmp_path / "bare.db"))
    c.row_factory = sqlite3.Row
    try:
        assert routing.orphaned_decisions(c, "nd-2025-04", {"gi:2"}) == []
    finally:
        c.close()
