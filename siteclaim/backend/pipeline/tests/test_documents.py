"""Spec for pipeline.documents.to_images (PDF→PNG, image normalise, bad type).

Skips when PyMuPDF is not installed — to_images imports fitz lazily, so the rest of
the suite (and DEMO_MODE) never needs the dependency.
"""

import base64

import pytest

fitz = pytest.importorskip("fitz")  # PyMuPDF

from pipeline.documents import (  # noqa: E402
    IMAGE_MAX_PAGES,
    extract_document,
    to_images,
)

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _tesseract_available() -> bool:
    try:
        import pytesseract

        pytesseract.get_tesseract_version()
        return True
    except Exception:  # noqa: BLE001
        return False


requires_tesseract = pytest.mark.skipif(not _tesseract_available(), reason="tesseract/pytesseract not installed")


@pytest.fixture(autouse=True)
def _isolate_ocr_cache(tmp_path, monkeypatch):
    # extract_document now reads pipeline.ocr, which caches on disk — keep tests off the real root.
    monkeypatch.setenv("SITESOURCE_OCR_CACHE", str(tmp_path / "ocr_cache"))


def _make_pdf(pages: int = 1) -> bytes:
    doc = fitz.open()
    for _ in range(pages):
        page = doc.new_page()
        page.insert_text((72, 72), "Total Due: HK$1,250,000")
    data = doc.tobytes()
    doc.close()
    return data


def _make_scanned_pdf() -> bytes:
    """A page with only an image and no text layer (a scanned page)."""
    doc = fitz.open()
    page = doc.new_page()
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 200, 200))
    pix.clear_with(255)  # blank white image, no text
    page.insert_image(page.rect, pixmap=pix)
    data = doc.tobytes()
    doc.close()
    return data


def _make_png() -> bytes:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "INVOICE")
    data = page.get_pixmap().tobytes("png")
    doc.close()
    return data


def test_pdf_rasterises_each_page_to_png():
    imgs = to_images(_make_pdf(2), "application/pdf")
    assert len(imgs) == 2
    assert base64.b64decode(imgs[0])[:8] == _PNG_MAGIC


def test_pdf_pages_are_capped():
    imgs = to_images(_make_pdf(8), "application/pdf", max_pages=5)
    assert len(imgs) == 5


def test_image_is_normalised_to_png():
    imgs = to_images(_make_png(), "image/png")
    assert len(imgs) == 1
    assert base64.b64decode(imgs[0])[:8] == _PNG_MAGIC


def test_content_type_with_parameters_is_handled():
    imgs = to_images(_make_pdf(1), "application/pdf; charset=binary")
    assert len(imgs) == 1


def test_unsupported_type_raises():
    with pytest.raises(ValueError):
        to_images(b"hello", "text/plain")


def test_empty_file_raises():
    with pytest.raises(ValueError):
        to_images(b"", "application/pdf")


# -- text-first extraction (extract_document) ------------------------------
def test_extract_document_uses_the_text_layer_and_renders_no_image():
    text, images = extract_document(_make_pdf(2), "application/pdf")
    assert "Total Due" in text and "1,250,000" in text  # literal rows, not a picture
    assert images == []                                  # a text layer -> no page rendered


def test_extract_document_falls_back_to_image_for_a_scanned_page():
    text, images = extract_document(_make_scanned_pdf(), "application/pdf")
    assert text == ""                                    # no usable text layer
    assert len(images) == 1
    assert base64.b64decode(images[0])[:8] == _PNG_MAGIC  # the scanned page went to vision


def test_extract_document_mixes_text_and_image_pages():
    # one text page + one scanned page in the same document
    doc = fitz.open()
    doc.new_page().insert_text((72, 72), "M1 rotary drilling PS 1.13.1A no 50")
    scan = doc.new_page()
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 200, 200))
    pix.clear_with(255)
    scan.insert_image(scan.rect, pixmap=pix)
    data = doc.tobytes()
    doc.close()

    text, images = extract_document(data, "application/pdf")
    assert "rotary drilling" in text and len(images) == 1  # text page as text, scan as image


def test_extract_document_image_upload_is_vision_only():
    text, images = extract_document(_make_png(), "image/png")
    assert text == "" and len(images) == 1


def test_extract_document_empty_raises():
    with pytest.raises(ValueError):
        extract_document(b"", "application/pdf")


def test_image_cap_limits_rendered_scanned_pages():
    # many scanned pages -> images are capped (vision is expensive)
    doc = fitz.open()
    for _ in range(IMAGE_MAX_PAGES + 4):
        page = doc.new_page()
        pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 100, 100))
        pix.clear_with(255)  # blank image page, no text
        page.insert_image(page.rect, pixmap=pix)
    data = doc.tobytes()
    doc.close()

    text, images = extract_document(data, "application/pdf")
    assert text == "" and len(images) == IMAGE_MAX_PAGES  # capped, not all rendered


def test_text_cap_is_generous_well_past_the_old_five_page_limit():
    doc = fitz.open()
    for i in range(20):
        doc.new_page().insert_text((72, 72), f"Page {i}: item {i} rotary drilling in soil and rock")
    data = doc.tobytes()
    doc.close()

    text, images = extract_document(data, "application/pdf")
    assert images == []
    assert text.count("[page ") == 20  # all 20 text pages extracted (old cap was 5)


@requires_tesseract
def test_scanned_text_pdf_past_the_image_cap_is_read_as_text_not_dropped():
    # A scanned SoR longer than the 8-page vision cap: OCR reads every page to text, so pages
    # past page 8 are NOT silently dropped, and vision is not used for text pages.
    src = fitz.open()
    for i in range(IMAGE_MAX_PAGES + 4):  # 12 pages, each rendered then flattened to an image
        src.new_page().insert_text((72, 100), f"H{i} rotary drilling in rock, section item {i}", fontsize=16)
    flat = fitz.open()
    for i in range(src.page_count):
        png = src[i].get_pixmap(matrix=fitz.Matrix(3, 3), alpha=False).tobytes("png")
        op = flat.new_page(width=src[i].rect.width, height=src[i].rect.height)
        op.insert_image(op.rect, stream=png)
    data = flat.tobytes()
    src.close()
    flat.close()

    text, images = extract_document(data, "application/pdf")
    assert f"[page {IMAGE_MAX_PAGES + 3}]" in text   # a page past the 8-page image cap is present as text
    assert images == []                              # scanned text pages -> OCR text, not vision


def test_extract_document_propagates_engine_unavailable_not_no_content(monkeypatch):
    # A configured-but-missing OCR engine surfaces as its own error, NOT "PDF has no extractable
    # content" — so the operator is pointed at configuration, not at the document.
    import pipeline.ocr as ocr

    def _raise(*a, **k):
        raise ocr.OcrEngineUnavailable("OCR engine (tesseract) not found — set TESSERACT_CMD")

    monkeypatch.setattr(ocr, "_ocr_image_png", _raise)
    doc = fitz.open()
    doc.new_page()  # a scanned page with no text layer -> OCR attempted
    data = doc.tobytes()
    doc.close()
    with pytest.raises(ocr.OcrEngineUnavailable):
        extract_document(data, "application/pdf")
