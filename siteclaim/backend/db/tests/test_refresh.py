"""Phase C — the semi-automated refresh with a human-confirm gate.

Every test builds its OWN temp DB (not the shared session DB), because a refresh
mutates the live firms/public_flags tables and would otherwise corrupt the 134/46
coverage assertions in sibling modules.
"""

import pytest

from db import refresh, seed, store


@pytest.fixture
def conn(tmp_path):
    path = tmp_path / "refresh.db"
    seed.build_database(path)  # demo profile — has real firms to attach flags to
    connection = store.get_connection(path)
    yield connection
    connection.close()


_REAL_FIRM = "able-engineering-company-limited-093d"


def _new_flag(reference="LD:REFRESH-TEST-1"):
    return {
        "signal_type": "safety_prosecution",
        "label": "Refresh-test prosecution 2026",
        "date": "2026-03-01",
        "source": "Labour Department",
        "reference": reference,
    }


def _live_flag_count(conn, firm_id, reference):
    profile = store.firm_profile(conn, firm_id)
    return sum(1 for f in profile.public_flags for ev in f.evidence if ev.reference == reference)


def test_stage_does_not_touch_the_live_tables(conn):
    summary = refresh.stage_records(conn, [{"firm_id": _REAL_FIRM, "public_flags": [_new_flag()]}])
    assert summary["staged_flags"] == 1
    assert len(refresh.list_pending(conn)) == 1
    assert _live_flag_count(conn, _REAL_FIRM, "LD:REFRESH-TEST-1") == 0  # nothing applied yet


def test_confirm_applies_the_staged_flag(conn):
    summary = refresh.stage_records(conn, [{"firm_id": _REAL_FIRM, "public_flags": [_new_flag()]}])
    result = refresh.confirm_pending(conn, batch_id=summary["batch_id"])
    assert result["confirmed_flags"] == 1
    assert _live_flag_count(conn, _REAL_FIRM, "LD:REFRESH-TEST-1") == 1
    assert refresh.list_pending(conn) == []  # nothing left pending


def test_restage_of_a_confirmed_flag_is_a_noop(conn):
    rec = {"firm_id": _REAL_FIRM, "public_flags": [_new_flag()]}
    first = refresh.stage_records(conn, [rec])
    refresh.confirm_pending(conn, batch_id=first["batch_id"])
    # staging the identical flag again: it already exists live -> skipped, never staged
    second = refresh.stage_records(conn, [rec])
    assert second["skipped_duplicate_flags"] == 1 and second["staged_flags"] == 0
    assert _live_flag_count(conn, _REAL_FIRM, "LD:REFRESH-TEST-1") == 1  # still exactly one


def test_duplicate_within_one_batch_is_deduped(conn):
    rec = {"firm_id": _REAL_FIRM, "public_flags": [_new_flag(), _new_flag()]}
    summary = refresh.stage_records(conn, [rec])
    assert summary["staged_flags"] == 1 and summary["skipped_duplicate_flags"] == 1


def test_confirming_a_new_firm_increments_coverage(conn):
    before = store.coverage(conn)["total_firms"]
    rec = {
        "firm_id": "new-public-firm-abcd",
        "name_en": "New Public Firm Ltd",
        "trades": ["electrical"],
        "public_flags": [{"signal_type": "winding_up", "label": "Winding-up petition 2026", "reference": "CR:NEW-1"}],
    }
    summary = refresh.stage_records(conn, [rec])
    pending = refresh.list_pending(conn)
    assert any(p["firm_id"] == "new-public-firm-abcd" and p["is_new_firm"] for p in pending)
    assert store.coverage(conn)["total_firms"] == before  # staging alone changes nothing

    result = refresh.confirm_pending(conn, batch_id=summary["batch_id"])
    assert result["confirmed_firms"] == 1 and result["confirmed_flags"] == 1
    cov = store.coverage(conn)
    assert cov["total_firms"] == before + 1  # new public_register firm is counted
    assert store.firm_profile(conn, "new-public-firm-abcd") is not None


def test_reject_keeps_data_out(conn):
    summary = refresh.stage_records(conn, [{"firm_id": _REAL_FIRM, "public_flags": [_new_flag()]}])
    rejected = refresh.reject_pending(conn, batch_id=summary["batch_id"])
    assert rejected["rejected"] >= 1
    assert refresh.list_pending(conn) == []
    assert _live_flag_count(conn, _REAL_FIRM, "LD:REFRESH-TEST-1") == 0


def test_confirm_forces_public_register_provenance(conn):
    # A refresh payload cannot inject 'illustrative' provenance to game the 134/46 claim.
    rec = {"firm_id": "sneaky-firm-0001", "name_en": "Sneaky Ltd", "trades": ["electrical"],
           "provenance": "illustrative", "public_flags": []}
    summary = refresh.stage_records(conn, [rec])
    refresh.confirm_pending(conn, batch_id=summary["batch_id"])
    prov = conn.execute("SELECT provenance FROM firms WHERE firm_id='sneaky-firm-0001'").fetchone()["provenance"]
    assert prov == "public_register"


def test_flag_for_unknown_firm_is_left_pending(conn):
    rec = {"firm_id": "ghost-firm-9999", "public_flags": [_new_flag("LD:GHOST")]}
    # Stage only the flags (simulate a flag whose firm row is not being created): stage
    # the record, then reject the firm row so only an orphan flag would remain to confirm.
    summary = refresh.stage_records(conn, [rec])
    refresh.reject_pending(conn, batch_id=summary["batch_id"], firm_ids=["ghost-firm-9999"])
    # re-stage just the flag against the (still absent) firm and confirm without its firm row
    conn.execute(
        "INSERT INTO staged_flags (batch_id, firm_id, signal_type, label, fingerprint, status, staged_at) "
        "VALUES ('b2','ghost-firm-9999','safety_prosecution','x','fp-x','pending','2026-01-01')"
    )
    conn.commit()
    result = refresh.confirm_pending(conn, batch_id="b2")
    assert result["skipped_unknown_firm"] == 1 and result["confirmed_flags"] == 0
    assert store.firm_profile(conn, "ghost-firm-9999") is None  # no orphan firm/flag
