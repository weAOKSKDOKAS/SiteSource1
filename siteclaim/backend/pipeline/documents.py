"""Turn an uploaded document into what a model can read — text first, images only when needed.

Two entry points, both with ``fitz`` (PyMuPDF) imported **lazily** so importing this
module costs nothing and DEMO_MODE never needs the dependency installed:

* ``extract_document(file_bytes, content_type) -> (text, images)`` — the **text-first**
  path. For a PDF it extracts each page's text layer (``get_text``, reading order) and
  only rasterises a page to PNG when that page has no usable text (a scanned page). A
  single document may mix text pages and image pages. This is far cheaper than sending
  every page as an image, and the model sees literal Schedule-of-Rates rows instead of
  summarising page pictures. A non-PDF image returns ``("", [png])``.
* ``to_images(file_bytes, content_type) -> list[base64-PNG]`` — the pure-image fallback,
  kept for genuinely scanned documents and callers that want vision only.

A scanned TEXT page is read cheaply by local OCR (``pipeline.ocr``) and joins the text stream
for DeepSeek; only a page that is a genuine image after OCR (a drawing) is rendered to PNG for
the vision model. ``to_images`` is unchanged (pure vision).
"""

import base64
import os
from typing import Optional

# Caps decoupled by modality: text is cheap, so allow many text pages; vision is
# expensive, so keep a low cap on rendered images (scanned pages only).
# Env-overridable, and the warnings above name the variable — an operator who meets a 400-page
# binder should be able to raise the cap without a code change, exactly as `REPLY_MAX_PAGES` and
# `DEEPSEEK_MIN_MAX_TOKENS` already work. The defaults are unchanged.
def _cap(env: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(env, "").strip() or default))
    except ValueError:
        return default


TEXT_MAX_PAGES = _cap("DOCUMENTS_TEXT_MAX_PAGES", 200)
IMAGE_MAX_PAGES = _cap("DOCUMENTS_IMAGE_MAX_PAGES", 8)
DEFAULT_DPI = 150
MIN_TEXT_CHARS = 20  # a page with fewer usable characters is treated as scanned (image)

# A PRICED RETURN is not an arbitrary document, and 8 pages is the wrong cap for it.
#
# `IMAGE_MAX_PAGES` bounds vision on documents we are sampling — a scanned page here and there
# inside a binder we are mostly reading as text. A return is different in kind: it is the whole
# answer, every page of it is a priced row, and a page nobody looked at reads downstream as a
# SCOPE GAP rather than as a page nobody looked at. The firm was sent a sliced section and replied
# with that section priced, so the length is set by the section, not by our sampling budget.
#
# 40 covers a CEDD bill section end to end. Cost is bounded by `IMAGE_PAGES_PER_CHUNK = 3`, so the
# worst case is 14 vision calls for a return — several minutes and real money, but a return arrives
# once per firm per package and the alternative is levelling a bid against rows nobody read.
#
# The cap still exists, and when it bites it is now REPORTED (`on_note`) rather than silent.
# Env-overridable, the same way `DEEPSEEK_MIN_MAX_TOKENS` is: the operator who meets a longer
# return should be able to raise it without a code change, and the warning names the variable.
def _reply_max_pages() -> int:
    try:
        return max(1, int(os.getenv("DOCUMENTS_REPLY_MAX_PAGES", "").strip() or 40))
    except ValueError:
        return 40


REPLY_MAX_PAGES = _reply_max_pages()


def _b64_png(png_bytes: bytes) -> str:
    return base64.b64encode(png_bytes).decode("ascii")


def _pdf_to_pngs(data: bytes, max_pages: int, dpi: int, on_note=None) -> list[str]:
    import fitz  # PyMuPDF — lazy

    zoom = dpi / 72.0
    matrix = fitz.Matrix(zoom, zoom)
    images: list[str] = []
    with fitz.open(stream=data, filetype="pdf") as doc:
        total = len(doc)
        for index in range(min(total, max_pages)):
            pix = doc[index].get_pixmap(matrix=matrix, alpha=False)
            images.append(_b64_png(pix.tobytes("png")))
    if not images:
        raise ValueError("PDF has no rasterisable pages.")
    if total > max_pages and on_note:
        # NEVER SILENT. `range(min(total, max_pages))` used to drop the tail with no warning, no
        # exception and no note, so a priced return past the cap came back short and the missing
        # rows read downstream as a scope gap — a fact about the document rather than about us.
        on_note(
            f"pages {max_pages + 1}-{total} of {total} were NOT read (the {max_pages}-page render "
            "cap). Anything priced on them is missing from this reply; re-send those pages, or "
            "raise DOCUMENTS_REPLY_MAX_PAGES."
        )
    return images


def _image_to_png(data: bytes) -> str:
    import fitz  # PyMuPDF — lazy

    pix = fitz.Pixmap(data)  # loads PNG/JPEG/WEBP/… into a pixmap
    if pix.alpha or pix.colorspace is None or pix.n > 4:
        pix = fitz.Pixmap(fitz.csRGB, pix)  # normalise to RGB
    return _b64_png(pix.tobytes("png"))


def to_images(
    file_bytes: bytes,
    content_type: Optional[str],
    *,
    max_pages: int = IMAGE_MAX_PAGES,
    dpi: int = DEFAULT_DPI,
    on_note=None,
) -> list[str]:
    """Rasterise an uploaded document to a list of base64-encoded PNG images.

    ``on_note`` is called with one sentence when the page cap actually drops pages. Optional and
    off by default, so every existing caller behaves exactly as it did — but a caller that is
    reading an ANSWER rather than sampling a document should pass it, because a dropped page there
    is indistinguishable downstream from a row the firm chose not to price.
    """
    if not file_bytes:
        raise ValueError("Empty file — nothing to extract.")
    ct = (content_type or "").split(";")[0].strip().lower()
    if ct == "application/pdf" or ct.endswith("/pdf"):
        return _pdf_to_pngs(file_bytes, max_pages=max_pages, dpi=dpi, on_note=on_note)
    if ct.startswith("image/"):
        return [_image_to_png(file_bytes)]
    raise ValueError(
        f"Unsupported document type {content_type!r}. Upload a PDF, JPEG, PNG, or WEBP."
    )


def _has_image_content(page) -> bool:
    """True when a page carries a raster image (a scan or a drawing). Used to tell a genuine
    image page (send to vision) from a blank one (skip) once OCR has yielded no usable text."""
    try:
        return bool(page.get_images(full=False))
    except Exception:  # noqa: BLE001 — unknown -> be safe and let vision look
        return True


def _report_caps(on_note, *, filename: str, total_pages: int, text_max_pages: int,
                 image_pages_dropped: int, image_max_pages: int) -> None:
    """Say when a cap actually bit. Both of these were silent, and both lose CONTENT.

    `TEXT_MAX_PAGES = 200` is the worse of the two: a real tender binder runs to 400+ pages, and
    the pages past the cap are never opened at all — the extractor returns what reads as the whole
    document. Downstream that is indistinguishable from a document that simply says less.

    `IMAGE_MAX_PAGES = 8` bounds vision on documents being SAMPLED, which is the right idea, but a
    drawing page past it is dropped with nothing said. The reply path already learned this lesson
    (`REPLY_MAX_PAGES`, reported through `on_note`); the same reporting belongs here.

    Off by default (`on_note=None`), so every existing caller behaves exactly as it did.
    """
    if on_note is None:
        return
    where = f" of {filename!r}" if filename else ""
    if total_pages > text_max_pages:
        on_note(
            f"{total_pages - text_max_pages} page(s){where} were NOT READ — the text cap is "
            f"{text_max_pages} (DOCUMENTS_TEXT_MAX_PAGES). Pages {text_max_pages + 1}-{total_pages} "
            f"contributed nothing, and a document read in part is not a document read.")
    if image_pages_dropped:
        on_note(
            f"{image_pages_dropped} image page(s){where} were not rendered — the vision cap is "
            f"{image_max_pages} (DOCUMENTS_IMAGE_MAX_PAGES). They contributed nothing to what was "
            f"read.")


def _pdf_text_first(
    data: bytes, text_max_pages: int, image_max_pages: int, dpi: int, min_chars: int,
    on_note=None, filename: str = "",
) -> tuple[str, list[str]]:
    import fitz  # PyMuPDF — lazy

    from pipeline import ocr  # lazy: pytesseract stays optional for import

    # Per-page text: native where present, local OCR for scanned pages (cached on the bytes).
    # A scanned SoR/PS/MM text page is now READ as text for DeepSeek instead of rendered for
    # vision — so it is no longer dropped by the 8-page image cap and costs nothing to vision.
    page_text = ocr.page_texts(data, min_native_chars=min_chars)

    zoom = dpi / 72.0
    matrix = fitz.Matrix(zoom, zoom)
    texts: list[str] = []
    images: list[str] = []
    dropped_images = 0
    total_pages = 0
    with fitz.open(stream=data, filetype="pdf") as doc:
        for index in range(min(len(doc), text_max_pages)):
            page = doc[index]
            text = (page_text[index] if index < len(page_text) else "").strip()
            if len(text) >= min_chars:
                texts.append(f"[page {index + 1}]\n{text}")  # native or OCR text (cheap, to DeepSeek)
            elif _has_image_content(page):
                if len(images) < image_max_pages:
                    pix = page.get_pixmap(matrix=matrix, alpha=False)  # a drawing -> vision
                    images.append(_b64_png(pix.tobytes("png")))
                else:
                    dropped_images += 1   # past the cap — counted, and reported below
            # else: negligible text and no raster content (blank page)
        total_pages = len(doc)
    _report_caps(on_note, filename=filename, total_pages=total_pages,
                 text_max_pages=text_max_pages, image_pages_dropped=dropped_images,
                 image_max_pages=image_max_pages)
    if not texts and not images:
        # OcrEngineUnavailable (a config fault) propagates from ocr.page_texts above and never
        # reaches here — so this message means a healthy OCR run found a genuinely empty document.
        raise ValueError("PDF has no extractable content.")
    return "\n\n".join(texts), images


def _pdf_table_aware(
    data: bytes, text_max_pages: int, image_max_pages: int, dpi: int, min_chars: int,
    on_note=None, filename: str = "",
) -> tuple[str, list[str]]:
    """Like ``_pdf_text_first`` but a scanned page is read with TABLE-AWARE OCR (``ocr_table``),
    so a ruled Schedule-of-Rates page keeps its Item / Description / Clause Ref / Unit / Rate
    columns. A page with low OCR confidence or unrecoverable columns is rendered to PNG for the
    vision fallback — per page, not the whole SoR. Native-text pages use their text verbatim."""
    import fitz  # PyMuPDF — lazy

    from pipeline import ocr_table  # lazy: pytesseract stays optional for import

    ocr_matrix = fitz.Matrix(300 / 72.0, 300 / 72.0)  # OCR wants a high-res render
    vis_matrix = fitz.Matrix(dpi / 72.0, dpi / 72.0)
    texts: list[str] = []
    images: list[str] = []
    dropped_images = 0
    total_pages = 0
    with fitz.open(stream=data, filetype="pdf") as doc:
        for index in range(min(len(doc), text_max_pages)):
            page = doc[index]
            native = page.get_text("text", sort=True).strip()
            if len(native) >= min_chars:
                texts.append(f"[page {index + 1}]\n{native}")
                continue
            png = page.get_pixmap(matrix=ocr_matrix, alpha=False).tobytes("png")
            row_text, confident = ocr_table.rows_text(png)
            if confident and row_text.strip():
                texts.append(f"[page {index + 1}]\n{row_text}")  # column-structured rows -> DeepSeek
            elif _has_image_content(page):
                if len(images) < image_max_pages:
                    pix = page.get_pixmap(matrix=vis_matrix, alpha=False)
                    images.append(_b64_png(pix.tobytes("png")))  # low confidence -> vision fallback
                else:
                    dropped_images += 1   # past the cap — counted, and reported below
        total_pages = len(doc)
    _report_caps(on_note, filename=filename, total_pages=total_pages,
                 text_max_pages=text_max_pages, image_pages_dropped=dropped_images,
                 image_max_pages=image_max_pages)
    if not texts and not images:
        # OcrEngineUnavailable (a config fault) propagates from ocr.page_texts above and never
        # reaches here — so this message means a healthy OCR run found a genuinely empty document.
        raise ValueError("PDF has no extractable content.")
    return "\n\n".join(texts), images


def extract_document(
    file_bytes: bytes,
    content_type: Optional[str],
    *,
    text_max_pages: int = TEXT_MAX_PAGES,
    image_max_pages: int = IMAGE_MAX_PAGES,
    dpi: int = DEFAULT_DPI,
    min_chars: int = MIN_TEXT_CHARS,
    table_aware: bool = False,
    on_note=None,
    filename: str = "",
) -> tuple[str, list[str]]:
    """Text-first extraction: return ``(text, images)``.

    For a PDF, text-layer pages contribute their extracted text (up to ``text_max_pages``,
    generous — text is cheap) and scanned text pages are read by OCR; only genuine image pages
    (drawings, or low-confidence table pages when ``table_aware``) are rendered to PNG (up to
    ``image_max_pages``, low — vision is expensive). ``table_aware=True`` uses column-recovering
    OCR for scanned pages, so a ruled Schedule of Rates keeps its columns — pass it only for the
    SoR. A non-PDF image returns ``("", [png])`` (vision only). ``fitz`` is imported lazily.
    """
    if not file_bytes:
        raise ValueError("Empty file — nothing to extract.")
    ct = (content_type or "").split(";")[0].strip().lower()
    if ct == "application/pdf" or ct.endswith("/pdf"):
        from pipeline import ocr  # lazy

        if table_aware and ocr.ocr_enabled():
            return _pdf_table_aware(file_bytes, text_max_pages, image_max_pages, dpi, min_chars,
                                    on_note, filename)
        return _pdf_text_first(file_bytes, text_max_pages, image_max_pages, dpi, min_chars,
                               on_note, filename)
    if ct.startswith("image/"):
        return "", [_image_to_png(file_bytes)]
    raise ValueError(
        f"Unsupported document type {content_type!r}. Upload a PDF, JPEG, PNG, or WEBP."
    )
