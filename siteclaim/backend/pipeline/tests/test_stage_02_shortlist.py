"""Stage 02 shortlist — the hero. Clean runner-up on top, gotcha demoted with
citable fatal evidence. Hermetic: builds its own offline seed, no network."""

import pytest

from db import seed, store
from pipeline.stage_01_ingest.ingest import ingest_tender
from pipeline.stage_02_shortlist.shortlist import shortlist
from schemas.models import Severity, ShortlistSet, TenderPackage

_FIXTURE = "cases/clean/scope_packages.json"


@pytest.fixture(scope="module")
def conn(tmp_path_factory):
    db_path = tmp_path_factory.mktemp("shortlist") / "test.db"
    seed.build_database(db_path)
    connection = store.get_connection(db_path)
    yield connection
    connection.close()


@pytest.fixture
def shortlisted(conn) -> ShortlistSet:
    scope = ingest_tender(TenderPackage(project_name="demo", description=""), demo_fixture=_FIXTURE)
    return shortlist(scope, conn=conn)


def test_shortlist_covers_every_trade(shortlisted):
    assert {"electrical", "mechanical_plumbing", "fire_services", "joinery_fitting_out"} <= set(
        shortlisted.per_trade
    )
    assert all(cands for cands in shortlisted.per_trade.values())  # no empty trade


def test_electrical_top_is_the_clean_runner_up(shortlisted):
    electrical = shortlisted.per_trade["electrical"]
    top = electrical[0]
    assert top.firm.firm_id == "F-EL-02"
    assert top.recommended_against is False
    assert not [f for f in top.risk_flags if f.severity is Severity.FATAL]


def test_gotcha_present_but_recommended_against_with_evidence(shortlisted):
    electrical = shortlisted.per_trade["electrical"]
    gotcha = next(c for c in electrical if c.firm.firm_id == "F-EL-01")
    # present, but demoted to the bottom and flagged
    assert gotcha.recommended_against is True
    assert electrical[-1].firm.firm_id == "F-EL-01"
    # the fatal winding-up flag is attached and citable
    winding = next(f for f in gotcha.risk_flags if f.rule_ref == "risk.winding_up")
    assert winding.severity is Severity.FATAL
    assert winding.evidence[0].source == "Companies Registry"
    assert winding.evidence[0].reference == "CR:HCCW-215/2026"
    # and it is a strong match — the demotion is the risk engine, not a weak score
    assert gotcha.match_score > 0.4


def test_gotcha_outranks_a_clean_firm_on_match_yet_is_below_it(shortlisted):
    electrical = shortlisted.per_trade["electrical"]
    gotcha = next(c for c in electrical if c.firm.firm_id == "F-EL-01")
    above_gotcha = electrical[: electrical.index(gotcha)]
    assert any(c.match_score < gotcha.match_score for c in above_gotcha)


def test_k_caps_each_trade_without_reordering(conn):
    # k bounds a broad public trade (live, 20+ firms) to a dispatchable shortlist:
    # the capped list must be exactly the head of the uncapped ranking, never a reshuffle.
    scope = ingest_tender(TenderPackage(project_name="demo", description=""), demo_fixture=_FIXTURE)
    full = shortlist(scope, conn=conn, include_public=True)
    capped = shortlist(scope, conn=conn, include_public=True, k=2)
    for trade, cands in full.per_trade.items():
        assert [c.firm.firm_id for c in capped.per_trade[trade]] == [c.firm.firm_id for c in cands][:2]


def test_k_none_is_identical_to_the_default(conn):
    scope = ingest_tender(TenderPackage(project_name="demo", description=""), demo_fixture=_FIXTURE)
    default = shortlist(scope, conn=conn)
    explicit = shortlist(scope, conn=conn, k=None)
    assert {t: [c.firm.firm_id for c in cs] for t, cs in default.per_trade.items()} == {
        t: [c.firm.firm_id for c in cs] for t, cs in explicit.per_trade.items()
    }
