"""Specialty-aware shortlist (roadmap #5, Commit 3): each GI section shortlists against its own
specialist pool with a parent fallback and specialists first — so G, H and J stop showing the
identical alphabetical list. Hermetic: builds its own offline seed, no network."""

import pytest

from db import seed, store
from db.cross_reference import MIN_POOL, _direct_specialties
from pipeline.stage_02_shortlist.shortlist import _section_specialty_for, shortlist
from schemas.models import FirmProfile, ScopePackages, SectionMeta, SorItem, TradeWorkPackage


@pytest.fixture(scope="module")
def conn(tmp_path_factory):
    db_path = tmp_path_factory.mktemp("shortlist_specialty") / "test.db"
    seed.build_database(db_path)
    connection = store.get_connection(db_path)
    yield connection
    connection.close()


def _unit(section: str, section_trade: str, title: str) -> TradeWorkPackage:
    return TradeWorkPackage(
        trade=f"ground_investigation:{section}",
        scope_summary=f"Section {section} — {title}",
        sor_items=[SorItem(item_ref=f"{section}1", section=section)],
        sections=[SectionMeta(code=section, title=title, item_count=1, section_trade=section_trade)],
    )


def _gi_scope() -> ScopePackages:
    return ScopePackages(project_name="GE/2026/14", packages=[
        _unit("G", "field_testing", "Field Testing"),
        _unit("H", "field_installations", "Field Installations"),
        _unit("J", "geophysical_survey", "Geophysical Survey"),
    ])


def test_gi_sections_resolve_to_different_pools(conn):
    res = shortlist(_gi_scope(), conn=conn, include_public=True, k=8).per_trade
    g = [c.firm.firm_id for c in res["ground_investigation:G"]]
    h = [c.firm.firm_id for c in res["ground_investigation:H"]]
    j = [c.firm.firm_id for c in res["ground_investigation:J"]]
    assert g and h and j
    assert g != h and g != j and h != j  # the identical-alphabetical list across sections is gone


def test_thin_specialty_pool_widens_to_the_parent(conn):
    # geophysical_survey has a single specialist in the seed -> below MIN_POOL -> widen to the GI
    # parent so there are bidders to compete, keeping the specialist.
    specialists = store.firms_for_trade(conn, "geophysical_survey")
    assert 0 < len(specialists) < MIN_POOL
    j = shortlist(_gi_scope(), conn=conn, include_public=True).per_trade["ground_investigation:J"]
    assert len(j) > len(specialists)  # widened, not a pool of one


def test_direct_specialist_ranks_above_an_incidental_parent_firm(conn):
    # J's top firm genuinely does geophysical survey (direct); GI firms surfaced via the parent
    # fallback are incidental for geophysical_survey and rank below.
    j = shortlist(_gi_scope(), conn=conn, include_public=True).per_trade["ground_investigation:J"]
    assert "geophysical_survey" in _direct_specialties(j[0].firm)  # a real specialist on top
    incidental = [c for c in j if "geophysical_survey" not in _direct_specialties(c.firm)]
    assert incidental, "expected GI firms surfaced only via the parent fallback"
    assert j.index(incidental[0]) > 0  # every specialist sorts above the first incidental firm


def test_field_testing_section_leads_with_a_direct_testing_specialist(conn):
    g = shortlist(_gi_scope(), conn=conn, include_public=True).per_trade["ground_investigation:G"]
    assert "field_testing" in _direct_specialties(g[0].firm)  # a genuine testing lab, not a GI firm


def test_empty_registered_trades_is_treated_non_direct_without_crashing():
    firm = FirmProfile(
        firm_id="F-X", name="X Ltd", registered_grade="", value_band="",
        trades=["field_testing"], registered_trades=[],
    )
    assert _direct_specialties(firm) == set()  # no registered specialties -> non-direct, no crash


def test_non_gi_package_keeps_its_own_pool():
    # A non-GI package never leaves its own trade pool: no specialty is derived for it.
    pkg = TradeWorkPackage(
        trade="electrical", scope_summary="LV distribution, containment and lighting installation",
        sections=[SectionMeta(code="E", title="", section_trade="electrical")],
    )
    assert _section_specialty_for(pkg) is None


def test_routed_subpackage_derives_specialty_from_its_summary_when_sections_are_absent():
    # The live path rebuilds the sourcing scope without section metadata; the specialty is still
    # recovered from the routed sub-package's summary (which carries the section header title).
    pkg = TradeWorkPackage(
        trade="ground_investigation:J", scope_summary="Section J — Geophysical Survey (borehole televiewer)",
    )
    assert _section_specialty_for(pkg) == "geophysical_survey"
