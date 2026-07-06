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
from typing import Optional

# Caps decoupled by modality: text is cheap, so allow many text pages; vision is
# expensive, so keep a low cap on rendered images (scanned pages only).
TEXT_MAX_PAGES = 200
IMAGE_MAX_PAGES = 8
DEFAULT_DPI = 150
MIN_TEXT_CHARS = 20  # a page with fewer usable characters is treated as scanned (image)


def _b64_png(png_bytes: bytes) -> str:
    return base64.b64encode(png_bytes).decode("ascii")


def _pdf_to_pngs(data: bytes, max_pages: int, dpi: int) -> list[str]:
    import fitz  # PyMuPDF — lazy

    zoom = dpi / 72.0
    matrix = fitz.Matrix(zoom, zoom)
    images: list[str] = []
    with fitz.open(stream=data, filetype="pdf") as doc:
        for index in range(min(len(doc), max_pages)):
            pix = doc[index].get_pixmap(matrix=matrix, alpha=False)
            images.append(_b64_png(pix.tobytes("png")))
    if not images:
        raise ValueError("PDF has no rasterisable pages.")
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
) -> list[str]:
    """Rasterise an uploaded document to a list of base64-encoded PNG images."""
    if not file_bytes:
        raise ValueError("Empty file — nothing to extract.")
    ct = (content_type or "").split(";")[0].strip().lower()
    if ct == "application/pdf" or ct.endswith("/pdf"):
        return _pdf_to_pngs(file_bytes, max_pages=max_pages, dpi=dpi)
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


def _pdf_text_first(
    data: bytes, text_max_pages: int, image_max_pages: int, dpi: int, min_chars: int
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
    with fitz.open(stream=data, filetype="pdf") as doc:
        for index in range(min(len(doc), text_max_pages)):
            page = doc[index]
            text = (page_text[index] if index < len(page_text) else "").strip()
            if len(text) >= min_chars:
                texts.append(f"[page {index + 1}]\n{text}")  # native or OCR text (cheap, to DeepSeek)
            elif len(images) < image_max_pages and _has_image_content(page):
                pix = page.get_pixmap(matrix=matrix, alpha=False)  # genuine image page (a drawing) -> vision
                images.append(_b64_png(pix.tobytes("png")))
            # else: negligible text and no raster content (blank), or past the image cap -> skipped
    if not texts and not images:
        raise ValueError("PDF has no extractable content.")
    return "\n\n".join(texts), images


def _pdf_table_aware(
    data: bytes, text_max_pages: int, image_max_pages: int, dpi: int, min_chars: int
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
            elif len(images) < image_max_pages and _has_image_content(page):
                pix = page.get_pixmap(matrix=vis_matrix, alpha=False)
                images.append(_b64_png(pix.tobytes("png")))  # low-confidence page -> vision fallback
    if not texts and not images:
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
        if table_aware:
            return _pdf_table_aware(file_bytes, text_max_pages, image_max_pages, dpi, min_chars)
        return _pdf_text_first(file_bytes, text_max_pages, image_max_pages, dpi, min_chars)
    if ct.startswith("image/"):
        return "", [_image_to_png(file_bytes)]
    raise ValueError(
        f"Unsupported document type {content_type!r}. Upload a PDF, JPEG, PNG, or WEBP."
    )
