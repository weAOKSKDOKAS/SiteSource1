"""Deterministic PDF structure operations for ingest. No model, no network, no I/O.

Everything here is a pure function of PDF bytes. It answers three questions the planning
call and the splitter need answered before either can act:

* what structure does this document declare about itself (bookmarks, printed contents)?
* which of its pages actually carry text, and which are scans?
* is a proposed split arithmetically sound against the real page count?

The logic is ported from the proven ``document-parser`` prototype (pypdf) onto PyMuPDF,
which the repo already depends on — so this adds no dependency. ``fitz`` is imported
lazily inside each function, matching ``pipeline/documents.py``, so DEMO_MODE and the
test suite never pay for it at import time.
"""

from __future__ import annotations

import re
from typing import Optional

from client_boq.models import (
    TIER_BOOKMARKS,
    TIER_HEURISTIC,
    TIER_TOC,
    TIER_WHOLE,
    InspectReport,
    OutlineNode,
    PartSpec,
    SplitManifest,
)

# A page with fewer usable characters than this is treated as a scan (no text layer).
# Matches ``pipeline.documents.MIN_TEXT_CHARS`` so the two agree on what "scanned" means.
SCANNED_CHAR_THRESHOLD = 20
DEFAULT_DEPTH = 2          # outline depth the draft manifest is cut at
SLUG_MAX_LEN = 32          # short: part paths nest, and Windows caps at 259 chars
MIN_PART_PAGES = 1
_TOC_SCAN_PAGES = 25       # how far into the document to look for its own contents page

_SLUG_STRIP = re.compile(r"[^a-z0-9]+")
# "CONTENTS", "TABLE OF CONTENTS", "LIST OF CONTENTS", "INDEX" as a standalone heading.
_TOC_HEADING = re.compile(r"^\s*(table of |list of )?contents\s*$|^\s*index\s*$", re.I | re.M)
# A contents LINE: some title, then dot leaders or whitespace, then a trailing page number.
_TOC_LINE = re.compile(r"^\s*(?P<title>\S.*?)[\s.]{2,}(?P<page>\d{1,4})\s*$", re.M)
# A divider/cover page: a short page whose text is mostly one shouted heading.
_DIVIDER_MAX_CHARS = 400


def slugify(title: str, max_len: int = SLUG_MAX_LEN) -> str:
    """A short, filesystem-safe slug. Deterministic; never empty."""
    slug = _SLUG_STRIP.sub("-", (title or "").lower()).strip("-")
    slug = re.sub(r"-{2,}", "-", slug)
    return slug[:max_len].rstrip("-") or "part"


def abbreviate(title: str) -> str:
    """A short upper-case tag from a title's initials, e.g. "Conditions of Tender" -> "COT".

    Used for the ``NN_ABBR`` folder name when the planner does not supply one. Stop-words
    are dropped so the tag carries signal; the result is capped at 4 characters.
    """
    words = [w for w in re.split(r"[^A-Za-z0-9]+", title or "") if w]
    skip = {"of", "the", "to", "for", "and", "a", "an", "in", "on"}
    initials = [w[0].upper() for w in words if w.lower() not in skip]
    return "".join(initials[:4]) or "PT"


# ---------------------------------------------------------------------------
# Reading the document
# ---------------------------------------------------------------------------
def _outline(doc) -> list[OutlineNode]:
    """Flatten PyMuPDF's ``get_toc`` into ordered nodes with 1-based physical pages.

    ``get_toc(simple=True)`` yields ``[level, title, page]`` with page already 1-based and
    ``-1`` for a destination that does not resolve.
    """
    nodes: list[OutlineNode] = []
    try:
        raw = doc.get_toc(simple=True) or []
    except Exception:  # noqa: BLE001 — a malformed outline is not a failure, just no outline
        return []
    for entry in raw:
        if not entry or len(entry) < 3:
            continue
        level, title, page = entry[0], entry[1], entry[2]
        nodes.append(OutlineNode(
            title=str(title or "").strip(),
            page=int(page) if isinstance(page, int) and page > 0 else None,
            depth=max(1, int(level or 1)),
        ))
    return nodes


def _page_chars(doc, limit: Optional[int] = None) -> list[int]:
    """Extracted character count per page — the scanned-page detector."""
    counts: list[int] = []
    pages = len(doc) if limit is None else min(len(doc), limit)
    for index in range(pages):
        try:
            counts.append(len((doc[index].get_text() or "").strip()))
        except Exception:  # noqa: BLE001 — an unreadable page counts as zero text, not a crash
            counts.append(0)
    return counts


def _find_toc_text(doc, page_chars: list[int]) -> str:
    """Text of the document's own contents pages, when it has one near the front."""
    chunks: list[str] = []
    for index in range(min(len(doc), _TOC_SCAN_PAGES)):
        if index < len(page_chars) and page_chars[index] < SCANNED_CHAR_THRESHOLD:
            continue
        try:
            text = doc[index].get_text() or ""
        except Exception:  # noqa: BLE001
            continue
        head = text[:300]
        if _TOC_HEADING.search(head) or len(_TOC_LINE.findall(text)) >= 5:
            chunks.append(text)
    return "\n".join(chunks)


# ---------------------------------------------------------------------------
# Deriving a draft split
# ---------------------------------------------------------------------------
def cut_outline(nodes: list[OutlineNode], depth: int) -> list[OutlineNode]:
    """The outline nodes that form a segmentation at ``depth``.

    A node is emitted when its depth equals the target, or when it is shallower and has no
    child (so a top-level section with no subsections is not silently dropped).
    """
    picked: list[OutlineNode] = []
    for i, node in enumerate(nodes):
        if node.page is None:
            continue
        if node.depth == depth:
            picked.append(node)
        elif node.depth < depth:
            has_child = i + 1 < len(nodes) and nodes[i + 1].depth > node.depth
            if not has_child:
                picked.append(node)
    picked.sort(key=lambda n: n.page or 0)
    return picked


def _parts_from_starts(starts: list[tuple[str, int]], n_pages: int) -> list[PartSpec]:
    """Turn ordered ``(title, start_page)`` markers into contiguous, gap-free parts.

    Each part runs to the page before the next marker; the last runs to the end. A leading
    gap becomes an explicit front-matter part rather than silently vanishing — no page of
    the source is ever unaccounted for.
    """
    ordered = sorted((s for s in starts if s[1] >= 1), key=lambda s: s[1])
    if not ordered:
        return []
    parts: list[PartSpec] = []
    for idx, (title, start) in enumerate(ordered):
        end = ordered[idx + 1][1] - 1 if idx + 1 < len(ordered) else n_pages
        parts.append(PartSpec(
            n=0, abbr=abbreviate(title), slug=slugify(title), title=title,
            start=start, end=max(start, end),
        ))
    if parts[0].start > 1:
        parts.insert(0, PartSpec(
            n=0, abbr="FM", slug="front-matter", title="Front matter (before the first section)",
            start=1, end=parts[0].start - 1,
        ))
    for i, part in enumerate(parts, start=1):
        part.n = i
    return parts


def _toc_starts(toc_text: str, n_pages: int) -> list[tuple[str, int]]:
    """Parse ``title .... 12`` lines out of the document's printed contents.

    The printed numbers are the document's OWN labels, which routinely differ from physical
    pages (a binder's body often restarts at 1 after front matter). We do not trust them as
    physical pages; we return them for the caller to offset-verify.
    """
    found: list[tuple[str, int]] = []
    for match in _TOC_LINE.finditer(toc_text or ""):
        title = re.sub(r"[\s.]+$", "", match.group("title")).strip()
        try:
            page = int(match.group("page"))
        except ValueError:
            continue
        if title and 1 <= page <= n_pages * 2:  # allow for a label/physical offset
            found.append((title, page))
    return found


def _normalise(text: str) -> str:
    """Lower-case, alphanumeric-only — for comparing a contents entry to a page's heading."""
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def verify_label_offset(
    doc, toc_hits: list[tuple[str, int]], n_pages: int,
) -> tuple[Optional[int], int]:
    """Find the constant offset between the document's PRINTED page labels and its physical
    pages, by testing candidate offsets and checking whether the section titles actually
    land where each offset predicts. Returns ``(offset, matches)``, or ``(None, 0)``.

    This is the difference between reading a contents page and trusting it. A binder that
    restarts its numbering after front matter will claim "Conditions of Tender ... 1" on
    physical page 7; only a verified offset turns that claim into a usable cut.
    """
    if not toc_hits:
        return None, 0
    candidates = range(0, min(n_pages, 60))
    best_offset, best_matches = None, 0
    needed = max(3, (len(toc_hits) + 1) // 2)  # a bare majority of entries must land
    for offset in candidates:
        matches = 0
        for title, printed in toc_hits:
            physical = printed + offset
            if not (1 <= physical <= n_pages):
                continue
            wanted = _normalise(title)[:28]
            if len(wanted) < 6:
                continue
            # Probe the predicted page EXACTLY. Tolerating a page of drift here would make
            # neighbouring offsets score identically, and the tie would silently resolve to the
            # lowest one — putting every boundary a page early. The offset is the thing being
            # solved for; smoothing it defeats the measurement.
            try:
                head = _normalise(doc[physical - 1].get_text() or "")[:1200]
            except Exception:  # noqa: BLE001
                continue
            if wanted in head:
                matches += 1
        if matches > best_matches:
            best_offset, best_matches = offset, matches
    if best_matches >= needed:
        return best_offset, best_matches
    return None, 0


def _divider_starts(doc, page_chars: list[int]) -> list[tuple[str, int]]:
    """Pages that look like section dividers: short, heading-shaped, mostly upper case.

    The weakest signal in the ladder, used only when neither bookmarks nor a contents page
    produced a usable structure.
    """
    starts: list[tuple[str, int]] = []
    for index, chars in enumerate(page_chars):
        if not (0 < chars <= _DIVIDER_MAX_CHARS):
            continue
        try:
            text = (doc[index].get_text() or "").strip()
        except Exception:  # noqa: BLE001
            continue
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        if not lines:
            continue
        heading = max(lines, key=len)
        letters = [c for c in heading if c.isalpha()]
        if len(heading) < 4 or not letters:
            continue
        upper_ratio = sum(1 for c in letters if c.isupper()) / len(letters)
        if upper_ratio >= 0.7 and len(lines) <= 6:
            starts.append((heading[:120], index + 1))
    return starts


def plan_draft(
    doc, n_pages: int, nodes: list[OutlineNode], page_chars: list[int], toc_text: str,
    depth: int = DEFAULT_DEPTH,
) -> tuple[list[PartSpec], int, str]:
    """The confidence ladder. Returns ``(parts, tier, reason)``.

    Tier 1 the PDF's own bookmarks; tier 2 its printed contents; tier 3 divider-page
    heuristics; tier 4 no reliable structure, so one part covering the whole document.
    Tier 4 is a DEGRADED SUCCESS: the document still ingests, flagged for a manual split.
    Never raises — a document we cannot segment is still a document we can review.
    """
    picked = cut_outline(nodes, depth)
    if len(picked) < 2 and nodes:
        # The requested depth was too deep (or too shallow) for this outline; try depth 1.
        picked = cut_outline(nodes, 1)
    if len(picked) >= 2:
        parts = _parts_from_starts([(n.title, n.page or 1) for n in picked], n_pages)
        if len(parts) >= 2:
            return parts, TIER_BOOKMARKS, f"{len(nodes)} bookmarks; cut at outline depth {depth}"

    toc_hits = _toc_starts(toc_text, n_pages)
    if len(toc_hits) >= 3:
        offset, matched = verify_label_offset(doc, toc_hits, n_pages)
        if offset is not None:
            shifted = [(t, p + offset) for t, p in toc_hits if 1 <= p + offset <= n_pages]
            parts = _parts_from_starts(shifted, n_pages)
            if len(parts) >= 2:
                return parts, TIER_TOC, (
                    f"no usable bookmarks; {len(shifted)} entries read from the document's own "
                    f"contents page. Printed page labels sit {offset:+d} from physical pages, "
                    f"verified by finding {matched} of {len(toc_hits)} section titles on the "
                    f"pages that offset predicts"
                )

    dividers = _divider_starts(doc, page_chars)
    if len(dividers) >= 3:
        parts = _parts_from_starts(dividers, n_pages)
        if len(parts) >= 2:
            return parts, TIER_HEURISTIC, (
                f"no bookmarks or contents page; {len(dividers)} divider-style pages detected"
            )

    whole = [PartSpec(n=1, abbr="ALL", slug="whole-document",
                      title="Whole document (not split)", start=1, end=max(1, n_pages))]
    return whole, TIER_WHOLE, (
        "no bookmarks, contents page, or divider pages found — ingested as a single part; "
        "edit the manifest to split it by hand"
    )


def mark_scanned(parts: list[PartSpec], scanned_pages: list[int]) -> list[PartSpec]:
    """Stamp the ``scanned`` flag from the measured page-text coverage.

    A part counts as scanned only when EVERY one of its pages lacks a text layer; one readable
    page makes the part readable. This must be re-applied after the planning call, because
    whether a part has a text layer is a measurement, not a proposal — a model refining the
    split must not be able to clear it by omission.
    """
    lookup = set(scanned_pages)
    for part in parts:
        span = range(part.start, part.end + 1)
        part.scanned = bool(len(span)) and all(p in lookup for p in span)
    return parts


def inspect(data: bytes, filename: str = "document.pdf", depth: int = DEFAULT_DEPTH) -> InspectReport:
    """Read a PDF's structure deterministically and derive a draft split manifest."""
    import fitz  # PyMuPDF — lazy, matching pipeline/documents.py

    if not data:
        raise ValueError("Empty file — nothing to inspect.")
    with fitz.open(stream=data, filetype="pdf") as doc:
        if doc.needs_pass:
            raise ValueError("This PDF is encrypted. Remove the password and upload it again.")
        n_pages = len(doc)
        meta = {str(k): str(v) for k, v in (doc.metadata or {}).items() if v}
        nodes = _outline(doc)
        page_chars = _page_chars(doc)
        toc_text = _find_toc_text(doc, page_chars)
        parts, tier, reason = plan_draft(doc, n_pages, nodes, page_chars, toc_text, depth)

    scanned = [i + 1 for i, c in enumerate(page_chars) if c < SCANNED_CHAR_THRESHOLD]
    mark_scanned(parts, scanned)

    return InspectReport(
        filename=filename,
        pages=n_pages,
        metadata=meta,
        outline=nodes,
        outline_depth_used=depth,
        page_chars=page_chars,
        scanned_pages=scanned,
        total_chars=sum(page_chars),
        toc_text=toc_text[:20000],
        draft=SplitManifest(
            source_doc=filename, pages=n_pages, prefix=slugify(filename.rsplit(".", 1)[0]),
            tier=tier, tier_reason=reason, parts=parts, scanned_pages=scanned,
        ),
    )


# ---------------------------------------------------------------------------
# Validating and performing the cut
# ---------------------------------------------------------------------------
# How much of the document a manifest must account for before the cut is offered at all.
#
# The number has to sit far from BOTH neighbours to be worth anything. A real split lands at or
# very near 100%: the planner is told to make adjacent parts touch, and the honest misses are a
# trailing blank leaf or an unassigned divider — a percent or two on any document large enough to
# be a tender. The failure this exists to catch is a planner that collapsed to a stub, which lands
# at 1/26 = 4%. 60% is in the empty middle: nothing legitimate has ever been observed below it,
# and nothing broken near it.
#
# Why not "any gap is an error"? Because a gap IS recoverable and the human gate exists to weigh
# it — `test_gaps_and_overlaps_are_warnings_not_errors` pins that on purpose, and turning a
# stray unassigned page into a hard refusal would block real work to catch a fault of a different
# size. Why not 90%? A binder plus loose annexes can legitimately leave more unassigned than one
# would guess, and an error a person cannot clear from the screen is worse than a warning they can
# read. The gap and overlap warnings still fire underneath this, so a near-miss is never silent.
MIN_COVERAGE_SHARE = 0.6


def validate(manifest: SplitManifest, n_pages: int) -> tuple[list[str], list[str]]:
    """Check a manifest against the real page count. Returns ``(errors, warnings)``.

    Errors mean the cut cannot be performed (out of bounds, inverted, empty). Warnings mean
    it can, but the human should see it first (gaps, overlaps, partial coverage). This is
    the deterministic half of "the LLM decides, code cuts" — a proposal that fails here is
    rejected regardless of how confident the model was.
    """
    errors: list[str] = []
    warnings: list[str] = []
    if not manifest.parts:
        errors.append("The manifest has no parts.")
        return errors, warnings

    # Only the parts cut out of the binder are checked against its page count. A set may also
    # carry loose documents uploaded alongside it, each already its own part; those page ranges
    # belong to a different file and are not this document's business.
    binder = [p for p in manifest.parts
              if not p.source_doc or p.source_doc == manifest.source_doc]
    if not binder:
        return errors, warnings

    for part in binder:
        if part.start < 1 or part.end > n_pages:
            errors.append(
                f"Part {part.n} ({part.title!r}) covers pages {part.start}-{part.end}, "
                f"outside the document's 1-{n_pages}."
            )
        elif part.end < part.start:
            errors.append(
                f"Part {part.n} ({part.title!r}) ends on page {part.end}, before it starts "
                f"on page {part.start}."
            )

    report = coverage(manifest, n_pages)
    for gap in report["gaps"]:
        warnings.append(f"Pages {gap['start']}-{gap['end']} belong to no part.")
    for overlap in report["overlaps"]:
        warnings.append(
            f"Parts {overlap['parts'][0]} and {overlap['parts'][1]} overlap on pages "
            f"{overlap['start']}-{overlap['end']}."
        )
    # Coverage far below the document is an ERROR, not a warning. A warning is an invitation to
    # look; this is a manifest that is not a split of this document at all — the observed case was
    # a planning call returning ONE part bounded 1-1 for a 26-page bill, which passed every
    # bounds check (1 >= 1, 1 <= 26, 1 >= 1) and was offered for approval with a green button.
    # A human approving that loses 25 of 26 pages silently.
    if not errors and n_pages > 0 and report["covered_pages"] < n_pages * MIN_COVERAGE_SHARE:
        errors.append(
            f"The parts cover only {report['covered_pages']} of {n_pages} pages "
            f"({report['covered_pages'] / n_pages:.0%}); a split must account for at least "
            f"{MIN_COVERAGE_SHARE:.0%} of the document. Edit the page ranges, or re-run the "
            "ingest if the document itself is wrong."
        )
    if not errors and report["covered"] != n_pages:
        warnings.append(f"The parts cover {report['covered']} of {n_pages} pages.")
    return errors, warnings


def coverage(manifest: SplitManifest, n_pages: int) -> dict:
    """Which pages of the binder are covered, and where the split breaks.

    Structured rather than prose because the gate is not the only reader: the manifest screen
    draws a coverage bar with a visible break at every gap, and shows a gaps/overlaps count
    beside the Approve button. That count is the evidence the approval rests on, so it has to be
    computed by the same code the gate refuses on — a screen saying "0 gaps" over a gate that
    then complains about one would be worse than showing nothing at all.
    """
    binder = [p for p in manifest.parts
              if not p.source_doc or p.source_doc == manifest.source_doc]
    gaps: list[dict] = []
    overlaps: list[dict] = []
    ordered = sorted(binder, key=lambda p: p.start)
    # The interior: every pair of neighbours. This walk ALONE was the whole of the check, and a
    # walk over pairs cannot see either end — a manifest whose single part covered page 1 of a
    # 26-page bill produced no pairs at all and reported 0 gaps, over a gate that then refused it.
    # The head and tail are checked separately, below and above the loop.
    if ordered and n_pages > 0 and ordered[0].start > 1:
        gaps.append({"start": 1, "end": min(ordered[0].start - 1, n_pages)})
    for a, b in zip(ordered, ordered[1:]):
        if b.start > a.end + 1:
            gaps.append({"start": a.end + 1, "end": b.start - 1})
        elif b.start <= a.end:
            overlaps.append({"start": b.start, "end": min(a.end, b.end), "parts": [a.n, b.n]})
    # `max(end)`, not `ordered[-1].end`: the ordering is by START, so a part that begins earlier
    # can still end later than the last one to begin.
    last_end = max((p.end for p in ordered), default=0)
    if ordered and n_pages > 0 and last_end < n_pages:
        gaps.append({"start": last_end + 1, "end": n_pages})
    return {
        "pages": n_pages,
        # The sum of the parts' own lengths — kept as it was, because callers depend on it and it
        # is what the manifest screen prints. It double-counts an overlap and can exceed `pages`.
        "covered": sum(p.page_count() for p in binder),
        # DISTINCT pages of THIS document that some part claims, clamped to the real document.
        # This is the honest coverage figure, and the one `validate` judges on: a manifest that
        # covers page 4 twice has not covered five pages.
        "covered_pages": len({
            page
            for p in binder
            for page in range(max(1, p.start), min(p.end, n_pages) + 1)
        }) if n_pages > 0 else 0,
        "gaps": gaps,
        "overlaps": overlaps,
    }


def slice_pdf(data: bytes, start: int, end: int) -> bytes:
    """Extract pages ``start``..``end`` (1-based inclusive) into a new PDF.

    Deterministic and defensive: an unusable range returns the original bytes rather than
    fabricating or dropping content, the same choice the procurement slicer makes.
    """
    import fitz  # PyMuPDF — lazy

    if not data or end < start or start < 1:
        return data
    try:
        with fitz.open(stream=data, filetype="pdf") as src:
            last = min(end, len(src))
            if start > last:
                return data
            out = fitz.open()
            out.insert_pdf(src, from_page=start - 1, to_page=last - 1)
            result = out.tobytes()
            out.close()
            return result or data
    except Exception:  # noqa: BLE001 — never let a slice failure lose the document
        return data


# Typographic pairs that read identically but are different characters. A quotation retyped or
# produced by a model uses the straight forms; a professionally typeset tender uses the curly
# ones. Measured on the reference documents: 81 curly quotes in the ND General Conditions of
# Tender, 44 in the CIC General Conditions of Employment, 31 in its Conditions of Tender — so a
# quotation containing an apostrophe fails to match unless both forms are tried.
_TYPOGRAPHIC = [("'", "’"), ('"', "“"), ('"', "”"), ("-", "–"), ("-", "—")]


def _variants(text: str) -> list[str]:
    """The same text written with straight and with typographic punctuation."""
    out = [text]
    swapped = text
    for plain, fancy in _TYPOGRAPHIC:
        swapped = swapped.replace(plain, fancy)
    if swapped != text:
        out.append(swapped)
    flattened = text
    for plain, fancy in _TYPOGRAPHIC:
        flattened = flattened.replace(fancy, plain)
    if flattened not in out:
        out.append(flattened)
    return out


def _search_fragments(needle: str, min_len: int = 45) -> list[str]:
    """Progressively shorter pieces of a quotation to look for.

    A quotation is tried whole first. Failing that, its sentences, then its longest clause-like
    run: a wrapped line, a table cell or a column break can split a quotation in the stored text
    even though the words are plainly on the page, and a distinctive fragment still pins the page
    down. Anything shorter than ``min_len`` is dropped — a short fragment matches by accident and
    a citation confirmed by accident is worse than one left unconfirmed.
    """
    whole = re.sub(r"\s+", " ", (needle or "")).strip()
    if not whole:
        return []
    out = [whole]
    for piece in re.split(r"(?<=[.;:])\s+", whole):
        piece = piece.strip()
        if len(piece) >= min_len and piece != whole:
            out.append(piece)
    # A long leading run, for a quotation whose tail wandered into another column.
    if len(whole) > min_len * 2:
        out.append(whole[:int(len(whole) * 0.6)].rsplit(" ", 1)[0])
    seen, unique = set(), []
    for item in out:
        if item not in seen and len(item) >= min_len:
            seen.add(item)
            unique.append(item)
    return unique


def locate(data: bytes, needle: str, start: int = 1, end: int = 0,
           page_offset: int = 0) -> Optional[dict]:
    """Find ``needle`` on a page of ``data``. Returns the page, how it matched, and rectangles.

    ``page_offset`` is added to the page number found, so a part that was cut from page 17 of a
    binder reports page numbers in the binder's terms rather than its own. Rectangles come back as
    fractions of page width and height, so a viewer can overlay them at any scale.

    Returns None when nothing matched, and None is deliberately ambiguous on its own: it means
    "not found here", not "the citation is wrong". The caller decides which, because only the
    caller knows whether this document was searchable at all.
    """
    import fitz  # PyMuPDF — lazy

    fragments = _search_fragments(needle)
    if not data or not fragments:
        return None
    try:
        with fitz.open(stream=data, filetype="pdf") as doc:
            last = len(doc) if end <= 0 else min(end, len(doc))
            for kind, fragment in (("exact", fragments[0]),
                                   *(("fragment", f) for f in fragments[1:])):
                for index in range(max(0, start - 1), last):
                    page = doc[index]
                    rects = []
                    for variant in _variants(fragment):
                        try:
                            rects = page.search_for(variant)
                        except Exception:  # noqa: BLE001
                            rects = []
                        if rects:
                            break
                    if not rects:
                        continue
                    width = page.rect.width or 1.0
                    height = page.rect.height or 1.0
                    return {
                        "page": index + 1 + page_offset,
                        "match": kind,
                        "matched_text": fragment,
                        "highlights": [
                            {"page": index + 1 + page_offset,
                             "x0": round(r.x0 / width, 5), "y0": round(r.y0 / height, 5),
                             "x1": round(r.x1 / width, 5), "y1": round(r.y1 / height, 5)}
                            for r in rects
                        ],
                    }
    except Exception:  # noqa: BLE001 — an unreadable document is unverifiable, not a crash
        return None
    return None


def has_text_layer(data: bytes, start: int = 1, end: int = 0) -> bool:
    """Whether a document carries enough text to be searched at all.

    The difference between "we looked and it is not there" and "we could not look".
    """
    import fitz  # PyMuPDF — lazy

    if not data:
        return False
    try:
        with fitz.open(stream=data, filetype="pdf") as doc:
            last = len(doc) if end <= 0 else min(end, len(doc))
            chars = 0
            for index in range(max(0, start - 1), last):
                chars += len((doc[index].get_text() or "").strip())
                if chars >= SCANNED_CHAR_THRESHOLD:
                    return True
    except Exception:  # noqa: BLE001
        return False
    return False


def page_text(data: bytes, start: int, end: int) -> str:
    """Plain text of a page range, each page prefixed ``[page N]`` with N the SOURCE page
    number — so a citation read out of a part still points at the original binder.

    ``sort=True``, and that is the whole of the fix for the worst defect this module has had.
    PyMuPDF's default returns text in the order the PDF's content stream happens to store it,
    which on a ruled bill page is NOT reading order: the column-B headings land in a clump at the
    bottom of the page, detached from the column-C items they govern. Bill 6 of CEDD ND/2025/04
    came out as six items and three descriptions — 6.1 "Standpipe" and 6.4 "Standpipe", where the
    real difference (installing one, versus recording from one) lived entirely in a heading the
    model never saw. Sorted, the headings sit above their items, and PyMuPDF space-pads the text
    to reflect the layout, so the column an entry sat in survives as leading whitespace. That
    indentation is what :func:`~pipeline.stage_01_ingest.ingest.heading_chains` reads.

    Only the newlines are stripped, never the spaces: stripping the page would cost its FIRST
    line the indent that says what level it is.

    The other ``get_text()`` calls in this module are deliberately left unsorted. Sorting adds
    ~1,300-1,600 padding characters per page, and ``_page_chars`` is a MEASUREMENT of how much
    real text a page carries — measured on the sample tender, sorting moves three near-blank
    pages above the scanned threshold on padding alone. A measurement must not be inflated by
    whitespace it did not have.
    """
    import fitz  # PyMuPDF — lazy

    if not data:
        return ""
    chunks: list[str] = []
    try:
        with fitz.open(stream=data, filetype="pdf") as doc:
            for index in range(max(0, start - 1), min(end, len(doc))):
                try:
                    text = (doc[index].get_text("text", sort=True) or "").strip("\n")
                except Exception:  # noqa: BLE001
                    text = ""
                if text.strip():
                    chunks.append(f"[page {index + 1}]\n{text}")
    except Exception:  # noqa: BLE001
        return ""
    return "\n\n".join(chunks)


# ---------------------------------------------------------------------------
# Showing a page, and looking things up on it
# ---------------------------------------------------------------------------
# Render DPI bounds. 110 reads comfortably at the ~400px pane width the design uses, and the
# ceiling exists because the DPI arrives from a query string: a request for 4000 would otherwise
# ask PyMuPDF to allocate a multi-gigabyte pixmap.
DEFAULT_RENDER_DPI = 110
MIN_RENDER_DPI = 40
MAX_RENDER_DPI = 300

# A ceiling on the rendered image, not just on the DPI, because a DPI means different things to
# different paper. Measured on the reference tender: at 110 DPI an A4 condition page renders
# 910px wide and weighs ~60KB, but the A3 drawing sheets in part 07 render 1819px and weigh
# **1.6MB each** — the same request producing a 27x heavier response purely because the paper is
# bigger. The pane is ~400-470px wide, so 1400px still leaves better than 2x for zoom.
MAX_RENDER_WIDTH_PX = 1400


def render_page(data: bytes, page: int, dpi: int = DEFAULT_RENDER_DPI) -> Optional[bytes]:
    """Rasterise one 1-based page to PNG bytes. None when the page does not exist.

    A scan rasterises exactly like a born-digital page — the viewer shows the same thing either
    way — which is why the pane can display a part that ``has_text_layer`` says cannot be searched.
    Seeing it and searching it are different questions.
    """
    import fitz  # PyMuPDF — lazy

    if not data or page < 1:
        return None
    dpi = max(MIN_RENDER_DPI, min(int(dpi or DEFAULT_RENDER_DPI), MAX_RENDER_DPI))
    try:
        with fitz.open(stream=data, filetype="pdf") as doc:
            if page > len(doc):
                return None
            target = doc[page - 1]
            # Points are 1/72", so width_px = width_pt * dpi / 72. Solve for the DPI that lands
            # on the ceiling and take whichever is smaller — an oversized sheet is scaled down,
            # an ordinary one is untouched.
            width_pt = target.rect.width or 1.0
            fitting = int(MAX_RENDER_WIDTH_PX * 72 / width_pt)
            pixmap = target.get_pixmap(dpi=max(MIN_RENDER_DPI, min(dpi, fitting)))
            return pixmap.tobytes("png")
    except Exception:  # noqa: BLE001 — an unrenderable page is a 404, not a crash
        return None


#: How much of the sheet's height the header strip is worth carrying into every band. The column
#: headings live at the top of the table and a band without them is a grid of numbers whose columns
#: nobody can name — so every band gets the top of the sheet stacked above its own slice.
#:
#: ERRS GENEROUS ON PURPOSE. Too small and a band loses the column names, which is fatal and silent:
#: the model would map twelve numeric columns by guessing. Too large and the first rows are read in
#: every band, which is wasteful and harmless — the caller de-duplicates on the station name.
BAND_HEADER_SHARE = 0.22

#: How far each band reaches into its neighbours. A table row split by a boundary must appear WHOLE
#: in at least one band, and the caller de-duplicates on the station name afterwards. 6% of an A3
#: sheet is roughly two row heights on a 91-row table — enough for the row, small enough that the
#: overlap is not a second read of the table.
BAND_OVERLAP_SHARE = 0.06


def render_band(data: bytes, page: int, band: int, bands: int,
                dpi: int = DEFAULT_RENDER_DPI) -> Optional[bytes]:
    """One horizontal slice of a page, with the sheet's header stacked above it. PNG or None.

    WHY THIS EXISTS. A 91-row schedule's transcription does not fit in one answer: measured on the
    real pack, it needs ~9,200-10,250 output tokens against a default ceiling of 8,000, so the
    model wrote valid JSON and ran out of room. Splitting the SHEET is the only fix that keeps
    working when somebody's table is bigger still — and it is the one that turns a whole-sheet
    failure into a partial read, because band 3 failing leaves bands 1, 2, 4 and 5 read.

    TWO THINGS MAKE A BAND READABLE, and both are geometry rather than judgement:

    * **The header travels with every band.** The column headings are printed once, at the top. A
      middle band on its own is a grid of numbers whose columns nobody can name, so the top
      ``BAND_HEADER_SHARE`` of the sheet is composed above each band's own slice — one image, two
      crops, no model involved in deciding what a column means.
    * **Bands overlap.** A row cut in half by a boundary would otherwise be half-read twice or lost
      once. Each band reaches ``BAND_OVERLAP_SHARE`` into its neighbours so every row is whole
      somewhere, and the caller de-duplicates on the station name — first occurrence wins, as
      everywhere else in this module.

    Band 0 of 1 is the whole page and is exactly :func:`render_page`, so a caller can ask for one
    band without a special case.
    """
    import fitz  # PyMuPDF — lazy

    if not data or page < 1 or bands < 1 or band < 0 or band >= bands:
        return None
    if bands == 1:
        return render_page(data, page, dpi)
    dpi = max(MIN_RENDER_DPI, min(int(dpi or DEFAULT_RENDER_DPI), MAX_RENDER_DPI))
    try:
        with fitz.open(stream=data, filetype="pdf") as doc:
            if page > len(doc):
                return None
            source = doc[page - 1]
            rect = source.rect
            height = rect.height or 1.0
            overlap = height * BAND_OVERLAP_SHARE
            step = height / bands
            top = max(rect.y0, rect.y0 + band * step - overlap)
            bottom = min(rect.y1, rect.y0 + (band + 1) * step + overlap)
            header = fitz.Rect(rect.x0, rect.y0, rect.x1, rect.y0 + height * BAND_HEADER_SHARE)
            body = fitz.Rect(rect.x0, top, rect.x1, bottom)

            # A BAND THAT ALREADY STARTS AT THE TOP DOES NOT NEED THE TOP STACKED ABOVE IT.
            # Band 0's body IS the head of the sheet, so composing the header strip above it
            # printed the table's heading twice and repeated the first rows underneath themselves.
            # At best that is a bigger image and a longer answer for nothing; at worst it asks the
            # model to make sense of a table that appears to restart. Either way it is not the
            # picture the sheet is.
            if body.y0 <= header.y0 + 0.5:
                target_doc = fitz.open()
                width = rect.width or 1.0
                page_only = target_doc.new_page(width=width, height=body.height)
                page_only.show_pdf_page(fitz.Rect(0, 0, width, body.height), doc, page - 1,
                                        clip=body)
                fitting_only = int(MAX_RENDER_WIDTH_PX * 72 / width)
                png_only = page_only.get_pixmap(
                    dpi=max(MIN_RENDER_DPI, min(dpi, fitting_only))).tobytes("png")
                target_doc.close()
                return png_only

            # A new page the height of both crops, with the header composed above the body. Done
            # with `show_pdf_page` rather than by stitching two pixmaps, so it needs nothing but
            # PyMuPDF and stays vector until the single rasterise at the end.
            composed = fitz.open()
            width = rect.width or 1.0
            target = composed.new_page(width=width, height=header.height + body.height)
            target.show_pdf_page(fitz.Rect(0, 0, width, header.height), doc, page - 1, clip=header)
            target.show_pdf_page(
                fitz.Rect(0, header.height, width, header.height + body.height),
                doc, page - 1, clip=body)
            fitting = int(MAX_RENDER_WIDTH_PX * 72 / width)
            pixmap = target.get_pixmap(dpi=max(MIN_RENDER_DPI, min(dpi, fitting)))
            png = pixmap.tobytes("png")
            composed.close()
            return png
    except Exception:  # noqa: BLE001 — an unrenderable band is a gap, not a crash
        return None


# The search box has no minimum length, unlike :func:`_search_fragments`' 45-character floor.
# The floor exists because a citation confirmed by an accidental match is worse than one left
# unconfirmed — it is a rule about *proof*. A person typing into a search box is not making a
# claim about the document, so the same rule does not apply and applying it would break the
# feature. Do not "fix" this to share the constant.
SEARCH_MAX_HITS = 60


def search(data: bytes, needle: str, start: int = 1, end: int = 0,
           page_offset: int = 0, max_hits: int = SEARCH_MAX_HITS) -> list[dict]:
    """Every place ``needle`` appears, as pages plus fractional rectangles.

    Same coordinate contract as :func:`locate` — fractions of page width and height, page numbers
    shifted by ``page_offset`` into the source document's numbering — so the viewer draws a search
    hit and a citation highlight through one code path.

    An empty list is honestly ambiguous: no hits, or nothing searchable. The caller pairs it with
    :func:`has_text_layer` to tell the user which.
    """
    import fitz  # PyMuPDF — lazy

    query = re.sub(r"\s+", " ", (needle or "")).strip()
    if not data or not query:
        return []
    hits: list[dict] = []
    try:
        with fitz.open(stream=data, filetype="pdf") as doc:
            last = len(doc) if end <= 0 else min(end, len(doc))
            for index in range(max(0, start - 1), last):
                page = doc[index]
                rects = []
                for variant in _variants(query):
                    try:
                        rects = page.search_for(variant)
                    except Exception:  # noqa: BLE001
                        rects = []
                    if rects:
                        break
                if not rects:
                    continue
                width = page.rect.width or 1.0
                height = page.rect.height or 1.0
                number = index + 1 + page_offset
                hits.append({
                    "page": number,
                    "highlights": [
                        {"page": number,
                         "x0": round(r.x0 / width, 5), "y0": round(r.y0 / height, 5),
                         "x1": round(r.x1 / width, 5), "y1": round(r.y1 / height, 5)}
                        for r in rects
                    ],
                })
                if len(hits) >= max_hits:
                    break
    except Exception:  # noqa: BLE001
        return []
    return hits
