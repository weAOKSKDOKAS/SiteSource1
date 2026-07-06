"""Table-aware SoR OCR (Commit 4). The column-recovery algorithm is exercised without tesseract
by stubbing the word-box reader (``_words``); only the real rendered-table round-trip is guarded
on a tesseract install."""

import pytest

import pipeline.ocr_table as ocr_table
from pipeline.ocr_table import _assign, _column_bounds, rows_text


def _tesseract_available() -> bool:
    try:
        import pytesseract

        pytesseract.get_tesseract_version()
        return True
    except Exception:  # noqa: BLE001
        return False


requires_tesseract = pytest.mark.skipif(not _tesseract_available(), reason="tesseract/pytesseract not installed")


def _word(text, cx, *, conf=90.0, row=1):
    return {"text": text, "conf": conf, "cx": float(cx), "left": cx - 10, "top": 100 + row * 20, "row_key": (1, 1, row)}


def test_column_bounds_finds_four_boundaries_for_five_columns():
    bounds = _column_bounds([50, 200, 400, 600, 750])
    assert bounds is not None and len(bounds) == 4          # 5 clusters -> 4 separators
    assert bounds[0] < 200 < bounds[1] < 400 < bounds[2] < 600 < bounds[3]


def test_column_bounds_is_none_when_columns_cannot_be_recovered():
    assert _column_bounds([10, 20]) is None                 # < 5 distinct positions -> fail -> vision


def test_assign_places_words_into_columns_by_x():
    bounds = [125, 325, 520, 675]
    cells = _assign([_word("G4", 50), _word("No.", 600), _word("805.00", 750)], bounds)
    assert cells[0] == "G4" and cells[3] == "No." and cells[4] == "805.00"


def test_rows_text_structures_a_ruled_sor_row(monkeypatch):
    # The whole row-structuring pipeline, tesseract-free: a 5-column row with a stacked Clause Ref
    # cell recovers Item / Desc / ClauseRef / Unit / Rate into the explicit structured line.
    row = [
        _word("G4", 50), _word("Extra", 200), _word("over", 250),
        _word("GS", 400), _word("7.72", 440),  # a two-token Clause Ref cell
        _word("No.", 600), _word("805.00", 750),
    ]
    monkeypatch.setattr(ocr_table, "_words", lambda *a, **k: row)
    text, confident = rows_text(b"fake-png")
    assert confident is True
    assert text == "Item: G4 | Desc: Extra over | ClauseRef: GS 7.72 | Unit: No. | Rate: 805.00"


def test_rows_text_low_confidence_page_falls_back_to_vision(monkeypatch):
    low = [_word("blur", 50, conf=20.0), _word("smudge", 400, conf=18.0), _word("x", 700, conf=15.0)]
    monkeypatch.setattr(ocr_table, "_words", lambda *a, **k: low)
    text, confident = rows_text(b"fake-png", min_conf=45.0)
    assert text == "" and confident is False                # low mean confidence -> caller uses vision


def test_rows_text_empty_page_is_not_confident(monkeypatch):
    monkeypatch.setattr(ocr_table, "_words", lambda *a, **k: [])
    assert rows_text(b"blank") == ("", False)


@requires_tesseract
def test_rows_text_on_a_real_rendered_table():
    fitz = pytest.importorskip("fitz")
    doc = fitz.open()
    page = doc.new_page()
    # a crude 5-column row rendered at spaced x positions
    for x, token in [(60, "G4"), (150, "Extra over rock"), (330, "GS 7.72"), (470, "No."), (560, "805.00")]:
        page.insert_text((x, 120), token, fontsize=11)
    png = page.get_pixmap(matrix=fitz.Matrix(3, 3), alpha=False).tobytes("png")
    doc.close()
    text, confident = rows_text(png)
    assert confident and "G4" in text and "805.00" in text
