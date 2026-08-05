"""A priced return past the render cap: read further, and never lose a page silently.

`IMAGE_MAX_PAGES = 8` with `range(min(len(doc), max_pages))` dropped page 9 onward of a PDF with no
warning, no exception and no note. That was latent while every return came back as a workbook. Now
that firms are sent a sliced section and reply in kind it is load-bearing: a CEDD bill section runs
past 8 pages, and a page nobody looked at reads downstream as a SCOPE GAP — a fact about the firm's
bid rather than about our renderer.

Two halves:

* the cap the REPLY path uses is `REPLY_MAX_PAGES` (40), not the sampling cap. A return is the
  whole answer, not a document we are sampling, so its length is set by the section it prices.
* when the cap still bites, the pages are NAMED. Silence is the failure mode this exists to end.

`IMAGE_MAX_PAGES` itself is unchanged: two existing tests pin it at 8 as a recorded defect, and
this fix does not edit them. See the report.
"""

import pytest
from pipeline import documents


def _pdf(pages: int) -> bytes:
    fitz = pytest.importorskip("fitz")
    doc = fitz.open()
    for n in range(pages):
        page = doc.new_page()
        page.insert_text((50, 60), f"SCHEDULE OF RATES — priced (sheet {n + 1})", fontsize=10)
        page.insert_text((50, 80), f"G{n + 1}   Item {n + 1}   m   10   850.00", fontsize=9)
    out = doc.tobytes()
    doc.close()
    return out


# -- the cap the reply path reads to ---------------------------------------------------------------
def test_the_reply_cap_is_higher_than_the_sampling_cap():
    assert documents.REPLY_MAX_PAGES > documents.IMAGE_MAX_PAGES
    assert documents.REPLY_MAX_PAGES >= 40      # a CEDD bill section, end to end


def test_a_twelve_page_return_now_comes_back_whole():
    """The exact case that used to lose four pages."""
    import api

    _sheets, images = api._read_reply_files([("return.pdf", "application/pdf", _pdf(12))])
    assert len(images) == 12


def test_a_return_at_the_cap_is_complete_and_says_nothing():
    import api

    notes: list[str] = []
    _sheets, images = api._read_reply_files(
        [("return.pdf", "application/pdf", _pdf(documents.REPLY_MAX_PAGES))], notes)
    assert len(images) == documents.REPLY_MAX_PAGES
    assert notes == []                          # nothing was dropped, so nothing is claimed


# -- and when it still bites, it says so ------------------------------------------------------------
def test_pages_past_the_cap_are_named_not_dropped_in_silence():
    dropped: list[str] = []
    images = documents.to_images(_pdf(6), "application/pdf", max_pages=4,
                                 on_note=dropped.append)

    assert len(images) == 4
    assert len(dropped) == 1
    assert "pages 5-6 of 6 were NOT read" in dropped[0]
    assert "DOCUMENTS_REPLY_MAX_PAGES" in dropped[0]     # and how to change it


def test_the_warning_names_the_file_it_is_about():
    import api

    notes: list[str] = []
    api._read_reply_files([("F001-section-G.pdf", "application/pdf", _pdf(3))], notes)
    assert notes == []

    monkey = documents.REPLY_MAX_PAGES
    try:
        documents.REPLY_MAX_PAGES = 2
        api._read_reply_files([("F001-section-G.pdf", "application/pdf", _pdf(3))], notes)
    finally:
        documents.REPLY_MAX_PAGES = monkey
    assert notes and notes[0].startswith("F001-section-G.pdf: ")


def test_the_note_is_optional_so_every_existing_caller_is_unchanged():
    # `_read_reply_files` still returns a 2-tuple and still works with no notes list at all.
    import api

    sheets, images = api._read_reply_files([("return.pdf", "application/pdf", _pdf(2))])
    assert sheets == [] and len(images) == 2


def test_the_cap_is_env_overridable():
    import os

    os.environ["DOCUMENTS_REPLY_MAX_PAGES"] = "7"
    try:
        assert documents._reply_max_pages() == 7
    finally:
        del os.environ["DOCUMENTS_REPLY_MAX_PAGES"]
    assert documents._reply_max_pages() == 40           # and a garbage value falls back, not raises


def test_a_nonsense_override_falls_back_rather_than_crashing_the_reply_path():
    import os

    os.environ["DOCUMENTS_REPLY_MAX_PAGES"] = "not-a-number"
    try:
        assert documents._reply_max_pages() == 40
    finally:
        del os.environ["DOCUMENTS_REPLY_MAX_PAGES"]


# -- it reaches the reply, not just the log ---------------------------------------------------------
def test_a_dropped_page_reaches_the_inbound_reply_response(monkeypatch, tmp_path):
    """`extras` is the reply's own notes channel — it is on the response AND in the comparison
    workbook, so the warning travels with the bid rather than living in a log nobody opens."""
    import api
    from pipeline import reply_loop
    from pipeline.workspace import Workspace

    monkeypatch.setenv("SITESOURCE_WORKDIR", str(tmp_path))
    monkeypatch.setenv("DEMO_MODE", "false")
    monkeypatch.setattr(documents, "REPLY_MAX_PAGES", 2)

    class ScriptedClient:
        def complete_json(self, **_kw):
            from schemas.models import BidLineItem, BidReply

            return BidReply(firm_id="F1", trade="ground_investigation",
                            line_items=[BidLineItem(item_ref="G1", rate=850.0)])

    from pipeline.stage_04_level import level as level_mod
    monkeypatch.setattr(level_mod, "LLMClient", lambda *a, **k: ScriptedClient())

    ws = Workspace()
    reply_loop.record_dispatch(ws, "REF-1", "gi-2026-11", "F1", "ground_investigation")

    notes: list[str] = []
    sheets, images = api._read_reply_files(
        [("return.pdf", "application/pdf", _pdf(5))], notes)
    assert notes, "the cap bit, so there must be a note to carry"

    out = api.process_inbound_reply("REF-1", sheets, images, notes=notes)
    assert out.status == "matched"
    assert any("were NOT read" in e for e in out.extras)
    # FIRST in the list: a reply built from part of a DOCUMENT is a different thing from a reply
    # that priced part of a schedule, and that has to be read before anything else on the list.
    assert "were NOT read" in out.extras[0]
