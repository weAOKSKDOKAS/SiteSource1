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

There is no OCR step — a scanned page is handed to the vision model as an image.
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


def _pdf_text_first(
    data: bytes, text_max_pages: int, image_max_pages: int, dpi: int, min_chars: int
) -> tuple[str, list[str]]:
    import fitz  # PyMuPDF — lazy

    zoom = dpi / 72.0
    matrix = fitz.Matrix(zoom, zoom)
    texts: list[str] = []
    images: list[str] = []
    with fitz.open(stream=data, filetype="pdf") as doc:
        for index in range(min(len(doc), text_max_pages)):
            page = doc[index]
            text = page.get_text("text", sort=True).strip()  # reading order
            if len(text) >= min_chars:
                texts.append(f"[page {index + 1}]\n{text}")  # usable text layer (cheap)
            elif len(images) < image_max_pages:
                pix = page.get_pixmap(matrix=matrix, alpha=False)  # scanned -> image (capped)
                images.append(_b64_png(pix.tobytes("png")))
            # else: a scanned page beyond the image cap is skipped (vision is expensive)
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
) -> tuple[str, list[str]]:
    """Text-first extraction: return ``(text, images)``.

    For a PDF, text-layer pages contribute their extracted text (up to ``text_max_pages``,
    generous — text is cheap) and only scanned pages (no usable text layer) are rendered
    to PNG (up to ``image_max_pages``, low — vision is expensive). A non-PDF image returns
    ``("", [png])`` (vision only). ``fitz`` is imported lazily, so this stays offline-safe
    and unit-testable.
    """
    if not file_bytes:
        raise ValueError("Empty file — nothing to extract.")
    ct = (content_type or "").split(";")[0].strip().lower()
    if ct == "application/pdf" or ct.endswith("/pdf"):
        return _pdf_text_first(file_bytes, text_max_pages, image_max_pages, dpi, min_chars)
    if ct.startswith("image/"):
        return "", [_image_to_png(file_bytes)]
    raise ValueError(
        f"Unsupported document type {content_type!r}. Upload a PDF, JPEG, PNG, or WEBP."
    )
