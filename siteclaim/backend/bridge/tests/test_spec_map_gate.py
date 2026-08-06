"""A confirmed map selects the specification; an unconfirmed proposal selects nothing.

The proposal (`pipeline/stage_03_dispatch/spec_match.py`) is evidence. This is the gate, and the two
halves of it are tested here: that a person's decision survives a reload, and that the absence of
one changes nothing about what a firm receives except a flag saying so.

The behaviour the gate replaces: this issuer's bill has no Clause Ref column, so no item cites a
clause, `relevant_ps_specs` came out empty, and NO specification was attached to any enquiry. Two
different trades received identical bundles, neither containing the document that governs the work.
Sending the whole specification is wasteful and visible; sending nothing looks like a tidy enquiry.
"""

import pytest
from fastapi.testclient import TestClient

from bridge.spec_map import (
    ConfirmedSpec,
    load_spec_map,
    load_spec_map_on,
    ps_specs_for_sections,
    save_spec_map,
    save_spec_map_on,
)
from pipeline.stage_01_ingest.doc_index import DocIndexEntry
from pipeline.stage_03_dispatch.relevant_docs import (
    NO_RELEVANCE_ESTABLISHED,
    resolve_section_plan,
)
from schemas.models import SorItem

SET = "san-tin-technopole-phase-2"


@pytest.fixture
def client():
    import api

    return TestClient(api.app)


PS28 = DocIndexEntry(filename="S/PS/PS28/…-S_PS28-0.pdf", kind="particular_specification",
                     spec_section_number="28", spec_section_title="Environmental Ground Investigation",
                     spec_section_title_source="ps_index", text_layer=True, page_count=40,
                     clause_index={"28.2.07": [1]})
PS2 = DocIndexEntry(filename="S/PS/PS2/…-S_PS2-0.pdf", kind="particular_specification",
                    spec_section_number="2", spec_section_title="Site Clearance",
                    spec_section_title_source="ps_index", text_layer=True, page_count=8)
PS31 = DocIndexEntry(filename="S/PS/PS31/…-S_PS31-0.pdf", kind="particular_specification",
                     spec_section_number="31", spec_section_title="Laboratory Testing",
                     spec_section_title_source="ps_index", text_layer=True, page_count=12)
INDEX = [PS2, PS28, PS31]


def _plan(*, confirmed=None, clause_refs=(), doc_index=None):
    """One dispatched unit: bill section 2, whose items cite whatever they are given."""
    return resolve_section_plan(
        package_key="ground_investigation:2", trade="ground_investigation",
        section_title="Ground investigation", section="2", sections=["2"],
        items=[SorItem(item_ref="2.1", description="Rotary drilling in soil", section="2",
                       clause_refs=list(clause_refs))],
        doc_index=INDEX if doc_index is None else doc_index,
        sor_sheet_name="SoR_gi.xlsx", confirmed_ps_specs=confirmed,
    )


def _specs(plan):
    return {a.source_doc for a in plan.attachments}


# -- an unconfirmed proposal selects nothing --------------------------------------------------------
def test_a_proposal_nobody_confirmed_selects_no_specification():
    """The single most important assertion in this phase.

    The matcher really does propose PS 28 for this bill, with `strong` confidence — asserted here
    rather than assumed, so this test cannot pass because the proposal quietly stopped existing.
    Nothing confirms it, and the plan must then behave EXACTLY as it would if no proposal had ever
    been made: PS 28 gets no privileged treatment, and PS 2 and PS 31 — which nothing proposed —
    are enclosed on precisely the same terms.
    """
    from pipeline.stage_03_dispatch.spec_match import propose_for_heading

    proposal = propose_for_heading("SECTION 2 - GROUND INVESTIGATION", "2", INDEX)
    assert (proposal.ps_section, proposal.confidence) == ("28", "strong")

    plan = _plan(confirmed=None)
    assert plan.relevance_source == "none", "a proposal is not a confirmed map"

    ps = {a.source_doc: a for a in plan.attachments if a.source_doc.startswith("S/PS/")}
    proposed, unproposed = ps[PS28.filename], ps[PS2.filename]
    assert (proposed.mode, proposed.flags) == (unproposed.mode, unproposed.flags), \
        "the proposed section was treated differently from an unproposed one — it was acted on"
    assert proposed.mode == "whole" and NO_RELEVANCE_ESTABLISHED in proposed.flags


def test_with_nothing_confirmed_the_full_specification_is_enclosed_whole():
    """Not nothing, which is what shipped before. Every PS section, whole, and flagged."""
    plan = _plan(confirmed=None)
    ps = [a for a in plan.attachments if a.source_doc.startswith("S/PS/")]

    assert {a.source_doc for a in ps} == {PS2.filename, PS28.filename, PS31.filename}
    assert {a.mode for a in ps} == {"whole"}
    assert all(NO_RELEVANCE_ESTABLISHED in a.flags for a in ps)


def test_the_gate_is_told_once_not_once_per_section():
    """Thirty-two identical lines read as thirty-two problems. It is one decision to make."""
    plan = _plan(confirmed=None)
    notes = [m for m in plan.missing_specs if "no per-item relevance established" in m.spec.lower()]

    assert len(notes) == 1
    assert "3 PS sections, whole" in notes[0].spec
    assert "no specification mapping is confirmed" in notes[0].referenced_by


def test_the_whole_specification_reason_does_not_claim_a_clause_was_looked_for():
    """"clause not located" would be a false report about a search that never ran — no clause was
    ever cited."""
    ps28 = next(a for a in _plan(confirmed=None).attachments if a.source_doc == PS28.filename)
    assert "clause not located" not in ps28.reason
    assert "no per-item relevance established" in ps28.reason.lower()
    assert "full specification is enclosed" in ps28.reason


# -- a confirmed map selects the right one -----------------------------------------------------------
def test_a_confirmed_map_selects_that_specification_and_only_that_one():
    plan = _plan(confirmed={"28"})

    assert plan.relevance_source == "confirmed_map"
    assert PS28.filename in _specs(plan)
    assert PS2.filename not in _specs(plan)      # the number-matched wrong answer stays out
    assert PS31.filename not in _specs(plan)
    assert not any(NO_RELEVANCE_ESTABLISHED in a.flags for a in plan.attachments)


def test_a_confirmed_map_that_names_the_wrong_section_is_obeyed():
    """The operator is the authority. If they confirm PS 2, PS 2 goes — the machine does not
    second-guess a human decision, it only made sure one was taken."""
    assert PS2.filename in _specs(_plan(confirmed={"2"}))


# -- cited clauses still win --------------------------------------------------------------------------
def test_where_the_bill_cites_clauses_those_decide_and_the_map_is_not_consulted():
    """A fallback for issuers that do not cite, never a replacement for the ones that do."""
    plan = _plan(clause_refs=["PS 28.2.07"], confirmed={"2"})

    assert plan.relevance_source == "clause_refs"
    assert PS28.filename in _specs(plan)         # the CITATION won
    assert PS2.filename not in _specs(plan)      # the confirmed map did not override it


def test_a_cited_bill_slices_rather_than_sending_whole():
    ps28 = next(a for a in _plan(clause_refs=["PS 28.2.07"]).attachments
                if a.source_doc == PS28.filename)
    assert ps28.mode == "sliced" and NO_RELEVANCE_ESTABLISHED not in ps28.flags


def test_a_tender_with_no_specification_at_all_is_unchanged():
    """No PS in the pack means nothing to enclose and nothing to flag — not an empty complaint."""
    plan = _plan(confirmed=None, doc_index=[])
    assert plan.relevance_source == ""
    assert not any(NO_RELEVANCE_ESTABLISHED in a.flags for a in plan.attachments)
    assert not any("relevance established" in m.spec.lower() for m in plan.missing_specs)


# -- persistence -------------------------------------------------------------------------------------
def test_a_confirmation_survives_a_reload():
    save_spec_map(SET, [ConfirmedSpec(bill_section="2", ps_section="28",
                                      bill_heading="SECTION 2 - GROUND INVESTIGATION",
                                      ps_title="Environmental Ground Investigation",
                                      proposed_ps_section="28", proposed_confidence="strong")])
    again = load_spec_map(SET)

    assert set(again) == {"2"}
    assert again["2"].ps_section == "28"
    assert again["2"].ps_title == "Environmental Ground Investigation"
    assert again["2"].confirmed_at and again["2"].confirmed_by == "operator"
    assert again["2"].agreed_with_the_machine is True


def test_re_confirming_corrects_in_place_rather_than_stacking_a_second_row():
    save_spec_map(SET, [ConfirmedSpec(bill_section="2", ps_section="28",
                                      proposed_ps_section="28", proposed_confidence="strong")])
    save_spec_map(SET, [ConfirmedSpec(bill_section="2", ps_section="7",
                                      proposed_ps_section="28", proposed_confidence="strong")])
    rows = load_spec_map(SET)

    assert len(rows) == 1 and rows["2"].ps_section == "7"
    assert rows["2"].agreed_with_the_machine is False, "the correction is visible, not lost"


def test_a_section_not_in_the_payload_is_left_alone():
    save_spec_map(SET, [ConfirmedSpec(bill_section="2", ps_section="28"),
                        ConfirmedSpec(bill_section="3", ps_section="31")])
    save_spec_map(SET, [ConfirmedSpec(bill_section="2", ps_section="7")])
    rows = load_spec_map(SET)

    assert rows["3"].ps_section == "31"      # this screen was not talking about bill 3
    assert rows["2"].ps_section == "7"


def test_confirming_no_counterpart_is_a_decision_and_is_stored():
    """Distinct from having no row. Both send the whole specification; only one was decided."""
    save_spec_map(SET, [ConfirmedSpec(bill_section="5", ps_section="",
                                      bill_heading="Bill No. 5 - Builders Work",
                                      proposed_confidence="none")])
    rows = load_spec_map(SET)

    assert "5" in rows and rows["5"].ps_section == ""
    assert ps_specs_for_sections(rows, ["5"]) == set()


def test_two_sets_do_not_see_each_others_decisions():
    save_spec_map(SET, [ConfirmedSpec(bill_section="2", ps_section="28")])
    save_spec_map("another-tender", [ConfirmedSpec(bill_section="2", ps_section="7")])

    assert load_spec_map(SET)["2"].ps_section == "28"
    assert load_spec_map("another-tender")["2"].ps_section == "7"


def test_a_confirmation_with_no_bill_section_is_refused():
    with pytest.raises(ValueError, match="must name the bill section"):
        save_spec_map(SET, [ConfirmedSpec(bill_section="  ", ps_section="28")])


def test_the_ddl_is_idempotent_across_connections():
    """Lazy DDL, run on every connection, exactly as approvals.py does it."""
    from bridge.identity import bridge_conn

    for _ in range(3):
        conn = bridge_conn()
        try:
            save_spec_map_on(conn, SET, [ConfirmedSpec(bill_section="2", ps_section="28")])
            assert set(load_spec_map_on(conn, SET)) == {"2"}
        finally:
            conn.close()


def test_only_the_confirmed_sections_of_this_unit_are_selected():
    save_spec_map(SET, [ConfirmedSpec(bill_section="2", ps_section="28"),
                        ConfirmedSpec(bill_section="3", ps_section="31")])
    rows = load_spec_map(SET)

    assert ps_specs_for_sections(rows, ["2"]) == {"28"}
    assert ps_specs_for_sections(rows, ["2", "3"]) == {"28", "31"}
    assert ps_specs_for_sections(rows, ["9"]) == set(), "an unmapped section selects nothing"


# -- end to end, through the endpoints ---------------------------------------------------------------
def test_the_endpoints_propose_without_confirming(client):
    body = client.get(f"/bridge/{SET}/spec-map").json()

    assert body["confirmed"] == {}, "a GET must never write a confirmation"
    assert "proposals" in body


def test_posting_a_confirmation_records_it_and_a_second_get_reads_it_back(client):
    payload = {"confirmations": [{"bill_section": "2", "ps_section": "28",
                                  "bill_heading": "SECTION 2 - GROUND INVESTIGATION",
                                  "ps_title": "Environmental Ground Investigation",
                                  "proposed_ps_section": "28", "proposed_confidence": "strong"}]}
    posted = client.post(f"/bridge/{SET}/spec-map", json=payload)
    assert posted.status_code == 200
    assert posted.json()["confirmed"]["2"]["ps_section"] == "28"

    assert client.get(f"/bridge/{SET}/spec-map").json()["confirmed"]["2"]["ps_section"] == "28"


def test_a_blank_bill_section_is_a_400_not_a_500(client):
    r = client.post(f"/bridge/{SET}/spec-map", json={"confirmations": [{"bill_section": ""}]})
    assert r.status_code == 400
