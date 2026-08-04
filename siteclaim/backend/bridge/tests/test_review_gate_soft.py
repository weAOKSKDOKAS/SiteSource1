"""The review gate, soft — a V1 departure that warns instead of refusing, and never goes quiet.

**This is a deliberate departure from a locked decision.** The locked decision is that the review
register must be human-approved before routing or pricing may run, enforced as a 409, because you
cannot sensibly choose self-perform vs sublet — or price a job — without knowing what the contract
makes you responsible for. That reasoning is unchanged. What changed is the DEFAULT, for V1 demo
purposes: approving a register on a real tender pack means working through every finding, and a
demo that cannot show routing or the estimate until that is done cannot show them at all.

``REVIEW_GATE=hard`` restores the original behaviour exactly, and the SUITE runs in hard mode by
default (`backend/conftest.py`) so every existing gate test keeps asserting the locked decision
unedited. These tests are the other half: they turn soft mode on explicitly and pin the property
that makes it survivable.

**That property is that soft is not silent.** A gate that stops gating and says nothing is worse
than no gate, because the absence of a warning reads as approval. Every bypass carries the same
sentence, on the response that did the bypassing.
"""

import pytest
from fastapi.testclient import TestClient

from client_boq import gates, jobs
from client_boq.gates import SOFT_GATE_WARNING


@pytest.fixture
def soft(monkeypatch):
    monkeypatch.setenv("REVIEW_GATE", "soft")


@pytest.fixture
def client():
    from api import app

    return TestClient(app)


@pytest.fixture(autouse=True)
def _clean_job_store():
    jobs.JOBS._jobs.clear()
    yield
    jobs.JOBS._jobs.clear()


@pytest.fixture
def routable(make_set, part_spec):
    """A set with a persisted scope split, review approval left to the caller.

    Rebuilt here rather than lifted out of ``test_routing_gate.py`` into a shared conftest: that
    file is the hard gate's own test and moving its fixture would edit it, which is exactly what
    "the existing gate tests pass unchanged" rules out.
    """
    from bridge import scope as scope_mod
    from bridge.identity import bridge_conn
    from schemas.models import ScopePackages, SorItem, TradeWorkPackage

    def _build(*, approved: bool):
        make_set("ge-2026-14", "Contract No. GE/2026/14",
                 [part_spec(1, "SR", "Schedule of Rates", "pricing")],
                 review_approved=approved)
        conn = bridge_conn()
        try:
            scope_mod.save_scope_on(conn, "ge-2026-14", ScopePackages(
                project_name="GE/2026/14", packages=[
                    TradeWorkPackage(trade="foundation_substructure", scope_summary="Bored piling",
                                     sor_items=[SorItem(item_ref="G1", description="Bored piling",
                                                        unit="m", qty=100.0, section="G")]),
                ]))
        finally:
            conn.close()
        return "ge-2026-14"

    return _build


# ---------------------------------------------------------------------------
# The mode switch itself
# ---------------------------------------------------------------------------
def test_the_v1_default_is_soft(monkeypatch):
    """The shipped default. The suite pins `hard` in conftest, so this asserts what a deployment
    with nothing set actually gets — which is the thing conftest would otherwise hide."""
    monkeypatch.delenv("REVIEW_GATE", raising=False)
    assert gates.review_gate_mode() == "soft"
    assert gates.review_gate_is_soft() is True


@pytest.mark.parametrize("raw", ["hard", "HARD", " Hard ", "hArD"])
def test_hard_is_case_and_space_insensitive(monkeypatch, raw):
    monkeypatch.setenv("REVIEW_GATE", raw)
    assert gates.review_gate_mode() == "hard"


@pytest.mark.parametrize("raw", ["", "  ", "strict", "true", "1", "off", "nonsense"])
def test_anything_unrecognised_is_soft(monkeypatch, raw):
    """Unrecognised falls to the V1 DEFAULT, not to the stricter mode. A demo that 409s for a
    reason nobody typed is the harder failure to diagnose — and the warning fires either way, so
    the unrecognised case is loud rather than quiet."""
    monkeypatch.setenv("REVIEW_GATE", raw)
    assert gates.review_gate_mode() == "soft"


def test_health_reports_the_mode(client, soft):
    body = client.get("/health").json()
    assert body["review_gate"] == "soft"


def test_health_reports_hard_when_hard(client, monkeypatch):
    monkeypatch.setenv("REVIEW_GATE", "hard")
    assert client.get("/health").json()["review_gate"] == "hard"


# ---------------------------------------------------------------------------
# Routing — propose and confirm
# ---------------------------------------------------------------------------
def test_analyze_runs_on_an_unapproved_register_and_says_so(client, routable, soft):
    """The 409 becomes a 200 plus a sentence. The sentence is the whole of the safety."""
    set_id = routable(approved=False)
    resp = client.post(f"/bridge/{set_id}/route/analyze")
    assert resp.status_code == 200
    assert SOFT_GATE_WARNING in resp.json()["notes"]


def test_confirming_a_route_on_unread_terms_also_says_so(client, routable, soft):
    """The act, not just the advice. `confirm_routes` had no note channel at all — a warning only
    on the proposal would leave the response that RECORDS the decision silent about it."""
    set_id = routable(approved=False)
    proposal = client.post(f"/bridge/{set_id}/route/analyze").json()
    key = proposal["packages"][0]["package_key"]
    resp = client.post(f"/bridge/{set_id}/route/confirm",
                       json={"decisions": [{"package_key": key, "chosen_route": "self_perform"}]})
    assert resp.status_code == 200
    assert SOFT_GATE_WARNING in resp.json()["notes"]


def test_an_approved_register_warns_about_nothing(client, routable, soft):
    """Soft mode must not add noise to the correct path. No bypass, no sentence."""
    set_id = routable(approved=True)
    notes = client.post(f"/bridge/{set_id}/route/analyze").json()["notes"]
    assert SOFT_GATE_WARNING not in notes


def test_hard_mode_is_unchanged(client, routable, monkeypatch):
    """The restore switch, asserted rather than assumed — this is what makes the departure
    reversible rather than a deletion."""
    monkeypatch.setenv("REVIEW_GATE", "hard")
    set_id = routable(approved=False)
    assert client.post(f"/bridge/{set_id}/route/analyze").status_code == 409


def test_the_gate_helper_returns_the_warning_rather_than_raising(soft, make_set, part_spec):
    """`require_approved_review` returns a value now, and a caller that drops it turns a warned
    bypass into a silent one. Both call sites thread it; this pins the contract they rely on."""
    from bridge import decisions
    from bridge.identity import bridge_conn

    make_set("unapproved-set", "Unapproved", [part_spec(1, "CC", "Conditions", "contract-conditions")])
    conn = bridge_conn()
    try:
        assert decisions.require_approved_review(conn, "unapproved-set") == SOFT_GATE_WARNING
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# The estimate — the same gate, the same sentence, on the job
# ---------------------------------------------------------------------------
def _reviewed_not_approved(client, make_set, part_spec, set_id="est-soft", run_review=True):
    """A set whose review has RUN but not been approved — the exact V1 demo state.

    Soft mode lifts the APPROVAL gate; it does not conjure a register. `run_scope` reads the
    parsed set and the register and raises without them, which is a data dependency sitting below
    the gate rather than a second gate — the estimate drafts a scope FROM the review's output, so
    there is nothing to draft from until the review has run. Worth stating explicitly: "soft" means
    unapproved, never unrun.
    """
    from client_boq import store as cb_store

    make_set(set_id, "Estimate Soft", [part_spec(1, "CC", "Conditions", "contract-conditions")])
    conn = cb_store.get_conn()
    try:
        cb_store.approve_manifest(conn, set_id, True)
    finally:
        conn.close()
    if run_review:
        # DEMO runs the review inline and persists the register. Deliberately NOT approved.
        client.post("/client-boq/review/run", data={"project_name": "Estimate Soft", "set_id": set_id})
    return set_id


def test_estimate_scope_kicks_off_on_an_unapproved_register_with_the_warning(
        client, make_set, part_spec, soft):
    set_id = _reviewed_not_approved(client, make_set, part_spec)
    resp = client.post("/client-boq/estimate/scope", json={"set_id": set_id})
    assert resp.status_code == 200
    assert SOFT_GATE_WARNING in resp.json()["warnings"]


def test_estimate_scope_still_409s_in_hard_mode(client, make_set, part_spec, monkeypatch):
    monkeypatch.setenv("REVIEW_GATE", "hard")
    set_id = _reviewed_not_approved(client, make_set, part_spec, "est-hard")
    resp = client.post("/client-boq/estimate/scope", json={"set_id": set_id})
    assert resp.status_code == 409
    assert "not approved yet" in resp.json()["detail"]


def test_the_warning_is_on_the_job_from_its_first_poll(monkeypatch, soft):
    """Attached BEFORE the work is submitted. A bypass the operator only learns about when the run
    finishes is one they have already acted on."""
    from client_boq.router import _job_state

    job_id = jobs.JOBS.create("scope", set_id="s")
    jobs.JOBS.add_warning(job_id, SOFT_GATE_WARNING)
    assert SOFT_GATE_WARNING in _job_state(job_id, jobs.JOBS.get(job_id)).warnings


def test_the_scope_freeze_gate_is_untouched_by_the_mode(client, make_set, part_spec, soft):
    """`_scope_gate_or_409` is a DATA dependency — there is nothing to price without a frozen
    scope — not a review gate, and the soft switch must not reach it."""
    set_id = _reviewed_not_approved(client, make_set, part_spec, "est-scopegate")
    resp = client.post("/client-boq/estimate/run", json={"set_id": set_id})
    assert resp.status_code == 409
    assert "estimate scope" in resp.json()["detail"]
