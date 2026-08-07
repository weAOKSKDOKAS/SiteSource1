"""The gate and dispatch must read the same workspace for the same tender.

THE DEFECT. `GET /bridge/{set_id}/doc-index` reported 168 documents while the dispatch preview,
at the same moment, said *"no Schedule of Rates PDF is indexed for this tender"* and substituted the
generated workbook for every package. Two workspaces existed on disk:

    workspace/nd-2025-04-san-tin-technopole/artifacts/doc_index.json   156,227 bytes   (current)
    workspace/nd-2025-04/artifacts/doc_index.json                          570 bytes   (stale)

`Workspace.tender_dir` is `root / tender_slug(tender_id)`, and `tender_slug` does not reconcile the
two strings a tender is addressed by:

    tender_slug('nd-2025-04-san-tin-technopole') -> 'nd-2025-04-san-tin-technopole'   (the set_id)
    tender_slug('Contract No. ND/2025/04')       -> 'nd-2025-04'                       (the name)

The bridge writes under the set_id; `/dispatch/plan` is handed `scope.project_name` and slugged that.
The stale 570-byte index made the mismatch read as an honest empty pack.

**This is C13's defect class exactly** — the spec map was stored under one identity and read under
another — and C13's fix (`storage_key = tender_slug(run_ref_for(set_id))`) does not survive it,
because `tender_slug(name) != tender_slug(set_id)` here. Both are fixed by resolving the identity
ONCE, at the API boundary, through the `unified_projects` row the bridge already registers.

EVERY artifact in a workspace is keyed the same way — `docs/`, the SoR sheets, `scope.json`, firm
attachments — so this was latent for all of them, not only the index.
"""

import pytest
from fastapi.testclient import TestClient

from bridge.identity import register_set, tender_ref
from pipeline.stage_01_ingest.doc_index import DocIndexEntry, save_doc_index
from pipeline.workspace import Workspace, tender_slug
from schemas.models import ScopePackages, SectionMeta, SorItem, TradeWorkPackage

SET_ID = "nd-2025-04-san-tin-technopole"
NAME = "Contract No. ND/2025/04"

BILL = DocIndexEntry(filename="BQ/I-ND_2025_04_BQ-0.pdf", kind="schedule_of_rates", text_layer=True,
                     page_count=26, sor_section_pages={"2": [8, 9, 10]},
                     bill_mm_sections={"2": ["2"]})
SMM2 = DocIndexEntry(filename="GP&PP/I-ND_2025_04-SMM_S02-0.pdf", kind="method_of_measurement",
                     spec_section_number="2", spec_section_title="GROUND INVESTIGATION",
                     text_layer=True, page_count=8)
PS28 = DocIndexEntry(filename="S/PS/PS28/I-ND_2025_04-S_PS28-0.pdf", kind="particular_specification",
                     spec_section_number="28", spec_section_title="Environmental Ground Investigation",
                     spec_section_title_source="ps_index", text_layer=True, page_count=40)

SCOPE = ScopePackages(project_name=NAME, packages=[TradeWorkPackage(
    trade="ground_investigation", scope_summary="Ground investigation",
    sections=[SectionMeta(code="2", title="GROUND INVESTIGATION FIELDWORKS", item_count=1)],
    sor_items=[SorItem(item_ref="2.1", description="Rotary drilling", section="2", clause_refs=[])])])


@pytest.fixture
def client():
    import api

    return TestClient(api.app)


@pytest.fixture
def tender(monkeypatch, tmp_path):
    """The pack as the bridge leaves it: registered under its set_id, index written there, and a
    STALE index sitting under the slug the display name resolves to."""
    monkeypatch.setenv("SITESOURCE_WORKDIR", str(tmp_path))   # NOT ..._WORKSPACE — see Workspace()
    monkeypatch.setenv("DEMO_MODE", "false")     # DEMO short-circuits the workspace entirely
    ws = Workspace()
    register_set(SET_ID, NAME)
    save_doc_index(ws, SET_ID, [BILL, SMM2, PS28])
    save_doc_index(ws, NAME, [])                 # the stale 570-byte one, in the other directory
    return ws


# -- the two identities --------------------------------------------------------------------------
def test_the_slug_does_not_reconcile_the_two_names_a_tender_is_known_by():
    """The mechanism, isolated. Neither string is wrong; they are simply not the same directory."""
    assert tender_slug(SET_ID) == SET_ID
    assert tender_slug(NAME) == "nd-2025-04"
    assert tender_slug(SET_ID) != tender_slug(NAME)


def test_the_registry_resolves_the_display_name_to_the_set_id(tender):
    assert tender_ref(NAME) == SET_ID
    assert tender_ref(SET_ID) == SET_ID, "already canonical, unchanged"


def test_an_unregistered_tender_resolves_to_itself(tender):
    """The pure procurement path has no bridge row, and must behave exactly as it always did."""
    assert tender_ref("Some Other Tender 2027") == "Some Other Tender 2027"
    assert tender_ref("") == ""


def test_the_resolution_is_idempotent(tender):
    assert tender_ref(tender_ref(NAME)) == SET_ID


# -- the gate and dispatch agree ----------------------------------------------------------------------
def test_the_gate_and_dispatch_resolve_to_the_same_workspace(tender, client):
    """The assertion the whole brief is about."""
    gate = client.get(f"/bridge/{SET_ID}/doc-index").json()
    assert gate["exists"] is True and gate["documents"] == 3

    plans = client.post("/dispatch/plan", json={
        "scope": SCOPE.model_dump(), "approvals": {"ground_investigation:2": ["F001"]},
        "project_name": NAME}).json()

    docs = {a["source_doc"] for p in plans for a in p["attachments"]}
    assert BILL.filename in docs, "the bill the gate can see must be the bill dispatch slices"
    assert SMM2.filename in docs and PS28.filename in docs


def test_dispatch_no_longer_reports_the_pack_empty_while_an_index_exists(tender, client):
    plans = client.post("/dispatch/plan", json={
        "scope": SCOPE.model_dump(), "approvals": {"ground_investigation:2": ["F001"]},
        "project_name": NAME}).json()
    reasons = " ".join(a["reason"] for p in plans for a in p["attachments"])

    assert "no Schedule of Rates PDF is indexed" not in reasons


def test_the_priced_return_is_the_sliced_bill_not_the_generated_sheet(tender, client):
    plans = client.post("/dispatch/plan", json={
        "scope": SCOPE.model_dump(), "approvals": {"ground_investigation:2": ["F001"]},
        "project_name": NAME}).json()
    priced = next(a for p in plans for a in p["attachments"] if "priced_return" in a["flags"])

    assert priced["source_doc"] == BILL.filename and priced["mode"] == "sliced"
    assert "substituted_priced_return" not in priced["flags"]


# -- when it genuinely cannot find one, it says where it looked ------------------------------------------
def test_the_substitution_reason_names_the_workspace_it_searched(tender, client):
    """A truly unindexed tender still substitutes — but the sentence now carries the directory, so
    a mismatch is visible instead of reading as "nothing was uploaded"."""
    plans = client.post("/dispatch/plan", json={
        "scope": ScopePackages(project_name="Unindexed Tender 2027",
                               packages=SCOPE.packages).model_dump(),
        "approvals": {"ground_investigation:2": ["F001"]},
        "project_name": "Unindexed Tender 2027"}).json()
    priced = next(a for p in plans for a in p["attachments"] if "priced_return" in a["flags"])

    assert "substituted_priced_return" in priced["flags"]
    assert "Searched:" in priced["reason"]
    assert "unindexed-tender-2027" in priced["reason"], priced["reason"]
    assert "doc_index.json" in priced["reason"]


# -- every artifact, not just the index -------------------------------------------------------------------
@pytest.mark.parametrize("artifact", [
    "doc_index_path", "scope_path",
])
def test_every_artifact_in_the_workspace_had_this_latent(tender, artifact):
    """The workspace is one directory: if it can be addressed two ways, so can everything in it."""
    ws = Workspace()
    by_name = getattr(ws, artifact)(NAME)
    by_ref = getattr(ws, artifact)(tender_ref(NAME))

    assert by_name != by_ref, "the two identities really do address different files"
    assert by_ref.parent.parent.name == SET_ID


def test_the_generated_sheets_land_where_dispatch_reads_them(tender, client):
    """`sor_sheet_path` is keyed by the same id, so a sheet written under one identity and looked
    for under the other is a file that exists and cannot be found."""
    ws = Workspace()
    assert ws.sor_sheet_path(NAME, "gi") != ws.sor_sheet_path(SET_ID, "gi")
    assert ws.sor_sheet_path(tender_ref(NAME), "gi") == ws.sor_sheet_path(SET_ID, "gi")
