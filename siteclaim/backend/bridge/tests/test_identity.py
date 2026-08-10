"""Phase 2 — one tender, one identifier.

``set_id`` and ``run_ref`` are the same string on both sides (both are ``tender_slug`` of the
project name), so these assert the equivalence is stated rather than translated, and that the
``unified_projects`` umbrella is registered exactly once per set.

Note on fixtures: the bridge's PRODUCTION code only ever READS client_boq. These tests call
client_boq's own public ``upsert_document_set`` to stand a set up in the throwaway test DB —
using their API rather than raw SQL, so the fixture follows their schema instead of duplicating
assumptions about it.
"""

import pytest

from bridge import identity


def _make_set(conn, set_id: str, name: str) -> None:
    from client_boq import store as cb_store

    cb_store.upsert_document_set(conn, set_id=set_id, name=name, slug=set_id, status="ingested")


def test_run_ref_for_is_the_identity_function():
    # Same string by construction — if this ever needs to translate, the two sides have diverged
    # and that is a design problem, not something to paper over here.
    assert identity.run_ref_for("ge-2026-14") == "ge-2026-14"
    assert identity.run_ref_for("  ge-2026-14  ") == "ge-2026-14"


def test_both_sides_slug_a_tender_name_to_the_same_id():
    # The actual guarantee behind run_ref_for: client_boq/ingest/run.py:70 and api.py:2092 both
    # call this one function, so a tender's two identities cannot drift.
    from pipeline.workspace import tender_slug

    name = "Contract No. GE/2026/14 — Term Contract for Ground Investigation"
    assert tender_slug(name) == identity.run_ref_for(tender_slug(name))


def test_an_empty_set_id_is_refused_not_invented():
    for bad in ("", "   "):
        # RE-ANCHORED with the plain-language pass: the refusal stopped saying "set_id" (an
        # internal name) and says the tender's name is missing. Same refusal, same inputs.
        with pytest.raises(ValueError, match="names no tender"):
            identity.run_ref_for(bad)


def test_a_registered_set_appears_once_and_registering_twice_is_idempotent():
    from db import project as uproject

    conn = identity.bridge_conn()
    try:
        _make_set(conn, "ge-2026-14", "Contract No. GE/2026/14 — Ground Investigation")

        first = identity.register_set_on(conn, "ge-2026-14")
        second = identity.register_set_on(conn, "ge-2026-14")

        assert first["id"] == second["id"]                       # the same row, not a second one
        assert first["run_ref"] == "ge-2026-14"
        rows = [p for p in uproject.list_projects(conn) if p["run_ref"] == "ge-2026-14"]
        assert len(rows) == 1                                    # registered once, exactly once
    finally:
        conn.close()


def test_the_umbrella_takes_its_name_from_the_client_boq_set():
    conn = identity.bridge_conn()
    try:
        _make_set(conn, "ge-2026-14", "Contract No. GE/2026/14 — Ground Investigation")
        row = identity.register_set_on(conn, "ge-2026-14")
        assert row["name"] == "Contract No. GE/2026/14 — Ground Investigation"
        assert row["provenance"] == "demo"                       # DEMO under the autouse fixture
    finally:
        conn.close()


def test_registering_an_unknown_set_still_works_with_an_empty_name():
    # The umbrella is the bridge's own record; it must not depend on client_boq having a row yet.
    conn = identity.bridge_conn()
    try:
        row = identity.register_set_on(conn, "not-ingested-yet")
        assert row["run_ref"] == "not-ingested-yet" and row["name"] == ""
    finally:
        conn.close()


def test_registration_writes_no_client_boq_table():
    # The umbrella lives on our side. Registering must not touch any client_boq_* row.
    conn = identity.bridge_conn()
    try:
        _make_set(conn, "ge-2026-14", "GE 2026 14")
        before = {
            t: conn.execute(f"SELECT COUNT(*) AS n FROM {t}").fetchone()["n"]
            for (t,) in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'client_boq_%'"
            ).fetchall()
        }
        identity.register_set_on(conn, "ge-2026-14")
        after = {t: conn.execute(f"SELECT COUNT(*) AS n FROM {t}").fetchone()["n"] for t in before}
        assert after == before
    finally:
        conn.close()
