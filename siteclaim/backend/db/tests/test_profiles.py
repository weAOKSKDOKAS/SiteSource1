"""Curated firm profiles are truthful and bound to the right firms; register-only
firms carry no profile (the modal then shows register data only)."""

from db import store

FUGRO = "fugro-geotechnical-services-limited-af2a"
KAIWAI = "kai-wai-engineering-survey-and-geophysics-limited-3f7b"


def test_fugro_has_a_rich_verifiable_profile(conn):
    f = store.firm_full_by_id(conn, FUGRO)
    p = f["profile"]
    assert "1973" in p["overview"] and "Fugro N.V." in p["group_parent"]
    assert p["offices"] == ["Fo Tan, Hong Kong"]
    assert len(p["services"]) >= 6
    assert any("3RS" in proj["title"] or "Three-Runway" in proj["title"] for proj in p["notable_projects"])
    assert any("HOKLAS" in a for a in p["accreditations"])
    # the cited government award source survives alongside the curated profile
    assert any((a.get("source") or "").startswith("http") for a in f["award_history"])


def test_kai_wai_profile_is_honest_and_minimal(conn):
    f = store.firm_full_by_id(conn, KAIWAI)
    p = f["profile"]
    # the exact honesty caveat is present; nothing is fabricated
    assert "Limited verifiable public corporate information" in p["overview"]
    assert "Recommend standard pre-qualification checks before award." in p["overview"]
    assert p["services"] == [] and p["notable_projects"] == [] and p["accreditations"] == []


def test_register_only_firms_have_no_curated_profile(conn):
    page = store.paged_firms(conn, limit=3)
    sample = page["items"][0]["firm_id"]
    f = store.firm_full_by_id(conn, sample)
    assert f["profile"] == {}  # no curated profile (the API layer fills empty defaults)
    # but its register data is intact, so the modal still has something to show
    assert f["registered_trades"] or f["description"]
