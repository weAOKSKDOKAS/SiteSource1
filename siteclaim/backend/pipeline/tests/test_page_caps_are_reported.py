"""A document read in part is not a document read — so the caps say when they bite.

Two caps in `documents.py` silently dropped content:

* `TEXT_MAX_PAGES = 200` — `for index in range(min(len(doc), text_max_pages))`. A real tender
  binder runs past 400 pages, and everything after page 200 was never opened. The extractor
  returned what reads as the whole document, and downstream that is indistinguishable from a
  document that simply says less.
* `IMAGE_MAX_PAGES = 8` — a drawing page past the eighth was skipped by an `elif` whose own
  comment said "past the image cap -> skipped".

The reply path already learned this (`REPLY_MAX_PAGES`, reported through `on_note`, added when a
dropped page read downstream as a SCOPE GAP rather than as a page nobody looked at). The same
reporting belongs on the caps that read the tender itself.

`on_note` is off by default, so every existing caller behaves exactly as it did. Both caps are now
env-overridable and the warning names the variable, the way `DEEPSEEK_MIN_MAX_TOKENS` does.
"""

import importlib

import pytest


def _pdf(pages: int, *, text: bool = True) -> bytes:
    fitz = pytest.importorskip("fitz")
    doc = fitz.open()
    for i in range(pages):
        page = doc.new_page()
        if text:
            page.insert_text((40, 60), f"Page {i + 1} — text content long enough to count as text")
    data = doc.tobytes()
    doc.close()
    return data


@pytest.fixture
def documents(monkeypatch):
    """`documents` with small caps, so the boundary is reachable without a 200-page fixture."""
    monkeypatch.setenv("DOCUMENTS_TEXT_MAX_PAGES", "3")
    monkeypatch.setenv("DOCUMENTS_IMAGE_MAX_PAGES", "1")
    from pipeline import documents as mod

    importlib.reload(mod)
    yield mod
    monkeypatch.undo()
    importlib.reload(mod)


def test_the_caps_are_env_overridable(documents):
    assert documents.TEXT_MAX_PAGES == 3 and documents.IMAGE_MAX_PAGES == 1


def test_pages_past_the_text_cap_are_reported_with_their_range(documents):
    notes: list[str] = []
    text, _images = documents.extract_document(
        _pdf(6), "application/pdf", on_note=notes.append, filename="binder.pdf")

    assert text.count("[page") == 3, "the cap still bites — this is a report, not a raise"
    assert len(notes) == 1
    assert "3 page(s) of 'binder.pdf' were NOT READ" in notes[0]
    assert "Pages 4-6 contributed nothing" in notes[0]
    assert "DOCUMENTS_TEXT_MAX_PAGES" in notes[0], "the warning names the variable to raise"


def test_a_document_inside_the_cap_says_nothing(documents):
    notes: list[str] = []
    documents.extract_document(_pdf(2), "application/pdf", on_note=notes.append, filename="short.pdf")
    assert notes == [], "a cap that did not bite must not produce a warning"


def test_the_report_is_off_by_default_so_no_existing_caller_changes(documents):
    text, _images = documents.extract_document(_pdf(6), "application/pdf")
    assert text.count("[page") == 3, "byte-for-byte the behaviour every current caller sees"


def test_the_cap_still_returns_what_it_did_read(documents):
    """Reporting is not refusing. The first pages are still extracted and still usable."""
    text, _images = documents.extract_document(_pdf(6), "application/pdf")
    assert "Page 1" in text and "Page 3" in text and "Page 4" not in text


def test_a_bad_env_value_falls_back_to_the_default(monkeypatch):
    monkeypatch.setenv("DOCUMENTS_TEXT_MAX_PAGES", "not-a-number")
    from pipeline import documents as mod

    importlib.reload(mod)
    try:
        assert mod.TEXT_MAX_PAGES == 200
    finally:
        monkeypatch.undo()
        importlib.reload(mod)


def test_the_ingest_upload_path_passes_its_note_channel():
    """The seam: `/ingest-upload` already has an `on_error` channel for exactly this kind of
    warning, and the cap reports through it. Asserted on the source rather than by uploading a
    400-page binder, because the wiring is the thing that was missing."""
    import ast
    import pathlib

    src = pathlib.Path(__file__).resolve().parents[2] / "api.py"
    tree = ast.parse(src.read_text(encoding="utf-8"))
    calls = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "extract_document"]
    ingest_calls = [c for c in calls if any(k.arg == "on_note" for k in c.keywords)]

    assert len(ingest_calls) >= 2, (
        "both /ingest-upload extractions (plain and table-aware) must report their caps")
