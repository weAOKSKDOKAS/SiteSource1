"""FIX 1 — a manually uploaded return is filed exactly as a polled one.

Reported live: a subcontractor returned a filled Schedule of Rates as an xlsx and it never
appeared in Level & compare.

``/level-upload`` parsed the upload, called ``level_bids`` on that ONE reply, wrote ``OUT_PATH``
and returned. It never called ``accumulate_replies``, never wrote the tender's replies registry,
and never regenerated the tender comparison — all three of which ``process_inbound_reply`` (the
Gmail poller's path) does. So the two intake channels that are meant to be one path were not: a
polled reply accumulates, supersedes and re-levels against every other reply on the tender; an
uploaded one was levelled alone, in memory, and gone on refresh. ``tenderReplies`` reads the
registry the upload never wrote, so the screen kept the firm as awaiting.

The last test here is the one that matters: the SAME return, once by upload and once through the
poller path, must leave the registry in the same state. Anything less is two paths again.
"""

import io

import api
import pytest
from fastapi.testclient import TestClient
from pipeline import reply_loop
from pipeline.scope_store import save_scope
from pipeline.workspace import Workspace
from schemas.models import ScopePackages, SectionMeta, SorItem, TradeWorkPackage

client = TestClient(api.app)

TENDER = "GI-2026-01"


@pytest.fixture
def live(monkeypatch, tmp_path):
    """Live mode against a throwaway workspace — DEMO returns the baked fixture and files nothing."""
    monkeypatch.setenv("DEMO_MODE", "")
    monkeypatch.setenv("SITESOURCE_WORKDIR", str(tmp_path / "work"))
    ws = Workspace()
    save_scope(ws, TENDER, ScopePackages(project_name=TENDER, packages=[
        TradeWorkPackage(
            trade="ground_investigation", scope_summary="GI",
            sor_items=[SorItem(item_ref=r, description=f"item {r}", unit="m", qty=1.0, section=r[0])
                       for r in ("G1", "G2", "H1")],
            sections=[SectionMeta(code="G", item_count=2), SectionMeta(code="H", item_count=1)]),
    ]))
    return ws


def _priced_xlsx(rows: list[tuple[str, float]]) -> bytes:
    """Our own dispatched SoR sheet, returned with the Rate column filled.

    Built to the shape ``parse_sor_xlsx`` reads, so this exercises the deterministic zero-model
    return path — the one a subcontractor actually uses when they fill in the workbook we sent.
    """
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.Workbook()
    sh = wb.active
    sh.append(["Item Ref", "Description", "Unit", "Qty", "Rate"])
    for ref, rate in rows:
        sh.append([ref, f"item {ref}", "m", 1, rate])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _upload(firm: str, rows: list[tuple[str, float]], trade="ground_investigation", tender=TENDER):
    return client.post("/level-upload", files=[
        ("files", ("SoR_return.xlsx", _priced_xlsx(rows),
                   "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")),
    ], data={"firm_id": firm, "trade": trade, "tender": tender})


def _records(ws, tender=TENDER):
    return reply_loop.tender_reply_records(ws, tender)


# ---------------------------------------------------------------------------
# It lands, and it stays
# ---------------------------------------------------------------------------
def test_an_uploaded_return_reaches_the_replies_registry(live):
    assert _upload("F1", [("G1", 10.0), ("G2", 20.0)]).status_code == 200
    records = _records(live)
    assert len(records) == 1
    assert records[0]["reply"]["firm_id"] == "F1"
    assert records[0]["status"] == "active"


def test_it_survives_a_re_read(live):
    """The defect in one assertion: it was levelled in memory and gone on refresh."""
    _upload("F1", [("G1", 10.0)])
    assert reply_loop.tender_replies(Workspace(), TENDER)      # a fresh read, not the same objects


def test_it_is_visible_from_the_tender_replies_endpoint(live):
    """`tenderReplies` reads the registry the upload never used to write — which is why the screen
    kept showing the firm as awaiting after a successful upload."""
    _upload("F1", [("G1", 10.0)])
    body = client.get(f"/tender/{TENDER}/replies").json()
    assert [r["firm_id"] for r in body["replies"]] == ["F1"]
    assert body["replies"][0]["status"] == "active"


def test_the_response_shape_did_not_move(live):
    """`LevelUploadResponse` is the frontend contract and stays exactly as it was."""
    body = _upload("F1", [("G1", 10.0)]).json()
    assert set(body) == {"levelled", "misdirected"}
    assert isinstance(body["levelled"], list)


# ---------------------------------------------------------------------------
# Supersede, and level against each other
# ---------------------------------------------------------------------------
def test_a_second_upload_supersedes_the_first_and_keeps_it_on_file(live):
    _upload("F1", [("G1", 10.0)])
    _upload("F1", [("G1", 99.0)])
    records = _records(live)
    assert [r["status"] for r in records] == ["superseded", "active"]
    active = reply_loop.tender_replies(Workspace(), TENDER)
    assert [li.rate for r in active for li in r.line_items if li.item_ref == "G1"] == [99.0]


def test_two_firms_level_against_each_other_in_one_comparison(live):
    """The whole point of accumulating. Levelled alone, two uploads were two comparisons of one."""
    _upload("F1", [("G1", 10.0)])
    body = _upload("F2", [("G1", 12.0)]).json()
    assert sorted({b["firm_id"] for b in body["levelled"]}) == ["F1", "F2"]


def test_the_tender_comparison_workbook_is_regenerated(live):
    _upload("F1", [("G1", 10.0)])
    assert reply_loop.comparison_path(live, TENDER).is_file()


# ---------------------------------------------------------------------------
# The equivalence — the assertion the fix exists for
# ---------------------------------------------------------------------------
def test_upload_and_poller_leave_the_same_registry_state(live, tmp_path, monkeypatch):
    """The same return, once by upload and once through the poller path, must produce the same
    registry state. If these ever diverge there are two intake paths again."""
    rows = [("G1", 10.0), ("H1", 30.0)]
    _upload("F1", rows)
    by_upload = _records(live)

    # A second, identical workspace driven through the POLLER's entry: a recorded dispatch ref,
    # resolved deterministically, then the same shared function.
    monkeypatch.setenv("SITESOURCE_WORKDIR", str(tmp_path / "work2"))
    ws2 = Workspace()
    save_scope(ws2, TENDER, ScopePackages(project_name=TENDER, packages=[
        TradeWorkPackage(
            trade="ground_investigation", scope_summary="GI",
            sor_items=[SorItem(item_ref=r, description=f"item {r}", unit="m", qty=1.0, section=r[0])
                       for r in ("G1", "G2", "H1")],
            sections=[SectionMeta(code="G", item_count=2), SectionMeta(code="H", item_count=1)]),
    ]))
    ref = reply_loop.make_ref(TENDER, "F1", "ground_investigation")
    reply_loop.record_dispatch(ws2, ref, TENDER, "F1", "ground_investigation")
    api._poller_process_reply(ref, [("SoR_return.xlsx", _priced_xlsx(rows))])
    by_poller = reply_loop.tender_reply_records(ws2, TENDER)

    def shape(records):
        return [
            (r["status"], r["reply"]["firm_id"], r["reply"]["trade"],
             sorted((li["item_ref"], li["rate"]) for li in r["reply"]["line_items"]))
            for r in records
        ]

    assert shape(by_upload) == shape(by_poller)


def test_the_upload_path_writes_no_correlation_ref(live):
    """It must not INVENT a ref. The registry is what a genuine reply resolves against, and a
    fabricated entry there would be a ref no email will ever carry."""
    _upload("F1", [("G1", 10.0)])
    assert reply_loop.outstanding_dispatches(Workspace()) == []


def test_an_upload_with_no_tender_still_levels_rather_than_failing(live):
    """No tender means no registry to file against, and inventing a slug would file the return
    under a tender that does not exist. Every caller in this repo passes the set id, so this is
    the unreachable branch — but it must degrade, not 500."""
    resp = _upload("F1", [("G1", 10.0)], tender="")
    assert resp.status_code == 200
    assert resp.json()["levelled"]
    assert _records(live) == []
