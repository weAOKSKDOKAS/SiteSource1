"""Table-aware OCR for scanned Schedule-of-Rates pages (Commit 4).

A SoR page is a ruled 5-column table — Item · Description · Clause Ref · Unit · Schedule Rate.
Naive single-column OCR (``--psm 6``) linearises it and loses column association (observed: the
item code and clause refs stay on-row but the Unit column is dropped). Since the Clause Ref column
is where ``clause_refs`` come from, and Unit/Rate feed the priced sheet and leveling, column
integrity matters for the SoR specifically.

This module recovers columns from the OCR word boxes (``pytesseract.image_to_data``): it groups
words into rows using tesseract's own block/paragraph/line numbering, clusters word x-centres into
up to five columns by the largest horizontal gaps, assigns each word to a column by x, and emits an
explicit column-structured line per row — ``Item: G4 | Desc: … | ClauseRef: GS 7.72; PS 7.74(4)S |
Unit: No. | Rate: 805.00`` — that the existing ingest prompt reads reliably (it already asks for
``clause_refs`` from the Clause Ref column; the structure just makes it dependable). A page with low
OCR confidence or unrecoverable columns is reported as not-confident so the caller renders THAT page
for the vision fallback (per page, not the whole SoR).

``pytesseract`` and Pillow are imported lazily; this produces no decision value — only structure.
"""

from __future__ import annotations

from typing import Optional

# The SoR column order, left to right. Words are labelled by their recovered column position.
COLUMNS = ["Item", "Desc", "ClauseRef", "Unit", "Rate"]


def _words(png_bytes: bytes, lang: str, psm: int) -> list[dict]:
    """Per-word boxes with confidence via ``image_to_data``. pytesseract / Pillow lazy-imported."""
    import io

    import pytesseract
    from PIL import Image

    from pipeline import ocr  # reuse the config-over-PATH resolution + engine-error handling

    ocr._resolve_tesseract_cmd(pytesseract)
    try:
        with Image.open(io.BytesIO(png_bytes)) as image:
            data = pytesseract.image_to_data(
                image, lang=lang, config=f"--psm {psm}", output_type=pytesseract.Output.DICT
            )
    except pytesseract.TesseractNotFoundError as exc:  # engine binary missing -> loud (not vision)
        raise ocr._engine_unavailable(pytesseract) from exc
    words: list[dict] = []
    for i in range(len(data["text"])):
        text = (data["text"][i] or "").strip()
        try:
            conf = float(data["conf"][i])
        except (TypeError, ValueError):
            conf = -1.0
        if not text or conf < 0:
            continue
        left, top, width = int(data["left"][i]), int(data["top"][i]), int(data["width"][i])
        words.append({
            "text": text, "conf": conf, "cx": left + width / 2.0, "left": left, "top": top,
            "row_key": (int(data["block_num"][i]), int(data["par_num"][i]), int(data["line_num"][i])),
        })
    return words


def _column_bounds(cxs: list[float], n_cols: int = len(COLUMNS)) -> Optional[list[float]]:
    """The ``n_cols - 1`` x-boundaries separating columns, found from the largest gaps between the
    sorted distinct word x-centres. ``None`` when fewer than ``n_cols`` distinct positions exist
    (column recovery failed -> caller uses the vision fallback)."""
    xs = sorted({round(c) for c in cxs})
    if len(xs) < n_cols:
        return None
    gaps = sorted(((xs[i + 1] - xs[i], i) for i in range(len(xs) - 1)), reverse=True)[: n_cols - 1]
    cut_after = sorted(i for _, i in gaps)
    return [(xs[i] + xs[i + 1]) / 2.0 for i in cut_after]


def _group_rows(words: list[dict]) -> list[list[dict]]:
    """Words grouped into rows by tesseract's block/paragraph/line numbering (robust for a ruled
    table), each row ordered left to right; rows ordered top to bottom."""
    rows: dict[tuple, list[dict]] = {}
    for w in words:
        rows.setdefault(w["row_key"], []).append(w)
    ordered = sorted(rows.values(), key=lambda ws: min(x["top"] for x in ws))
    return [sorted(ws, key=lambda x: x["left"]) for ws in ordered]


def _assign(row: list[dict], bounds: list[float]) -> dict[int, str]:
    """Assign each word in a row to a column index (0..len(bounds)) by its x-centre."""
    cells: dict[int, list[str]] = {}
    for w in row:
        col = 0
        for b in bounds:
            if w["cx"] > b:
                col += 1
            else:
                break
        cells.setdefault(col, []).append(w["text"])
    return {i: " ".join(v) for i, v in cells.items()}


def rows_text(png_bytes: bytes, *, lang: str = "eng", psm: int = 6, min_conf: float = 45.0) -> tuple[str, bool]:
    """Return ``(column-structured text, confident)`` for a rendered SoR page. ``confident`` is
    False — with empty text — when the page's mean OCR confidence is below ``min_conf`` or columns
    could not be recovered, so the caller renders that page for the vision fallback."""
    words = _words(png_bytes, lang, psm)
    if not words:
        return "", False
    mean_conf = sum(w["conf"] for w in words) / len(words)
    bounds = _column_bounds([w["cx"] for w in words])
    if mean_conf < min_conf or bounds is None:
        return "", False  # low confidence / no columns -> vision fallback for this page
    lines: list[str] = []
    for row in _group_rows(words):
        cells = _assign(row, bounds)
        parts = [f"{COLUMNS[i]}: {cells[i].strip()}" for i in range(len(COLUMNS)) if cells.get(i, "").strip()]
        if parts:
            lines.append(" | ".join(parts))
    return "\n".join(lines), bool(lines)
