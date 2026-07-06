"""Native-or-OCR per-page text for scanned tender PDFs (Layer-1 input; deterministic).

Real HK ground-investigation tender PDFs (Schedule of Rates, Particular Specification, Method of
Measurement) are often SCANNED — no text layer, so ``page.get_text`` returns nothing and the
clause-slicing assembler finds no markers. This module returns per-page text: the native text
layer where a page has one (cheap, exact, identical to what the pipeline already trusts), and
local OCR (tesseract, via ``pytesseract``) only for pages that don't.

The result feeds Layer-1 regex (``doc_index`` / ``doc_refs``) and the Layer-2 extraction prompt,
which still only COPIES item fields — OCR produces no decision value.

``fitz`` (PyMuPDF) and ``pytesseract`` are BOTH imported lazily, inside the functions, so
importing this module costs nothing and a machine without either (DEMO_MODE, the test suite)
imports it fine. OCR is local — no network — so it never breaks the DEMO offline rule (and OCR
must not run on the DEMO path anyway; DEMO returns fixtures and never reaches here).

Content-addressed cache: keyed on ``sha256(bytes) + dpi + lang + psm``, so the two consumers
(``doc_index`` and ``documents``) and every dispatch re-run share results and never re-OCR the
same bytes. Keyed on bytes, so nothing threads ``tender_id`` anywhere.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Optional


class NotAPdf(ValueError):
    """The input bytes are not a readable PDF — callers decide how to degrade."""


# -- content-addressed cache ------------------------------------------------
def _cache_root() -> Path:
    """Where per-key OCR results live. ``SITESOURCE_OCR_CACHE`` wins; otherwise a subdir under
    the same root ``Workspace`` uses (``SITESOURCE_WORKDIR`` or ``backend/fixtures/out/workspace``,
    which is gitignored)."""
    env = os.getenv("SITESOURCE_OCR_CACHE", "").strip()
    if env:
        return Path(env)
    workdir = os.getenv("SITESOURCE_WORKDIR", "").strip()
    root = Path(workdir) if workdir else (Path(__file__).resolve().parent.parent / "fixtures" / "out" / "workspace")
    return root / "ocr_cache"


def _cache_key(data: bytes, dpi: int, lang: str, psm: int) -> str:
    return f"{hashlib.sha256(data).hexdigest()}-{dpi}-{lang}-psm{psm}"


def _cache_read(key: str) -> Optional[list[str]]:
    path = _cache_root() / f"{key}.json"
    if not path.is_file():
        return None
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, ValueError):
        return None  # corrupt / unreadable cache -> recompute
    pages = obj.get("pages") if isinstance(obj, dict) else None
    if isinstance(pages, list) and all(isinstance(p, str) for p in pages):
        return pages
    return None


def _cache_write(key: str, pages: list[str]) -> None:
    try:
        root = _cache_root()
        root.mkdir(parents=True, exist_ok=True)
        (root / f"{key}.json").write_text(json.dumps({"pages": pages}), encoding="utf-8")
    except OSError:
        pass  # a cache write must never fail the pipeline


# -- OCR worker (lazy tesseract) --------------------------------------------
def _ocr_image_png(png_bytes: bytes, *, lang: str, psm: int) -> str:
    """OCR a single rendered page (PNG bytes) to text via tesseract. ``pytesseract`` (and its
    Pillow dependency) are imported lazily here, never at module top."""
    import io

    import pytesseract
    from PIL import Image

    with Image.open(io.BytesIO(png_bytes)) as image:
        return pytesseract.image_to_string(image, lang=lang, config=f"--psm {psm}")


def _ocr_or_empty(png_bytes: bytes, *, lang: str, psm: int) -> str:
    """OCR a page, degrading to ``""`` when OCR is unavailable or fails (no pytesseract / no
    tesseract binary / a bad page). An unreadable scanned page then simply contributes no text —
    exactly the pre-OCR behaviour — so a machine without tesseract runs DEMO and the whole suite
    unchanged, and a scanned doc falls back to whole-file rather than crashing ingest."""
    try:
        return _ocr_image_png(png_bytes, lang=lang, psm=psm)
    except Exception:  # noqa: BLE001 — OCR unavailable/failed for this page -> no text
        return ""


def _render_png(page, dpi: int) -> bytes:
    import fitz  # PyMuPDF — lazy

    zoom = dpi / 72.0
    return page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False).tobytes("png")


def _compute_page_texts(data: bytes, min_native_chars: int, dpi: int, lang: str, psm: int) -> list[str]:
    """Per-page native-or-OCR text, uncached. Native text is used verbatim when a page has a
    usable one; otherwise the page is rasterised and OCR'd. Line structure is preserved so the
    line-anchored clause / PB markers in ``doc_index`` survive."""
    import fitz  # PyMuPDF — lazy

    try:
        doc = fitz.open(stream=data, filetype="pdf")
    except Exception as exc:  # noqa: BLE001 — any open failure means "not a readable PDF"
        raise NotAPdf(str(exc)) from exc
    try:
        pages: list[str] = []
        for page in doc:
            native = page.get_text("text", sort=True)
            if len(native.strip()) >= min_native_chars:
                pages.append(native)  # cheap, exact — the text layer the pipeline already trusts
            else:
                pages.append(_ocr_or_empty(_render_png(page, dpi), lang=lang, psm=psm))
        return pages
    finally:
        doc.close()


def page_texts(
    data: bytes, *, min_native_chars: int = 20, dpi: int = 300, lang: str = "eng", psm: int = 6,
) -> list[str]:
    """Per-page text for a PDF, one entry per page, in page order: the native text layer where a
    page has one (>= ``min_native_chars`` stripped), else local tesseract OCR of the rasterised
    page. Content-addressed cache on the bytes + params, so the same document is never OCR'd
    twice. Raises :class:`NotAPdf` when the input is not a readable PDF."""
    key = _cache_key(data, dpi, lang, psm)
    cached = _cache_read(key)
    if cached is not None:
        return cached
    pages = _compute_page_texts(data, min_native_chars, dpi, lang, psm)
    _cache_write(key, pages)
    return pages
