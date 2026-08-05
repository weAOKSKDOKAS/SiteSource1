"""FIX 6 — the PDF return path, exercised for the first time, and costed.

Subcontractors return PDF, not xlsx. ``_read_reply_files`` already routes a non-xlsx through
``to_images`` + the vision parse, so PDF is supported BY DESIGN — and had never been run on a real
returned PDF. Nothing here changes format handling; this drives the shared path and measures it.

**The fixture is BUILT FROM THE DISPATCHED SoR, not from a real return.** There is no priced
returned PDF in this repo. The items, refs, units and quantities are the dispatched schedule's own;
the RATES are test values, because a rate is the one thing only a subcontractor can supply. Said
plainly here so nobody later reads these numbers as evidence about a real bid.

Two costs this file measures, because FIX 9 moves EVERY return onto this path:

* **Calls are per THREE pages, not per page.** ``parse_bid_reply`` groups images through
  ``_chunk_pages(images, IMAGE_PAGES_PER_CHUNK)`` with ``IMAGE_PAGES_PER_CHUNK = 3``, so an
  N-page return costs ``ceil(N/3)`` vision calls. A pure xlsx return costs ZERO.
* **``IMAGE_MAX_PAGES = 8``, and the cap is SILENT.** ``_pdf_to_pngs`` does
  ``range(min(len(doc), max_pages))`` with no warning and no note on the reply, so a 9-page priced
  return is parsed as its first 8 pages and the rest is simply gone. That is pinned below as
  known behaviour, not endorsed — see the report.
"""

import pytest
from pipeline import documents
from pipeline.stage_04_level import level as level_mod
from schemas.models import BidLineItem, BidReply, SorItem, TradeWorkPackage

# The dispatched schedule this return is built from — a real package shape, not an invented one.
PACKAGE = TradeWorkPackage(
    trade="ground_investigation", scope_summary="Ground investigation fieldworks",
    sor_items=[
        SorItem(item_ref="G1", description="Cable percussion borehole, 150mm", unit="m", qty=120.0,
                section="G"),
        SorItem(item_ref="G2", description="Rotary core drilling in rock", unit="m", qty=80.0,
                section="G"),
        SorItem(item_ref="G3", description="Standard penetration test", unit="nr", qty=200.0,
                section="G"),
        SorItem(item_ref="H1", description="Standpipe piezometer installation", unit="nr", qty=12.0,
                section="H"),
    ],
)

# Test rates. NOT from a real return — see the module docstring.
RATES = {"G1": 850.0, "G2": 1450.0, "G3": 320.0, "H1": 2100.0}


def _returned_pdf(pages: int = 4) -> bytes:
    """The dispatched SoR, rendered as the PDF a subcontractor would send back priced.

    One header row per page plus the items, spread over ``pages`` sheets so the multi-page path is
    the one under test — a single-page return would never reach ``_chunk_pages`` at all.
    """
    fitz = pytest.importorskip("fitz")
    doc = fitz.open()
    rows = [(i.item_ref, i.description, i.unit, i.qty, RATES[i.item_ref]) for i in PACKAGE.sor_items]
    per_page = max(1, -(-len(rows) // pages))
    for p in range(pages):
        page = doc.new_page()
        page.insert_text((40, 50), f"SCHEDULE OF RATES — priced return (sheet {p + 1})", fontsize=10)
        page.insert_text((40, 70), "Item   Description                        Unit  Qty     Rate",
                         fontsize=8)
        y = 90
        for ref, desc, unit, qty, rate in rows[p * per_page:(p + 1) * per_page]:
            page.insert_text((40, y), f"{ref}   {desc[:34]:<34} {unit:<5} {qty:<7.1f} {rate:.2f}",
                             fontsize=8)
            y += 16
    out = doc.tobytes()
    doc.close()
    return out


class CountingClient:
    """Stands in for Layer 2 and counts calls. Returns the items it was shown, so the assertions
    are about ROUTING and merging rather than about a model's reading."""

    def __init__(self, items_per_page: int = 1):
        self.calls: list[int] = []          # images per call
        self.items_per_page = items_per_page
        self._cursor = 0                    # which schedule item the next page carries

    def complete_json(self, *, system, user, target_model, images=None, **_kw):
        n = len(images or [])
        self.calls.append(n)
        # The items the pages in THIS call carry. Tracked by a cursor rather than recomputed from
        # the call index, because `_chunk_pages` groups by three and the last group is short — an
        # index-based split would silently drop the tail and the test would pass for the wrong
        # reason (which it did, on the first draft of this stub).
        take = max(1, n) * self.items_per_page
        chunk = PACKAGE.sor_items[self._cursor:self._cursor + take]
        self._cursor += take
        return BidReply(firm_id="", trade="", line_items=[
            BidLineItem(item_ref=i.item_ref, description=i.description, unit=i.unit, qty=i.qty,
                        rate=RATES[i.item_ref], amount=i.qty * RATES[i.item_ref])
            for i in chunk
        ])


@pytest.fixture
def counting(monkeypatch):
    client = CountingClient()
    monkeypatch.setattr(level_mod, "LLMClient", lambda *a, **k: client)
    return client


# ---------------------------------------------------------------------------
# It parses, and the rates come back
# ---------------------------------------------------------------------------
def test_a_returned_pdf_yields_its_line_items_and_rates(counting):
    import api

    sheets, images = api._read_reply_files([("return.pdf", "application/pdf", _returned_pdf(4))])
    assert sheets == []                       # a PDF is not the deterministic xlsx path
    assert len(images) == 4                   # one rasterised page each

    reply = api._parse_reply(sheets, images, firm_id="F1", trade="ground_investigation")
    by_ref = {li.item_ref: li.rate for li in reply.line_items}
    assert by_ref == RATES
    assert reply.firm_id == "F1"              # identity stays the ref's, never the document's


def test_the_priced_lines_route_to_their_own_sections(counting):
    """The reply is filed by ITEM IDENTITY against the canonical scope, not by the enquiry's
    trade — a firm routinely prices items from more sections than it was asked about."""
    import api
    from schemas.models import ScopePackages

    scope = ScopePackages(project_name="GI", packages=[PACKAGE])
    sheets, images = api._read_reply_files([("return.pdf", "application/pdf", _returned_pdf(4))])
    parsed = api._parse_reply(sheets, images, firm_id="F1", trade="ground_investigation")
    new_replies, _extras, coverage = api._route_reply(
        parsed, scope, firm_id="F1", trade="ground_investigation", tender_id="GI")

    assert new_replies                        # something was routed
    priced = {li.item_ref for r in new_replies for li in r.line_items}
    assert priced == set(RATES)
    assert {c.section for c in coverage} <= {"G", "H", ""}


# ---------------------------------------------------------------------------
# The cost — measured, because FIX 9 moves every return onto this path
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("pages,expected_calls", [(1, 1), (3, 1), (4, 2), (6, 2), (7, 3), (8, 3)])
def test_the_call_count_is_per_three_pages_not_per_page(counting, pages, expected_calls):
    """The brief assumed one vision call per page. `_chunk_pages` groups them:
    `IMAGE_PAGES_PER_CHUNK = 3`, so an N-page return costs ceil(N/3) calls."""
    import api

    assert level_mod.IMAGE_PAGES_PER_CHUNK == 3
    sheets, images = api._read_reply_files(
        [("return.pdf", "application/pdf", _returned_pdf(pages))])
    api._parse_reply(sheets, images, firm_id="F1", trade="ground_investigation")
    assert len(counting.calls) == expected_calls
    assert sum(counting.calls) == pages       # every page reached a call, none dropped


def test_a_workbook_return_costs_no_model_call_at_all(counting):
    """The comparison that makes the PDF cost meaningful. `_parse_reply` short-circuits on
    sheets-and-no-images, so the deterministic path never reaches Layer 2."""
    import api

    reply = api._parse_reply(
        [BidReply(firm_id="", trade="", line_items=[BidLineItem(item_ref="G1", rate=1.0)])],
        [], firm_id="F1", trade="ground_investigation")
    assert counting.calls == []
    assert reply.line_items[0].item_ref == "G1"


# ---------------------------------------------------------------------------
# The cap, pinned as known behaviour — NOT endorsed
# ---------------------------------------------------------------------------
def test_a_return_longer_than_eight_pages_is_silently_truncated():
    """`IMAGE_MAX_PAGES = 8`, and `_pdf_to_pngs` does `range(min(len(doc), max_pages))` with no
    warning, no exception and no note on the reply. A 12-page priced return is parsed as its first
    8 pages and the remaining items simply do not exist as far as the comparison is concerned.

    Pinned here so it is a recorded fact rather than a surprise on a live run. Format handling is
    out of scope for this fix and is NOT changed — but this is the blocker to clear before FIX 9
    moves every return onto this path, and it is reported as such.
    """
    assert documents.IMAGE_MAX_PAGES == 8
    images = documents.to_images(_returned_pdf(12), "application/pdf")
    assert len(images) == 8                   # four pages gone, nothing said
