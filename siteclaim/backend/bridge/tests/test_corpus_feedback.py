"""The one feedback edge: a won/lost tender's result + lessons into the benchmark corpus.

Hooks into the EXISTING snapshot machinery (unified_projects.benchmark_project_id), never
duplicates it, and is append-only across the corpus.

NOTE ON THE READ PATH: the outcome lands in its OWN corpus slot, ``project_outcomes``, NOT in
``project_eos`` (that slot is the operator's End-of-Site document — the two collided when both
routed through ``attach_eos``). So these guarantees are read back through ``get_project_outcome``;
every guarantee is unchanged, only the slot it is inspected in is the corrected one. The collision
itself is covered in ``db/tests/test_benchmark_eos.py`` (the crossing test).
"""

import pytest

from bridge import closeout
from bridge.identity import bridge_conn
from db import benchmark as bench
from db import project as uproject


def _outcome(pid: int) -> dict:
    conn = bridge_conn()
    try:
        return bench.get_project_outcome(conn, pid)
    finally:
        conn.close()


# -- won/lost feed; submitted/withdrawn do not -----------------------------------------------------
def test_a_won_outcome_is_recorded_into_the_corpus():
    closeout.set_outcome("nd-2025-04", "won", "Awarded at HK$1.25m.")
    closeout.add_lesson("nd-2025-04", "pricing", "Drilling rate was light on hard rock.")

    result = closeout.feed_outcome_to_corpus("nd-2025-04")
    assert result["fed"] is True and result["benchmark_project_id"]

    outcome = _outcome(result["benchmark_project_id"])
    assert outcome["status"] == "won"
    assert "WON" in outcome["narrative"]
    assert "hard rock" in outcome["narrative"], "the lessons ride into the corpus"


def test_a_lost_outcome_also_feeds():
    closeout.set_outcome("nd-2025-04", "lost", "Price 8% over the winner.")
    assert closeout.feed_outcome_to_corpus("nd-2025-04")["fed"] is True


@pytest.mark.parametrize("status", ["submitted", "withdrawn"])
def test_an_unresolved_outcome_feeds_nothing(status):
    closeout.set_outcome("nd-2025-04", status)
    result = closeout.feed_outcome_to_corpus("nd-2025-04")
    assert result["fed"] is False and result["benchmark_project_id"] is None


def test_no_outcome_at_all_feeds_nothing():
    assert closeout.feed_outcome_to_corpus("never-touched")["fed"] is False


# -- idempotent on repeat ---------------------------------------------------------------------------
def test_feeding_twice_records_once_not_twice():
    closeout.set_outcome("nd-2025-04", "won")
    first = closeout.feed_outcome_to_corpus("nd-2025-04")
    second = closeout.feed_outcome_to_corpus("nd-2025-04")

    assert first["benchmark_project_id"] == second["benchmark_project_id"], "reuses the same project"
    conn = bridge_conn()
    try:
        # one benchmark project for the tender, one outcome row on it
        projects = [p for p in bench.list_projects(conn) if p["source"] == "tender-outcome"]
        assert len(projects) == 1
        rows = conn.execute(
            "SELECT COUNT(*) AS n FROM project_outcomes WHERE project_id = ?",
            (first["benchmark_project_id"],)).fetchone()["n"]
        assert rows == 1, "attach_project_outcome replaces, one outcome per project"
        # and it never touched the EoS slot
        eos_rows = conn.execute(
            "SELECT COUNT(*) AS n FROM project_eos WHERE project_id = ?",
            (first["benchmark_project_id"],)).fetchone()["n"]
        assert eos_rows == 0, "the outcome does not live in the EoS slot"
    finally:
        conn.close()


def test_a_re_fed_outcome_updates_its_own_narrative():
    closeout.set_outcome("nd-2025-04", "won")
    pid = closeout.feed_outcome_to_corpus("nd-2025-04")["benchmark_project_id"]
    assert "WON" in _outcome(pid)["narrative"]

    closeout.set_outcome("nd-2025-04", "lost", "Reversed on appeal.")
    again = closeout.feed_outcome_to_corpus("nd-2025-04")
    assert again["benchmark_project_id"] == pid
    assert _outcome(pid)["status"] == "lost"
    assert "LOST" in _outcome(pid)["narrative"] and "WON" not in _outcome(pid)["narrative"]


# -- hooks into the existing link, does not duplicate ----------------------------------------------
def test_it_reuses_the_estimates_captured_benchmark_project():
    """When the estimate was already captured (to-benchmark linked a project), the outcome attaches
    to THAT project rather than creating a second one for the same tender."""
    conn = bridge_conn()
    try:
        uproject.get_or_create(conn, "nd-2025-04", name="ND/2025/04")
        existing = bench.create_project(conn, name="ND/2025/04", source="estimate")
        uproject.link_benchmark(conn, "nd-2025-04", existing["id"])
    finally:
        conn.close()

    closeout.set_outcome("nd-2025-04", "won")
    result = closeout.feed_outcome_to_corpus("nd-2025-04")

    assert result["benchmark_project_id"] == existing["id"], "the estimate's project, reused"


def test_it_does_not_mutate_an_unrelated_corpus_project():
    conn = bridge_conn()
    try:
        other = bench.create_project(conn, name="Some Other Job", source="estimate")
        bench.replace_tender_items(conn, other["id"],
                                   [{"item_ref": "A1", "description": "x", "unit": "m", "qty": 1.0,
                                     "rate": 100.0, "amount": 100.0, "section": ""}], source="estimate")
    finally:
        conn.close()

    closeout.set_outcome("nd-2025-04", "won")
    closeout.feed_outcome_to_corpus("nd-2025-04")

    conn = bridge_conn()
    try:
        assert len(bench.tender_items(conn, other["id"])) == 1, "the other project is untouched"
        assert bench.get_eos(conn, other["id"]) is None
        assert bench.get_project_outcome(conn, other["id"]) is None
    finally:
        conn.close()
