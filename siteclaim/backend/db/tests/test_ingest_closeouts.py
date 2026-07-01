"""Phase D — partner-archive closeout ingestion.

Each test builds its own temp demo DB and ingests partner records, then confirms the
existing cross_reference(include_public=True) picks up the closeout as enrichment with
no new stage — while the demo hero and the coverage honesty figures stay intact.
"""

import pytest

from db import ingest_closeouts as ic
from db import seed, store
from db.cross_reference import cross_reference
from db.tests.conftest import ELECTRICAL_SCOPE_QUERY
from rules_engine.risk_scoring import score_firm

_NARRATIVE = (
    "LV sub-mains, final circuits, lighting installation, cable containment, busbar "
    "trunking and power distribution delivered on a commercial fit-out, with testing "
    "and commissioning records completed on programme."
)


@pytest.fixture
def conn(tmp_path):
    path = tmp_path / "ingest.db"
    seed.build_database(path)  # demo profile — deterministic vectors, embed_dim 256
    connection = store.get_connection(path)
    yield connection
    connection.close()


def _electrical_record(name="VSL Test Electrical Ltd", **kw):
    base = dict(firm_name=name, trade="electrical", project_name="Drainage GE/2026/14",
                year=2025, closeout_narrative=_NARRATIVE)
    base.update(kw)
    return ic.PartnerCloseoutRecord(**base)


def test_ingest_enriches_the_shortlist_via_existing_cross_reference(conn):
    summary = ic.ingest(conn, [_electrical_record()])
    assert summary.firms_created == 1 and summary.closeouts_written == 1 and summary.embeddings_baked == 1

    candidates = cross_reference(conn, "electrical", ELECTRICAL_SCOPE_QUERY, include_public=True)
    mine = [c for c in candidates if c.firm.name == "VSL Test Electrical Ltd"]
    assert mine, "the ingested firm must appear in the opened shortlist"
    assert mine[0].match_score > 0.0  # the baked closeout matches the electrical scope
    assert any(e.reference.startswith("EOS:") for e in mine[0].evidence)  # closeout evidence attached


def test_embedding_is_baked_in_the_dbs_own_space(conn):
    firm_id, _ = _resolve_and_ingest(conn, _electrical_record())
    dim = int(store._meta(conn, "embed_dim", "256"))
    row = conn.execute("SELECT vector FROM closeout_embeddings WHERE firm_id = ?", (firm_id,)).fetchone()
    import json

    assert len(json.loads(row["vector"])) == dim  # parity with the query embedder


def test_new_firm_is_partner_archive_and_not_counted_in_coverage(conn):
    before = store.coverage(conn)["total_firms"]
    firm_id, _ = _resolve_and_ingest(conn, _electrical_record())
    prov = conn.execute("SELECT provenance FROM firms WHERE firm_id = ?", (firm_id,)).fetchone()["provenance"]
    assert prov == "partner_archive"
    assert store.coverage(conn)["total_firms"] == before  # partner firms never inflate 134/46


def test_delayed_closeout_becomes_a_warning(conn):
    rec = _electrical_record(planned_completion="2025-01-01", actual_completion="2025-05-01")
    firm_id, _ = _resolve_and_ingest(conn, rec)
    delayed = conn.execute("SELECT delayed FROM project_closeouts WHERE firm_id = ?", (firm_id,)).fetchone()["delayed"]
    assert delayed == 1
    flags = score_firm(store.firm_profile(conn, firm_id))
    assert any(f.rule_ref == "risk.closeout_delay" for f in flags)


def test_missing_narrative_writes_closeout_but_no_embedding(conn):
    rec = _electrical_record(name="No Narrative Ltd", closeout_narrative=None)
    summary = ic.ingest(conn, [rec])
    assert summary.closeouts_written == 1 and summary.embeddings_baked == 0 and summary.skipped_no_narrative == 1
    firm_id = _resolve(conn, "No Narrative Ltd")
    assert conn.execute("SELECT COUNT(*) AS n FROM closeout_embeddings WHERE firm_id = ?", (firm_id,)).fetchone()["n"] == 0


def test_entity_resolution_matches_existing_firm_by_name(conn):
    ic.ingest(conn, [_electrical_record(name="Acme Test Contractors Ltd")])
    count_after_first = len(store.all_firms(conn))
    # a second closeout for the same firm (name variant) resolves, does not duplicate
    summary = ic.ingest(conn, [_electrical_record(name="Acme Test Contractors Limited", project_name="Other Project")])
    assert summary.firms_matched == 1 and summary.firms_created == 0
    assert len(store.all_firms(conn)) == count_after_first


def test_entity_resolution_matches_by_br_number(conn):
    ic.ingest(conn, [_electrical_record(name="BR Firm One Ltd", br_number="12345678")])
    count_after_first = len(store.all_firms(conn))
    summary = ic.ingest(conn, [_electrical_record(name="Totally Different Name Ltd", br_number="12345678",
                                                  project_name="Second Job")])
    assert summary.firms_matched == 1 and summary.firms_created == 0
    assert len(store.all_firms(conn)) == count_after_first


def test_reingesting_the_same_closeout_is_idempotent(conn):
    rec = _electrical_record()
    ic.ingest(conn, [rec])
    firm_id = _resolve(conn, "VSL Test Electrical Ltd")
    closeouts_first = conn.execute("SELECT COUNT(*) AS n FROM project_closeouts WHERE firm_id = ?", (firm_id,)).fetchone()["n"]
    summary = ic.ingest(conn, [rec])
    assert summary.skipped_duplicate == 1
    closeouts_second = conn.execute("SELECT COUNT(*) AS n FROM project_closeouts WHERE firm_id = ?", (firm_id,)).fetchone()["n"]
    assert closeouts_first == closeouts_second == 1


def test_ingest_preserves_the_fatal_last_ranking_rule(conn):
    # A partner closeout makes the firm an *assessed* firm, so it correctly enters even
    # the default shortlist. What must never change is the risk rule: the fatal
    # winding-up firm F-EL-01 stays demoted below every clean firm, however strong the
    # new firm's match. (In production, partner data is ingested into the clean live
    # profile, not the demo DB — this test uses the demo DB only because it carries a
    # known fatal firm to prove the rule against.)
    ic.ingest(conn, [_electrical_record()])
    candidates = cross_reference(conn, "electrical", ELECTRICAL_SCOPE_QUERY)
    assert any(c.firm.name == "VSL Test Electrical Ltd" for c in candidates)  # now assessable
    assert candidates[-1].firm.firm_id == "F-EL-01"  # the fatal firm is still last
    clean = [i for i, c in enumerate(candidates) if not c.recommended_against]
    flagged = [i for i, c in enumerate(candidates) if c.recommended_against]
    assert max(clean) < min(flagged)  # every clean firm outranks every fatal-flagged one


# -- helpers ---------------------------------------------------------------
def _resolve(conn, name):
    normalized = ic._normalize_name(name)
    for row in conn.execute("SELECT firm_id, name_en FROM firms").fetchall():
        if ic._normalize_name(row["name_en"]) == normalized:
            return row["firm_id"]
    return None


def _resolve_and_ingest(conn, record):
    ic.ingest(conn, [record])
    return _resolve(conn, record.firm_name), record
