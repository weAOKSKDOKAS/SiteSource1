"""The OCR spine (Commit 1): native-or-OCR per-page text + content-addressed cache.

The native-path, cache and line-structure tests run everywhere (no tesseract needed — the native
text layer never invokes OCR, and the cache test stubs the compute worker). Only the true OCR
round-trip is guarded on a real tesseract install, so CI without it stays green.
"""

import pytest

import pipeline.ocr as ocr
from pipeline.ocr import NotAPdf, page_texts

fitz = pytest.importorskip("fitz")  # PyMuPDF — used only to build test PDFs


def _tesseract_available() -> bool:
    try:
        import pytesseract

        pytesseract.get_tesseract_version()
        return True
    except Exception:  # noqa: BLE001
        return False


requires_tesseract = pytest.mark.skipif(not _tesseract_available(), reason="tesseract/pytesseract not installed")


@pytest.fixture(autouse=True)
def _isolate_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("SITESOURCE_OCR_CACHE", str(tmp_path / "ocr_cache"))


def _text_pdf(lines: list[str]) -> bytes:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 100), "\n".join(lines), fontsize=14)
    data = doc.tobytes()
    doc.close()
    return data


def test_native_text_page_uses_native_text_and_never_calls_tesseract(monkeypatch):
    calls = {"n": 0}

    def _count(*a, **k):
        calls["n"] += 1
        return "OCR-RAN"

    monkeypatch.setattr(ocr, "_ocr_image_png", _count)
    pages = page_texts(_text_pdf(["Total Due: HK$1,250,000 for the works"]))
    assert len(pages) == 1 and "1,250,000" in pages[0] and calls["n"] == 0  # native text, OCR never called


def test_scanned_page_degrades_to_empty_when_ocr_is_unavailable(monkeypatch):
    # A page with no text layer, on a machine without tesseract, yields "" (no crash) — the
    # pre-OCR behaviour, so the whole suite / DEMO run unchanged where tesseract is absent.
    def _unavailable(*a, **k):
        raise ImportError("no pytesseract")

    monkeypatch.setattr(ocr, "_ocr_image_png", _unavailable)
    blank = fitz.open()
    blank.new_page()  # a page with no inserted text
    data = blank.tobytes()
    blank.close()
    assert page_texts(data) == [""]  # degraded, not raised


def test_cache_computes_once_then_reads(monkeypatch):
    calls = {"n": 0}

    def _fake_compute(data, min_native_chars, dpi, lang, psm):
        calls["n"] += 1
        return ["page one", "page two"]

    monkeypatch.setattr(ocr, "_compute_page_texts", _fake_compute)
    first = page_texts(b"some tender bytes")
    second = page_texts(b"some tender bytes")     # same bytes -> served from the cache
    assert first == second == ["page one", "page two"]
    assert calls["n"] == 1                          # computed once, cached thereafter


def _blank_pdf() -> bytes:
    doc = fitz.open()
    doc.new_page()  # a page with no text layer -> OCR is attempted
    data = doc.tobytes()
    doc.close()
    return data


def test_an_empty_ocr_result_is_not_cached_but_a_real_one_is(tmp_path, monkeypatch):
    # A transient engine/config failure returns empty text; that must NOT be cached, or every
    # retry would fail instantly. Once the engine works, the real result caches.
    data = _blank_pdf()
    monkeypatch.setattr(ocr, "_ocr_or_empty", lambda *a, **k: "")   # engine "missing" -> empty
    assert page_texts(data) == [""]
    assert not list(tmp_path.rglob("*.json"))                       # nothing persisted

    monkeypatch.setattr(ocr, "_ocr_or_empty", lambda *a, **k: "7.34A Rotary drilling in rock")
    assert page_texts(data) == ["7.34A Rotary drilling in rock"]    # recomputed, not the poisoned empty
    assert list(tmp_path.rglob("*.json"))                          # now it caches


def test_line_structure_is_preserved_for_clause_markers():
    # doc_index matches clause / PB markers at line start, so line breaks must survive.
    pages = page_texts(_text_pdf(["7.34A Rotary drilling in rock", "7.37A Standard penetration test"]))
    lines = pages[0].splitlines()
    assert any(ln.startswith("7.34A") for ln in lines) and any(ln.startswith("7.37A") for ln in lines)


def test_not_a_pdf_raises():
    with pytest.raises(NotAPdf):
        page_texts(b"this is not a pdf")


# -- tesseract binary resolution (config over PATH) ------------------------
def test_find_tesseract_prefers_the_configured_path_when_it_exists(tmp_path, monkeypatch):
    exe = tmp_path / "tesseract"
    exe.write_text("#!/bin/sh\n")
    monkeypatch.setenv("TESSERACT_CMD", str(exe))
    assert ocr._find_tesseract() == str(exe)


def test_find_tesseract_falls_through_a_missing_configured_path(monkeypatch):
    monkeypatch.setenv("TESSERACT_CMD", "/no/such/tesseract")
    monkeypatch.setattr(ocr, "_platform_candidates", lambda: ["/no/such/a", "/no/such/b"])
    assert ocr._find_tesseract() is None  # nothing exists -> leave pytesseract's PATH default


def test_find_tesseract_uses_the_first_existing_platform_default(tmp_path, monkeypatch):
    monkeypatch.delenv("TESSERACT_CMD", raising=False)
    good = tmp_path / "tess"
    good.write_text("x")
    monkeypatch.setattr(ocr, "_platform_candidates", lambda: ["/no/such/one", str(good)])
    assert ocr._find_tesseract() == str(good)


def test_resolve_sets_tesseract_cmd_from_config(monkeypatch):
    import types

    monkeypatch.setattr(ocr, "_TESSERACT_RESOLVED", False)
    monkeypatch.setattr(ocr, "_find_tesseract", lambda: "/opt/tess/tesseract")
    fake = types.SimpleNamespace(pytesseract=types.SimpleNamespace(tesseract_cmd="tesseract"))
    ocr._resolve_tesseract_cmd(fake)
    assert fake.pytesseract.tesseract_cmd == "/opt/tess/tesseract"  # config over PATH


# -- fail loud when the engine is missing (vs an empty document) -----------
def test_engine_unavailable_error_names_the_fix():
    import types

    fake = types.SimpleNamespace(pytesseract=types.SimpleNamespace(tesseract_cmd="/bad/tesseract"))
    exc = ocr._engine_unavailable(fake)
    assert isinstance(exc, ocr.OcrEngineUnavailable)
    assert "TESSERACT_CMD" in str(exc) and "tesseract" in str(exc).lower()


def test_engine_unavailable_is_raised_never_swallowed_to_empty(monkeypatch):
    def _raise(*a, **k):
        raise ocr.OcrEngineUnavailable("no engine")

    monkeypatch.setattr(ocr, "_ocr_image_png", _raise)
    with pytest.raises(ocr.OcrEngineUnavailable):
        page_texts(_blank_pdf())  # a scanned page -> OCR attempted -> loud, not ""


def test_healthy_but_blank_page_degrades_to_empty_without_raising(monkeypatch):
    monkeypatch.setattr(ocr, "_ocr_image_png", lambda *a, **k: "")  # engine ran, page blank
    assert page_texts(_blank_pdf()) == [""]  # graceful "", no raise


@requires_tesseract
def test_scanned_page_is_read_by_ocr():
    # A page whose text is flattened into an image (no text layer) is recovered by OCR.
    src = fitz.open()
    sp = src.new_page()
    sp.insert_text((72, 120), "ROTARY DRILLING", fontsize=32)
    png = sp.get_pixmap(matrix=fitz.Matrix(3, 3), alpha=False).tobytes("png")
    src.close()
    out = fitz.open()
    op = out.new_page()
    op.insert_image(op.rect, stream=png)
    data = out.tobytes()
    out.close()

    pages = page_texts(data)
    assert len(pages) == 1 and "ROTARY" in pages[0].upper()  # OCR'd back to text


def test_ocr_disabled_is_native_only_and_never_ocrs(monkeypatch):
    monkeypatch.setenv("OCR_ENABLED", "false")
    calls = {"n": 0}

    def _count(*a, **k):
        calls["n"] += 1
        return "OCR-RAN"

    monkeypatch.setattr(ocr, "_ocr_image_png", _count)
    blank = fitz.open()
    blank.new_page()  # a scanned/blank page with no text layer
    data = blank.tobytes()
    blank.close()
    assert page_texts(data) == [""] and calls["n"] == 0  # OCR off -> native-only, never OCR'd
