"""Two defects that let a confirmed decision be ignored and a superseded document be sent.

**The map was stored and never read.** `bridge/spec_map.py` keyed its rows on `run_ref_for(set_id)`
— the identity function — while `/dispatch/plan` is handed the tender's human `project_name`. So six
confirmations sat under `nd-2025-04` and were looked up under `Contract No. ND/2025/04`, the lookup
came back empty, and the fallback told the operator *"no specification mapping is confirmed"* while
six were. `storage_key` reconciles the two through `tender_slug`, which is the same equivalence
`Workspace` already uses to make the doc index reachable by either name.

**A reissue never met the document it supersedes.** `TA #1/…-S_PS25-1.pdf` is PS 25 at revision 1,
filed under the addendum that issued it. `_ADDENDUM` matched `TA #1` IN THE PATH, so it classified
as a clarification: it went whole to every firm through that branch and never entered
`_ps_revisions`, so the `-0` was enclosed beside it with nothing saying which governs. One contest,
two doors.

Fixtures, not the real pack: these are that pack's PATH SHAPES, written by hand.
"""

import pytest
from fastapi.testclient import TestClient

from bridge.spec_map import ConfirmedSpec, load_spec_map, save_spec_map, storage_key
from pipeline.stage_01_ingest.doc_index import DocIndexEntry, _kind_for
from pipeline.stage_03_dispatch.relevant_docs import (
    NO_RELEVANCE_ESTABLISHED,
    SUPERSEDED_BY_ADDENDUM,
    resolve_section_plan,
)
from schemas.models import DocType, SorItem

NAME = "Contract No. ND/2025/04"
SET_ID = "nd-2025-04"                       # == tender_slug(NAME), as the bridge builds it

PS25_0 = "S/PS/PS25/I-ND_2025_04-S_PS25-0.pdf"
PS25_1 = "TA #1/S/PS/PS25/I-ND_2025_04-S_PS25-1.pdf"
PS27_0 = "S/PS/PS27/I-ND_2025_04-S_PS27-0.pdf"
PS27_1 = "TA #2/S/PS/PS27/I-ND_2025_04-S_PS27-1.pdf"
PS28_0 = "S/PS/PS28/I-ND_2025_04-S_PS28-0.pdf"
PSA1_1 = "TA #1/S/PS/PS1/I-ND_2025_04-S_PSA1.12-1.pdf"
LETTER = "TA #1/I-ND_2025_04-Tender_Addendum_No_1.pdf"


def _e(fn, kind="particular_specification", sec="", title=""):
    return DocIndexEntry(filename=fn, kind=kind, spec_section_number=sec,
                         spec_section_title=title, spec_section_title_source="ps_index" if title else "",
                         text_layer=True, page_count=20)


PACK = [
    _e(PS25_0, sec="25", title="Environmental Protection"),
    _e(PS25_1, kind="clarification", sec="25", title="Environmental Protection"),
    _e(PS27_0, sec="27", title="Construction Site Safety"),
    _e(PS27_1, kind="clarification", sec="27", title="Construction Site Safety"),
    _e(PS28_0, sec="28", title="Environmental Ground Investigation"),
    _e(LETTER, kind="clarification"),
]


@pytest.fixture
def client():
    import api

    return TestClient(api.app)


def _plan(sections, *, confirmed=None, unconfirmed=None, index=None):
    return resolve_section_plan(
        package_key=f"ground_investigation:{sections[0]}", trade="ground_investigation",
        section_title="Ground investigation", section=sections[0], sections=list(sections),
        items=[SorItem(item_ref=f"{sections[0]}.1", description="Rotary drilling",
                       section=sections[0], clause_refs=[])],
        doc_index=list(PACK if index is None else index), sor_sheet_name="SoR.xlsx",
        confirmed_ps_specs=confirmed, unconfirmed_sections=unconfirmed,
    )


def _docs(plan):
    return {a.source_doc for a in plan.attachments}


# ============================================================================
# DEFECT 1 — the confirmed map reaches dispatch
# ============================================================================
def test_a_confirmation_saved_by_set_id_is_found_by_project_name():
    """The defect, at its root: two identities for one tender."""
    save_spec_map(SET_ID, [ConfirmedSpec(bill_section="2", ps_section="28")])

    assert load_spec_map(SET_ID)["2"].ps_section == "28"
    assert load_spec_map(NAME)["2"].ps_section == "28", "what /dispatch/plan asks for"


def test_the_storage_key_is_the_slug_both_paths_already_share():
    assert storage_key(NAME) == storage_key(SET_ID) == SET_ID
    assert storage_key(SET_ID) == SET_ID, "idempotent — a set_id that is already a slug is unchanged"


def test_a_row_written_under_the_raw_ref_is_still_found():
    """A read-side fallback, not a migration. Confirming is a human act; losing one silently to a
    key change would be the worst possible way to spend it."""
    from bridge.identity import bridge_conn
    from bridge.spec_map import save_spec_map_on

    conn = bridge_conn()
    try:
        save_spec_map_on(conn, "ND/2025/04", [ConfirmedSpec(bill_section="2", ps_section="28")])
    finally:
        conn.close()
    assert load_spec_map("ND/2025/04")["2"].ps_section == "28"


def test_the_dispatch_path_reads_it(client):
    """End to end through the endpoint the operator's gate actually calls."""
    client.post(f"/bridge/{SET_ID}/spec-map",
                json={"confirmations": [{"bill_section": "2", "ps_section": "28"}]})
    from api import _confirmed_spec_map

    assert _confirmed_spec_map(NAME) == {"2": "28"}


def test_a_confirmed_section_encloses_that_specification_alone():
    plan = _plan(["2"], confirmed={"28"}, unconfirmed=[])

    assert plan.relevance_source == "confirmed_map"
    assert PS28_0 in _docs(plan)
    assert PS25_0 not in _docs(plan) and PS27_0 not in _docs(plan)
    assert not any(NO_RELEVANCE_ESTABLISHED in a.flags for a in plan.attachments)


def test_the_reason_says_it_was_selected_and_never_that_nothing_is_confirmed():
    """The false sentence on the gate, made impossible."""
    ps28 = next(a for a in _plan(["2"], confirmed={"28"}).attachments if a.source_doc == PS28_0)

    assert "CONFIRMED specification map" in ps28.reason
    assert "no specification mapping is confirmed" not in ps28.reason
    assert "clause not located" not in ps28.reason


def test_an_unconfirmed_bill_section_still_falls_back_to_whole_with_the_honest_reason():
    plan = _plan(["6"], confirmed=None)
    ps = [a for a in plan.attachments if a.source_doc.startswith(("S/PS", "TA #"))
          and NO_RELEVANCE_ESTABLISHED in a.flags]

    assert plan.relevance_source == "none"
    assert ps, "the full specification is enclosed"
    assert all("no specification mapping is confirmed" in a.reason for a in ps)


def test_a_partly_confirmed_unit_keeps_its_confirmation_and_names_the_gap():
    """Bills 1 and 9 dispatched together with only bill 9 confirmed. Falling back to the whole
    specification would bury the one section somebody actually decided."""
    plan = _plan(["9", "1"], confirmed={"27"}, unconfirmed=["1"])

    assert plan.relevance_source == "confirmed_map"
    assert PS27_1 in _docs(plan)                 # the operative revision of the confirmed section
    assert not any(NO_RELEVANCE_ESTABLISHED in a.flags for a in plan.attachments)
    assert any("Bill section 1 — no specification mapping confirmed" in m.spec
               for m in plan.missing_specs)


# ============================================================================
# DEFECT 2 — one contest, one door
# ============================================================================
@pytest.mark.parametrize("path,expected", [
    (PS25_1, "particular_specification"),        # a reissued section, filed under its addendum
    (PS27_1, "particular_specification"),
    (PSA1_1, "appendix"),                        # a reissued APPENDIX is still an appendix
    ("TA #1/S/GS/I-ND_2025_04-S_GS7-1.pdf", "general_specification"),
    (LETTER, "clarification"),                   # a genuine addendum letter names no section
    ("TA #2/I-ND_2025_04-Tender_Addendum_No_2.pdf", "clarification"),
])
def test_a_document_under_an_addendum_folder_is_classified_by_its_own_name(path, expected):
    assert _kind_for(DocType.GENERAL, "", path) == expected


def test_the_reissue_supersedes_its_original_and_only_one_is_enclosed():
    plan = _plan(["7"], confirmed={"25"})
    docs = _docs(plan)

    assert PS25_1 in docs, "the revision governs"
    assert PS25_0 not in docs, "the superseded original is not sent"


def test_the_gate_states_the_revision_and_its_evidence():
    att = next(a for a in _plan(["7"], confirmed={"25"}).attachments if a.source_doc == PS25_1)

    assert "Rev 1" in att.reason and "superseding" in att.reason
    assert "the -0/-1 filename suffix" in att.reason, "the only revision evidence this pack carries"
    assert SUPERSEDED_BY_ADDENDUM in att.flags


def test_the_reissue_no_longer_goes_to_every_firm_as_a_clarification():
    """It used to enter through the clarification branch, so a firm enquired on nothing to do with
    section 25 received PS 25 rev 1 anyway."""
    plan = _plan(["2"], confirmed={"28"})
    assert PS25_1 not in _docs(plan) and PS25_0 not in _docs(plan)


def test_a_genuine_addendum_letter_still_goes_to_every_firm():
    """The one thing this must not break."""
    att = next(a for a in _plan(["2"], confirmed={"28"}).attachments if a.source_doc == LETTER)
    assert att.mode == "whole" and "issued to all firms" in att.reason


@pytest.mark.parametrize("reverse", [False, True])
def test_the_outcome_does_not_depend_on_index_order(reverse):
    index = list(reversed(PACK)) if reverse else list(PACK)
    plan = _plan(["7"], confirmed={"25"}, index=index)

    assert PS25_1 in _docs(plan) and PS25_0 not in _docs(plan)


def test_the_effective_kind_is_applied_before_the_revision_contest():
    """A `doc_index.json` written before the classifier learned this carries `clarification` for the
    reissue. Overriding it inside the attachment loop — where the override used to live — was too
    late: `_ps_revisions` had already run on the stored kinds and never saw the contest.
    """
    stale = [_e(PS25_0, sec="25"), _e(PS25_1, kind="clarification", sec="25")]
    docs = _docs(_plan(["7"], confirmed={"25"}, index=stale))

    assert docs & {PS25_0, PS25_1} == {PS25_1}, "repaired on read, with no re-split"


def test_two_revisions_of_two_different_sections_each_resolve_independently():
    plan = _plan(["7"], confirmed={"25", "27"})
    docs = _docs(plan)

    assert {PS25_1, PS27_1} <= docs
    assert not ({PS25_0, PS27_0} & docs)
