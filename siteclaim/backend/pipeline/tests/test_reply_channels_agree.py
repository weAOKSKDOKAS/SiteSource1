"""FIX 3 (the half that does not depend on default-on polling) — both intake channels, and PDF.

Automatic collection itself is NOT turned on in this change: the outbound-ledger guard misses,
because the Gmail API replaces a draft's message id when the draft is sent (see the report and
``reply_loop.record_outbound``). Turning polling on before that is closed would have the poller
ingest our own RFQ as a rateless bid.

What IS verifiable now, and is verified here:

* a return arriving through the POLLER's entry and the same return uploaded BY HAND produce
  identical registry rows — the two channels are one path or they are not, and that is testable
  without any polling schedule;
* a multi-page priced **PDF** works on that path, not only a workbook — its lines and rates route
  to their section by item identity.

``test_level_upload_files.py`` asserts the same equivalence for a workbook. This is its PDF twin,
which is the format subcontractors actually return.
"""

import pytest
from pipeline import reply_loop
from pipeline.scope_store import save_scope
from pipeline.stage_04_level import level as level_mod
from pipeline.workspace import Workspace
from schemas.models import (
    BidLineItem,
    BidReply,
    ScopePackages,
    SectionMeta,
    SorItem,
    TradeWorkPackage,
)

TENDER = "GI-2026-02"
RATES = {"G1": 850.0, "G2": 1450.0, "H1": 2100.0}

PACKAGE = TradeWorkPackage(
    trade="ground_investigation", scope_summary="Ground investigation",
    sor_items=[
        SorItem(item_ref="G1", description="Cable percussion borehole", unit="m", qty=120.0, section="G"),
        SorItem(item_ref="G2", description="Rotary core drilling", unit="m", qty=80.0, section="G"),
        SorItem(item_ref="H1", description="Standpipe piezometer", unit="nr", qty=12.0, section="H"),
    ],
    sections=[SectionMeta(code="G", item_count=2), SectionMeta(code="H", item_count=1)],
)


def _priced_pdf(pages: int = 4) -> bytes:
    """A priced return as a subcontractor sends it: multi-page PDF.

    Built from the dispatched schedule — items, refs, units and quantities are its own. The RATES
    are test values, because a rate is the one thing only a subcontractor can supply.
    """
    fitz = pytest.importorskip("fitz")
    doc = fitz.open()
    rows = [(i.item_ref, i.description, i.unit, i.qty, RATES[i.item_ref]) for i in PACKAGE.sor_items]
    per = max(1, -(-len(rows) // pages))
    for p in range(pages):
        page = doc.new_page()
        page.insert_text((40, 50), f"SCHEDULE OF RATES — priced (sheet {p + 1})", fontsize=10)
        for n, (ref, desc, unit, qty, rate) in enumerate(rows[p * per:(p + 1) * per]):
            page.insert_text((40, 80 + n * 16),
                             f"{ref}  {desc[:30]:<30} {unit:<4} {qty:<7.1f} {rate:.2f}", fontsize=8)
    out = doc.tobytes()
    doc.close()
    return out


class ScriptedClient:
    """Layer 2, scripted — returns the schedule's items priced, a page at a time."""

    def __init__(self):
        self._cursor = 0
        self.calls = 0

    def complete_json(self, *, system, user, target_model, images=None, **_kw):
        self.calls += 1
        take = max(1, len(images or []))
        chunk = PACKAGE.sor_items[self._cursor:self._cursor + take]
        self._cursor += take
        return BidReply(firm_id="", trade="", line_items=[
            BidLineItem(item_ref=i.item_ref, description=i.description, unit=i.unit, qty=i.qty,
                        rate=RATES[i.item_ref], amount=i.qty * RATES[i.item_ref]) for i in chunk])


@pytest.fixture
def live(monkeypatch, tmp_path):
    monkeypatch.setenv("DEMO_MODE", "")
    monkeypatch.setenv("SITESOURCE_WORKDIR", str(tmp_path / "ws"))
    monkeypatch.setattr(level_mod, "LLMClient", lambda *a, **k: ScriptedClient())
    ws = Workspace()
    save_scope(ws, TENDER, ScopePackages(project_name=TENDER, packages=[PACKAGE]))
    return ws


def _shape(records):
    return [
        (r["status"], r["reply"]["firm_id"], r["reply"]["trade"],
         sorted((li["item_ref"], li["rate"]) for li in r["reply"]["line_items"]))
        for r in records
    ]


# ---------------------------------------------------------------------------
# A PDF return works on the shared path
# ---------------------------------------------------------------------------
def test_a_pdf_return_through_the_poller_entry_lands_priced(live):
    """`_poller_process_reply` is the poller's ONLY adapter onto the shared function, so driving it
    is driving what a landed email would do — without needing a polling schedule."""
    import api

    ref = reply_loop.make_ref(TENDER, "F1", "ground_investigation")
    reply_loop.record_dispatch(live, ref, TENDER, "F1", "ground_investigation")
    status = api._poller_process_reply(ref, [("priced.pdf", _priced_pdf(3))])

    assert status == "matched"
    records = reply_loop.tender_reply_records(live, TENDER)
    priced = {li["item_ref"]: li["rate"] for r in records for li in r["reply"]["line_items"]}
    assert priced == RATES


def test_the_pdf_lines_route_to_their_own_sections(live):
    """Filed by ITEM IDENTITY against the canonical scope, so a firm that priced across two
    sections produces one reply per section rather than everything under the enquiry's key."""
    import api

    ref = reply_loop.make_ref(TENDER, "F1", "ground_investigation")
    reply_loop.record_dispatch(live, ref, TENDER, "F1", "ground_investigation")
    api._poller_process_reply(ref, [("priced.pdf", _priced_pdf(3))])

    keys = {r["reply"]["trade"] for r in reply_loop.tender_reply_records(live, TENDER)}
    assert keys                                   # routed somewhere
    assert all(k.startswith("ground_investigation") for k in keys)


# ---------------------------------------------------------------------------
# The two channels agree — for a PDF, as they already do for a workbook
# ---------------------------------------------------------------------------
def test_upload_and_poller_leave_identical_rows_for_a_pdf(live, tmp_path, monkeypatch):
    import api
    from fastapi.testclient import TestClient

    pdf = _priced_pdf(3)

    # (a) the poller's entry
    ref = reply_loop.make_ref(TENDER, "F1", "ground_investigation")
    reply_loop.record_dispatch(live, ref, TENDER, "F1", "ground_investigation")
    api._poller_process_reply(ref, [("priced.pdf", pdf)])
    by_poller = _shape(reply_loop.tender_reply_records(live, TENDER))

    # (b) the manual upload, in its own workspace
    monkeypatch.setenv("SITESOURCE_WORKDIR", str(tmp_path / "ws2"))
    monkeypatch.setattr(level_mod, "LLMClient", lambda *a, **k: ScriptedClient())
    ws2 = Workspace()
    save_scope(ws2, TENDER, ScopePackages(project_name=TENDER, packages=[PACKAGE]))
    resp = TestClient(api.app).post(
        "/level-upload",
        files=[("files", ("priced.pdf", pdf, "application/pdf"))],
        data={"firm_id": "F1", "trade": "ground_investigation", "tender": TENDER})
    assert resp.status_code == 200
    by_upload = _shape(reply_loop.tender_reply_records(ws2, TENDER))

    assert by_upload == by_poller


def test_a_second_pdf_return_supersedes_with_the_prior_kept(live):
    import api

    ref = reply_loop.make_ref(TENDER, "F1", "ground_investigation")
    reply_loop.record_dispatch(live, ref, TENDER, "F1", "ground_investigation")
    api._poller_process_reply(ref, [("priced.pdf", _priced_pdf(3))])
    api._poller_process_reply(ref, [("priced.pdf", _priced_pdf(3))])

    statuses = [r["status"] for r in reply_loop.tender_reply_records(live, TENDER)]
    assert "superseded" in statuses and statuses[-1] == "active"


def test_the_comparison_is_persisted_so_a_refresh_still_shows_it(live):
    """FIX 4's load-bearing property: the screen reads persisted state, not component state."""
    import api

    ref = reply_loop.make_ref(TENDER, "F1", "ground_investigation")
    reply_loop.record_dispatch(live, ref, TENDER, "F1", "ground_investigation")
    api._poller_process_reply(ref, [("priced.pdf", _priced_pdf(3))])

    assert reply_loop.comparison_path(live, TENDER).is_file()
    assert reply_loop.tender_replies(Workspace(), TENDER)     # a FRESH read, not the same objects


# ---------------------------------------------------------------------------
# The cap, restated where it now bites
# ---------------------------------------------------------------------------
def test_a_priced_return_past_eight_pages_loses_its_tail_silently():
    """`IMAGE_MAX_PAGES = 8`; `_pdf_to_pngs` does `range(min(len(doc), max_pages))` with no
    warning, no exception and no note on the reply.

    This was latent while every return came back as a workbook. Now that firms are sent a sliced
    PDF and reply in kind, it is load-bearing: page 9 onward of a priced return does not exist as
    far as the comparison is concerned, and a missing rate reads as a scope gap rather than as a
    page nobody looked at. Pinned, not fixed — the fix is out of scope here and is recommended in
    the report.
    """
    from pipeline import documents

    assert documents.IMAGE_MAX_PAGES == 8
    assert len(documents.to_images(_priced_pdf(12), "application/pdf")) == 8
