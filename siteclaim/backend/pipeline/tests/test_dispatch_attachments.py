"""Stage 03 dispatch with real routed attachments (Phase A) — the bundle carries
general docs + this trade's docs + the generated SoR sheet, while ``bundle_doc_refs``
(the human-readable labels) keeps its existing behaviour."""

import pytest

from db import seed, store
from pipeline.stage_01_ingest.ingest import ingest_tender
from pipeline.stage_02_shortlist.shortlist import shortlist
from pipeline.stage_03_dispatch.dispatch import build_dispatch
from pipeline.workspace import Workspace
from schemas.models import AttachmentKind, DocType, TenderDocument, TenderPackage

_SCOPE_FIXTURE = "cases/clean/scope_packages.json"
_DISPATCH_FIXTURE = "cases/clean/dispatch.json"


@pytest.fixture(scope="module")
def conn(tmp_path_factory):
    db_path = tmp_path_factory.mktemp("dispatch_att") / "test.db"
    seed.build_database(db_path)
    connection = store.get_connection(db_path)
    yield connection
    connection.close()


@pytest.fixture
def scope():
    return ingest_tender(TenderPackage(project_name="Kwun Tong Commercial Tower"), demo_fixture=_SCOPE_FIXTURE)


@pytest.fixture
def shortlisted(conn, scope):
    return shortlist(scope, conn=conn)


def _tender():
    return TenderPackage(project_name="Kwun Tong Commercial Tower", documents=[
        TenderDocument(doc_type=DocType.METHOD_OF_MEASUREMENT, filename="mom.pdf"),
        TenderDocument(doc_type=DocType.SCHEDULE_OF_RATES, filename="sor.pdf"),
    ])


def test_bundle_gets_general_docs_and_a_generated_sor_sheet(shortlisted, scope, tmp_path):
    ws = Workspace(root=tmp_path)
    ds = build_dispatch(
        shortlisted, {"electrical": ["F-EL-02"]}, demo_fixture=_DISPATCH_FIXTURE,
        scope=scope, project_name=scope.project_name, tender=_tender(),
        tender_id=scope.project_name, workspace=ws,
    )
    bundle = ds.bundles[0]
    kinds = {a.kind for a in bundle.attachments}
    assert AttachmentKind.GENERAL in kinds and AttachmentKind.SOR_SHEET in kinds
    sor = next(a for a in bundle.attachments if a.kind is AttachmentKind.SOR_SHEET)
    assert sor.source_path  # the sheet was really generated to the workspace
    # the legacy label list is untouched — still names this trade's package
    assert any("scope & SoR package" in ref for ref in bundle.bundle_doc_refs)


def test_without_tender_or_workspace_the_sor_sheet_is_still_described(shortlisted, scope):
    ds = build_dispatch(
        shortlisted, {"electrical": ["F-EL-02"]}, demo_fixture=_DISPATCH_FIXTURE,
        scope=scope, project_name=scope.project_name,
    )
    bundle = ds.bundles[0]
    assert {a.kind for a in bundle.attachments} == {AttachmentKind.SOR_SHEET}
    assert all(a.source_path is None for a in bundle.attachments)  # no disk side effects


def test_attachments_are_shared_per_trade_not_regenerated_per_firm(shortlisted, scope, tmp_path):
    ws = Workspace(root=tmp_path)
    ds = build_dispatch(
        shortlisted, {"electrical": ["F-EL-02", "F-EL-03"]}, demo_fixture=_DISPATCH_FIXTURE,
        scope=scope, project_name=scope.project_name, tender=_tender(),
        tender_id=scope.project_name, workspace=ws,
    )
    by_firm = {b.firm_id: b for b in ds.bundles}
    el2_sor = next(a.source_path for a in by_firm["F-EL-02"].attachments if a.kind is AttachmentKind.SOR_SHEET)
    el3_sor = next(a.source_path for a in by_firm["F-EL-03"].attachments if a.kind is AttachmentKind.SOR_SHEET)
    assert el2_sor == el3_sor  # one sheet per trade, shared
