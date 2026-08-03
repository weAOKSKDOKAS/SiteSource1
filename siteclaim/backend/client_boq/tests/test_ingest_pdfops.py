"""Spec for the deterministic half of ingest: inspect, the confidence ladder, validate, slice.

No model and no network anywhere in this file — every assertion is about arithmetic over real
PDF bytes, which is the whole point of keeping the cut deterministic.
"""

import pytest

from client_boq.ingest import pdfops
from client_boq.models import (
    TIER_BOOKMARKS,
    TIER_HEURISTIC,
    TIER_TOC,
    TIER_WHOLE,
    PartSpec,
    SplitManifest,
)

fitz = pytest.importorskip("fitz")  # PyMuPDF


def _pdf(pages: list[str], bookmarks: list[tuple[int, str, int]] | None = None) -> bytes:
    doc = fitz.open()
    for body in pages:
        page = doc.new_page()
        if body:
            page.insert_text((72, 100), body, fontsize=11)
    if bookmarks:
        doc.set_toc([list(b) for b in bookmarks])
    data = doc.tobytes()
    doc.close()
    return data


def _scanned_pdf(pages: int) -> bytes:
    """Pages carrying only a blank image — no text layer at all."""
    doc = fitz.open()
    for _ in range(pages):
        page = doc.new_page()
        pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 200, 200))
        pix.clear_with(255)
        page.insert_image(page.rect, pixmap=pix)
    data = doc.tobytes()
    doc.close()
    return data


# -- tier 1: the document's own bookmarks ----------------------------------
def test_bookmarks_give_tier_1_and_contiguous_parts():
    data = _pdf(
        ["cover", "conditions", "more conditions", "scope", "scope 2", "pricing"],
        bookmarks=[(1, "Conditions of Tender", 2), (1, "Scope of Works", 4), (1, "Pricing", 6)],
    )
    report = pdfops.inspect(data, "tender.pdf")

    assert report.pages == 6
    assert report.draft.tier == TIER_BOOKMARKS
    # Page 1 precedes the first bookmark and must NOT vanish — it becomes front matter.
    assert [(p.start, p.end) for p in report.draft.parts] == [(1, 1), (2, 3), (4, 5), (6, 6)]
    assert report.draft.coverage() == 6


def test_every_page_is_accounted_for_whatever_the_outline_says():
    data = _pdf([f"page {i}" for i in range(10)], bookmarks=[(1, "A", 3), (1, "B", 7)])
    report = pdfops.inspect(data, "t.pdf")
    covered = sorted(p for part in report.draft.parts for p in range(part.start, part.end + 1))
    assert covered == list(range(1, 11))  # no gaps, no repeats


def test_a_deeper_outline_is_cut_at_the_requested_depth():
    data = _pdf(
        [f"p{i}" for i in range(8)],
        bookmarks=[(1, "Part One", 1), (2, "1.1 Intro", 2), (2, "1.2 Terms", 4),
                   (1, "Part Two", 6), (2, "2.1 Scope", 7)],
    )
    # Depth 2 cuts at the subsections. Page 1 sits before the first of them, so it is kept as
    # front matter rather than dropped.
    deep = pdfops.inspect(data, "t.pdf", depth=2)
    assert [p.title for p in deep.draft.parts][1:] == ["1.1 Intro", "1.2 Terms", "2.1 Scope"]
    assert deep.draft.parts[0].slug == "front-matter"
    assert deep.draft.coverage() == 8

    shallow = pdfops.inspect(data, "t.pdf", depth=1)
    assert [p.title for p in shallow.draft.parts] == ["Part One", "Part Two"]
    assert shallow.draft.coverage() == 8


# -- tier 2: the document's own printed contents ---------------------------
def test_a_contents_page_drives_the_split_when_there_are_no_bookmarks():
    # Physical page 1 is the contents; the body's printed labels start at 1 on physical page 2,
    # so the verified offset must come out as +1.
    pages = [
        "CONTENTS\n\nConditions of Tender ......... 1\n"
        "Scope of Works ......... 3\nPricing Schedule ......... 5\n",
        "Conditions of Tender\nthe bidding rules follow",
        "more conditions",
        "Scope of Works\nthe works are described",
        "more scope",
        "Pricing Schedule\nrates follow",
    ]
    report = pdfops.inspect(_pdf(pages), "no-bookmarks.pdf")

    assert report.draft.tier == TIER_TOC
    assert "+1" in report.draft.tier_reason  # the offset was verified, not assumed
    starts = {p.title: p.start for p in report.draft.parts}
    assert starts["Conditions of Tender"] == 2   # printed page 1 == physical page 2
    assert starts["Scope of Works"] == 4
    assert starts["Pricing Schedule"] == 6
    assert report.draft.coverage() == 6


def test_a_contents_page_whose_titles_are_nowhere_is_not_trusted():
    # Entries that do not appear anywhere in the body: no offset verifies, so tier 2 is refused
    # rather than producing a confident-looking split of the wrong pages.
    pages = ["CONTENTS\n\nAlpha ......... 1\nBeta ......... 2\nGamma ......... 3\n"] + [
        "unrelated body text here" for _ in range(5)
    ]
    report = pdfops.inspect(_pdf(pages), "lying-contents.pdf")
    assert report.draft.tier != TIER_TOC


# -- tier 4: nothing to go on ----------------------------------------------
def test_a_featureless_document_degrades_to_one_part_and_is_still_a_success():
    data = _pdf(["the same flat paragraph of prose" for _ in range(6)])
    report = pdfops.inspect(data, "flat.pdf")

    assert report.draft.tier == TIER_WHOLE
    assert len(report.draft.parts) == 1
    assert (report.draft.parts[0].start, report.draft.parts[0].end) == (1, 6)
    assert "by hand" in report.draft.tier_reason  # says what the human should do about it


def test_tier_is_one_of_the_four_rungs_for_any_input():
    for data in (_pdf(["a"]), _scanned_pdf(3), _pdf(["x", "y"], [(1, "Only", 1)])):
        report = pdfops.inspect(data, "x.pdf")
        assert report.draft.tier in {TIER_BOOKMARKS, TIER_TOC, TIER_HEURISTIC, TIER_WHOLE}
        assert report.draft.parts  # never zero parts


# -- scanned detection ------------------------------------------------------
def test_pages_with_no_text_layer_are_flagged_not_dropped():
    report = pdfops.inspect(_scanned_pdf(3), "scan.pdf")
    assert report.scanned_pages == [1, 2, 3]
    assert report.total_chars == 0
    assert report.draft.parts[0].scanned is True
    assert report.draft.parts[0].page_count() == 3  # catalogued in full, not skipped


def test_a_part_is_only_scanned_when_all_of_its_pages_are():
    doc = fitz.open()
    doc.new_page().insert_text((72, 100), "readable text on page one")
    page = doc.new_page()
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 200, 200))
    pix.clear_with(255)
    page.insert_image(page.rect, pixmap=pix)
    data = doc.tobytes()
    doc.close()

    report = pdfops.inspect(data, "mixed.pdf")
    assert report.scanned_pages == [2]
    assert report.draft.parts[0].scanned is False  # one readable page makes the part readable


def test_scanned_is_re_stamped_onto_new_boundaries_not_carried_by_the_proposal():
    # Regression: whether a part has a text layer is MEASURED. When the planner (or a human at
    # the gate) replaces the parts, the flag must be recomputed from the measured page list —
    # otherwise a refinement silently clears it and a scan is treated as readable text.
    proposed = [
        PartSpec(n=1, start=1, end=4),     # entirely inside the scanned range
        PartSpec(n=2, start=5, end=9),     # mixed
        PartSpec(n=3, start=10, end=12),   # entirely readable
    ]
    pdfops.mark_scanned(proposed, scanned_pages=[1, 2, 3, 4, 5])

    assert [p.scanned for p in proposed] == [True, False, False]


def test_mark_scanned_with_nothing_scanned_clears_every_flag():
    parts = [PartSpec(n=1, start=1, end=3, scanned=True)]
    pdfops.mark_scanned(parts, scanned_pages=[])
    assert parts[0].scanned is False


# -- validation: the deterministic veto over the model's proposal -----------
def _manifest(parts, pages=10, source="t.pdf"):
    return SplitManifest(source_doc=source, pages=pages, parts=parts)


def test_validate_accepts_a_clean_cover():
    m = _manifest([PartSpec(n=1, start=1, end=4), PartSpec(n=2, start=5, end=10)])
    assert pdfops.validate(m, 10) == ([], [])


def test_validate_rejects_a_range_past_the_end_of_the_document():
    m = _manifest([PartSpec(n=1, title="Overrun", start=1, end=99)])
    errors, _ = pdfops.validate(m, 10)
    assert errors and "outside" in errors[0]


def test_validate_rejects_an_inverted_range():
    m = _manifest([PartSpec(n=1, title="Backwards", start=8, end=3)])
    errors, _ = pdfops.validate(m, 10)
    assert errors and "before it starts" in errors[0]


def test_validate_rejects_an_empty_manifest():
    errors, _ = pdfops.validate(_manifest([]), 10)
    assert errors


def test_gaps_and_overlaps_are_warnings_not_errors():
    # A gap is recoverable and the human should see it; it must not block the cut.
    gap = _manifest([PartSpec(n=1, start=1, end=3), PartSpec(n=2, start=7, end=10)])
    errors, warnings = pdfops.validate(gap, 10)
    assert errors == [] and any("belong to no part" in w for w in warnings)

    overlap = _manifest([PartSpec(n=1, start=1, end=6), PartSpec(n=2, start=4, end=10)])
    errors, warnings = pdfops.validate(overlap, 10)
    assert errors == [] and any("overlap" in w for w in warnings)


def test_parts_from_another_uploaded_file_are_not_judged_against_the_binder():
    # A loose annex uploaded beside the binder has its own page numbering.
    m = _manifest([
        PartSpec(n=1, start=1, end=10, source_doc="t.pdf"),
        PartSpec(n=2, start=1, end=40, source_doc="annex.pdf"),
    ])
    assert pdfops.validate(m, 10) == ([], [])


# -- slicing ----------------------------------------------------------------
def test_slice_extracts_exactly_the_requested_pages():
    data = _pdf([f"page number {i}" for i in range(1, 11)])
    out = pdfops.slice_pdf(data, 3, 5)
    with fitz.open(stream=out, filetype="pdf") as doc:
        assert len(doc) == 3
        assert "page number 3" in doc[0].get_text()
        assert "page number 5" in doc[2].get_text()


def test_slicing_every_part_reproduces_the_whole_document():
    data = _pdf([f"p{i}" for i in range(12)])
    report = pdfops.inspect(data, "t.pdf")
    total = 0
    for part in report.draft.parts:
        with fitz.open(stream=pdfops.slice_pdf(data, part.start, part.end), filetype="pdf") as d:
            total += len(d)
    assert total == 12


def test_an_impossible_slice_returns_the_document_rather_than_losing_it():
    data = _pdf(["only page"])
    assert pdfops.slice_pdf(data, 9, 3) == data     # inverted
    assert pdfops.slice_pdf(data, 50, 60) == data   # past the end
    assert pdfops.slice_pdf(b"", 1, 2) == b""


def test_page_text_numbers_pages_from_the_source_not_the_slice():
    # A citation read out of part 3 must still point at the page of the original binder.
    data = _pdf([f"content of page {i}" for i in range(1, 9)])
    text = pdfops.page_text(data, 5, 6)
    assert "[page 5]" in text and "[page 6]" in text
    assert "[page 1]" not in text


# -- slugs and tags ---------------------------------------------------------
def test_slugs_are_short_safe_and_never_empty():
    assert pdfops.slugify("Conditions of Tender!!") == "conditions-of-tender"
    assert pdfops.slugify("") == "part"
    assert pdfops.slugify("!!!") == "part"
    assert len(pdfops.slugify("x" * 200)) <= pdfops.SLUG_MAX_LEN


def test_abbreviations_skip_stop_words():
    assert pdfops.abbreviate("Conditions of Tender") == "CT"
    assert pdfops.abbreviate("Memorandum of Agreement") == "MA"
    assert pdfops.abbreviate("") == "PT"


def test_part_id_is_stable_and_sorts_in_document_order():
    parts = [PartSpec(n=n, abbr=a) for n, a in ((1, "INV"), (2, "CT"), (10, "GCC"))]
    ids = [p.part_id for p in parts]
    assert ids == ["01-inv", "02-ct", "10-gcc"]
    assert sorted(ids) == ids


def test_an_encrypted_pdf_is_refused_with_a_useful_message():
    doc = fitz.open()
    doc.new_page().insert_text((72, 100), "secret")
    data = doc.tobytes(encryption=fitz.PDF_ENCRYPT_AES_256, owner_pw="o", user_pw="u")
    doc.close()
    with pytest.raises(ValueError, match="encrypted"):
        pdfops.inspect(data, "locked.pdf")


def test_an_empty_upload_is_refused():
    with pytest.raises(ValueError, match="Empty"):
        pdfops.inspect(b"", "nothing.pdf")
