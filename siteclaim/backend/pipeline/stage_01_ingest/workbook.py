"""The bill of quantities, read from the workbook it was written in. Zero model calls.

A SECOND PRODUCER OF THE SAME SHAPE, not a second pipeline. This emits the ``SorItem`` list
``ingest_tender`` emits, so routing, packages and the split report are unchanged. The PDF path
stays exactly as it is; the reader is chosen by file type.

Why it is worth building, given the PDF path now works. Sorted extraction already recovered the
heading hierarchy — Bills 2 and 4 extract exactly, 26 of 26 and 28 of 28. The case is cost and
fidelity: the PDF path spent roughly one hundred model calls over ten minutes on a 26-page bill,
lost five items at chunk boundaries and invented one. This needs no model call at all, cannot lose
an item at a chunk boundary because it never chunks, and cannot scramble reading order because rows
are rows.

Three things the workbook carries that no render does, measured in the real file:

* **Rate versus lump sum, unambiguously.** Bill 9 row 8 is ``=E8*G8`` — quantity times rate. Row 38
  is ``=G38`` — a lump sum. In the render both are blank cells.
* **Employer-fixed rates.** Every Bill 9 rate is pre-filled by CEDD under the Pay for Safety
  Scheme. An engine that generates a rate for one of those is wrong by definition, and no current
  validation flag would catch it. The workbook is where that is a fact rather than an inference.
* **Structure rather than inferred structure.** The heading chain is WHICH COLUMN the text occupies
  — ``Instrument Installation`` in B, ``6.1 Standpipe`` in C. In the sorted render it is how many
  spaces PyMuPDF happened to pad with. One is a fact; the other is a good reading.

``openpyxl`` is already pinned at 3.1.5 and used by the levelling export. It is imported lazily, so
nothing here costs anything on a PDF-only run.
"""

from __future__ import annotations

import re
from typing import Callable, Optional

from schemas.models import SorItem

Note = Optional[Callable[[str], None]]

# Sheets that are not bills. `Index` and `Grand Summary` carry no priced rows and reading them
# would invent items out of a table of contents.
_SKIP_SHEETS = re.compile(r"^\s*(index|contents|grand\s+summary|summary|cover)\s*$", re.I)
_BILL_SHEET = re.compile(r"^\s*bill\s*(?:no\.?)?\s*(\d{1,2})\b", re.I)

# The column layout of the real workbook. A = item ref; B/C/D = description at three indent levels;
# E = quantity; F = unit; G = rate; H = amount.
_COL_REF = 1
_COL_DESC = (2, 3, 4)
_COL_QTY, _COL_UNIT, _COL_RATE, _COL_AMOUNT = 5, 6, 7, 8

# Page furniture, repeating roughly every 57 rows. None of it is content, and every line of it
# would otherwise read as either an item or a heading.
_FURNITURE = re.compile(
    r"^\s*(?:"
    r"bill\s*(?:no\.?)?\s*\d+\b"                      # the per-page banner
    r"|item\s*no\.?\b"                                 # the column header row
    r"|item\s+description\b"
    r"|(?:carried|brought)\s+(?:to|forward|down)\b"    # Carried to Collection / Brought Forward
    r"|collection\b"
    r"|page\s+bq\b"
    r"|total\b|sub[-\s]?total\b"
    r"|to\s+collection\b|to\s+summary\b"
    r")",
    re.I,
)

# A literal `-` in the rate column is a SEMANTIC MARKER — this row is not rated — not a missing
# value. Recorded as "not rated" rather than as an absent rate we might later try to fill.
_NOT_RATED = {"-", "–", "—"}


class WorkbookBill:
    """What one workbook yielded, and everything it could not reconcile."""

    def __init__(self) -> None:
        self.items: list[SorItem] = []
        self.per_bill: dict[str, int] = {}
        self.notes: list[str] = []
        self.sheets_read: list[str] = []
        self.sheets_skipped: list[str] = []


def _text(value) -> str:
    return "" if value is None else str(value).strip()


def _number(value) -> Optional[float]:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    text = _text(value).replace(",", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


# A bare "major.minor" reference, which is what a bill item number is once the letter variants and
# the page furniture are out of the way.
_MINOR_REF = re.compile(r"^(\d+)\.(\d+)$")


def restore_dropped_zero(rendered: str, previous: str, *, from_number: bool) -> tuple[str, str]:
    """Put back the trailing zero Excel discarded, where the SEQUENCE proves one was discarded.

    THE DEFECT, measured on the real pack (CEDD ND/2025/04). Bill 1 of the PDF render carries 63
    unique references, 1.1 … 1.63, no gaps and no duplicates. The same bill in the editable
    workbook carries **58 unique references across 63 rows**::

        r 96:  1.19  Servicing of core and sample store for the …    87  wk
        r 98:  1.2   Handing over of core and sample store to …      -   item     <- this is 1.20
        r141:  1.29  Provision                                       -   item
        r143:  1.3   Maintenance                                     -   item     <- this is 1.30

    Excel stored the reference as a NUMBER, so ``1.20`` came back as ``1.2``. Five decade
    boundaries, five collisions with the real items 1.2 … 1.6 near the top of the bill — and two
    genuinely different items then arrive carrying one key. Every index downstream is keyed on the
    reference, so it collapses them and the total counts one line twice.

    :func:`item_ref_of` already recovers this **where the cell's number format says so** — ``0.00``
    means two decimals were printed. On the real file that evidence is absent, so the format is not
    enough and something else has to decide.

    WHY THE SEQUENCE DECIDES IT, and why it is not a guess. A bill sheet numbers its items in
    ascending order; that is what a bill is. So a reference that goes BACKWARDS against the one
    above it did not come from the document — ``1.2`` after ``1.19`` is not item 2 arriving late,
    it is item 20 with a zero missing. Appending zeros until the sequence moves forward again is
    then the only reconstruction consistent with the file, and the smallest one is taken.

    A reference that moves FORWARD is left exactly alone, which is the case that matters most:
    ``1.2`` after ``1.1`` is item 2, and rewriting it would invent a defect where there is none.
    A repeat (``1.2`` after ``1.2``) is also left alone — that is a genuine duplicate and the
    reader's own duplicate check owns it.

    Returns ``(reference, note)``. The note is non-empty whenever the sequence went backwards,
    whether or not it could be explained: an unexplained backwards jump is a fact about the client's
    file that an estimator should see, not something to swallow.
    """
    if not from_number or not rendered or not previous:
        return rendered, ""
    now, before = _MINOR_REF.match(rendered), _MINOR_REF.match(previous)
    if not now or not before or now.group(1) != before.group(1):
        return rendered, ""
    major, digits = now.group(1), now.group(2)
    prior = int(before.group(2))
    if int(digits) >= prior:
        return rendered, ""
    for zeros in (1, 2):
        candidate = digits + ("0" * zeros)
        if int(candidate) > prior:
            restored = f"{major}.{candidate}"
            return restored, (
                f"item {restored} was stored as the number {rendered} — Excel drops a trailing "
                f"zero — and read back as {rendered!r}, which would collide with the real item "
                f"{rendered}. Restored from the sequence: it follows {previous}."
            )
    return rendered, (
        f"item {rendered!r} follows {previous!r}, so the numbering goes backwards here. A bill "
        f"numbers its items in order, and no dropped trailing zero explains this one. Kept exactly "
        f"as printed — repairing a reference on a guess is how a priced row ends up under the "
        f"wrong item."
    )


def compare_reference_sets(workbook_refs, render_refs) -> list[str]:
    """The workbook's item references against the PDF render's. Reports; resolves nothing.

    WHY THIS IS NOT BELT AND BRACES. The pack ships the same bill twice — `BQ/E-…xlsx` is the
    editable workbook and `BQ/I-…pdf` is its render — and the split drops the render, correctly,
    because pricing one bill twice is worse than reading it from the wrong one and a render can
    establish neither a lump sum nor an Employer rate. But "the workbook wins" was applied to the
    ITEM REFERENCE too, and the reference is the one thing the render carries BETTER: a PDF prints
    what was typed, while Excel stores `1.20` as a number and hands back `1.2`.

    Measured on CEDD ND/2025/04, Bill 1: the render carries 63 unique references over 63 rows; the
    workbook carried 58 over the same 63. Five decade boundaries, five collisions, and the
    deterministic path — the one nothing downstream doubts, because it "parses with zero model
    calls" — was the one delivering a corrupted key.

    :func:`restore_dropped_zero` repairs what the ordering proves. This is the independent check on
    that repair, and on everything it cannot reach. A disagreement is not resolved here in either
    file's favour: which document is right about a reference is a question about the client's pack,
    and the estimator is the one who answers it.
    """
    book, render = set(workbook_refs or ()), set(render_refs or ())
    if not book or not render:
        return []
    notes: list[str] = []
    only_render = sorted(render - book, key=_ref_sort)
    only_book = sorted(book - render, key=_ref_sort)
    if only_render:
        notes.append(
            f"the PDF render of this bill carries {len(only_render)} reference(s) the workbook does "
            f"not: {', '.join(only_render[:20])}"
            + (" …" if len(only_render) > 20 else "")
            + ". Excel stores an item number as a number and drops its trailing zero, so a "
              "reference present in the render and absent from the workbook is usually a "
              "corrupted key rather than a missing item."
        )
    if only_book:
        notes.append(
            f"the workbook carries {len(only_book)} reference(s) the PDF render does not: "
            f"{', '.join(only_book[:20])}" + (" …" if len(only_book) > 20 else "")
            + ". Same bill, different reference sets — one of the two files is wrong about an "
              "item's identity, and nothing here decides which."
        )
    if not notes:
        notes.append(f"the workbook and the PDF render agree on all {len(book)} item reference(s).")
    return notes


def _ref_sort(ref: str):
    """Numeric where it can be, textual where it cannot. Only for readable note ordering."""
    parts = str(ref).split(".", 1)
    try:
        return (0, int(parts[0]), float(f"0.{parts[1]}") if len(parts) > 1 else 0.0, str(ref))
    except ValueError:
        return (1, 0, 0.0, str(ref))


def item_ref_of(cell, bill: str, on_note: Note = None) -> str:
    """The printed item reference, recovering the trailing zero Excel discarded.

    Item numbers cannot be trusted as parsed. Stored as Excel NUMBERS they lose trailing zeros —
    ``1.20`` reads back as ``1.2``, ``2.10`` as ``2.1``, ``3.10`` as ``3.1``. The cell's own number
    format is the evidence: ``0.00`` means two decimals were printed, so ``1.2`` is rendered back
    to ``1.20``. A cell stored as TEXT is taken verbatim and needs no recovery.

    Nothing is repaired silently. A reference that does not belong to the sheet it is on — the real
    file contains a live typo, ``2.244`` where ``2.24`` was meant — is REPORTED and kept as printed.
    """
    raw = cell.value
    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw.strip()
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        fmt = str(getattr(cell, "number_format", "") or "")
        decimals = len(fmt.split(".", 1)[1]) if "." in fmt and fmt.split(".", 1)[1].isdigit() else 0
        ref = f"{float(raw):.{decimals}f}" if decimals else f"{raw:g}"
        head = ref.split(".", 1)[0]
        if bill and head != bill and on_note:
            on_note(
                f"bill {bill}: item {ref!r} does not belong to this bill by its own numbering. "
                "Kept exactly as printed — the source may carry a typo, and repairing a reference "
                "silently is how a priced row ends up under the wrong bill."
            )
        return ref
    return _text(raw)


def _heading_level(row) -> Optional[tuple[int, str]]:
    """``(column, text)`` for a heading row — text in a description column with no item ref.

    THE HEADING CHAIN IS THE COLUMN. A string in B is a parent of a string in C, which is a parent
    of one in D. This is a fact about the file, where the render's indentation is a reading of it.
    """
    for col in _COL_DESC:
        text = _text(row[col - 1].value)
        if text:
            return col, text
    return None


def read_bill_sheet(sheet, on_note: Note = None) -> tuple[list[SorItem], str]:
    """Every priced row of one bill sheet, with its heading chain. Returns ``(items, bill)``."""
    m = _BILL_SHEET.match(sheet.title or "")
    bill = m.group(1).lstrip("0") or m.group(1) if m else ""
    items: list[SorItem] = []
    stack: list[tuple[int, str]] = []          # (column, heading), outermost first
    # The reference above this one, within THIS sheet. A bill numbers its items in order, so it is
    # what tells a dropped trailing zero from an ordinary step. Per sheet, never across bills.
    last_ref = ""

    for row in sheet.iter_rows(min_col=1, max_col=_COL_AMOUNT):
        cells = list(row)
        joined = " ".join(_text(c.value) for c in cells).strip()
        if not joined:
            continue
        if _FURNITURE.match(joined) or any(
            _FURNITURE.match(_text(c.value)) for c in cells[:4] if _text(c.value)
        ):
            continue

        ref_cell = cells[_COL_REF - 1]
        ref = item_ref_of(ref_cell, bill, on_note)
        if ref:
            # The number format is the FIRST evidence and the sequence is the second. Both are
            # needed: on the real pack the format says nothing and only the order does.
            ref, zero_note = restore_dropped_zero(
                ref, last_ref,
                from_number=isinstance(ref_cell.value, (int, float))
                and not isinstance(ref_cell.value, bool),
            )
            if zero_note and on_note:
                on_note(f"bill {bill}: {zero_note}" if bill else zero_note)
            last_ref = ref
        if not ref:
            heading = _heading_level(cells)
            if heading:
                col, text = heading
                # A heading closes every open heading at or right of its own column — `Recording`
                # is a SIBLING of `Instrument Installation`, not a child of it.
                while stack and stack[-1][0] >= col:
                    stack.pop()
                stack.append((col, text))
            continue

        description = next(
            (_text(cells[c - 1].value) for c in _COL_DESC if _text(cells[c - 1].value)), ""
        )
        rate_cell = cells[_COL_RATE - 1]
        amount = _text(cells[_COL_AMOUNT - 1].value)
        rate_text = _text(rate_cell.value)
        items.append(SorItem(
            item_ref=ref,
            description=description or None,
            unit=_text(cells[_COL_UNIT - 1].value) or None,
            qty=_number(cells[_COL_QTY - 1].value),
            section=bill or None,
            heading_path=[text for _col, text in stack],
            # `=G38` is a lump sum; `=E8*G8` is quantity × rate. Both are blank in a render.
            is_lump_sum=_is_lump_sum(amount),
            # A rate the tender ARRIVED with is the Employer's, and must never be overwritten by a
            # generated one. `-` is "not rated", which is a different statement from "no rate yet".
            employer_rate=None if rate_text in _NOT_RATED else _number(rate_cell.value),
        ))
    return items, bill


_LUMP_SUM_RE = re.compile(r"^\s*=\s*\$?[A-Z]{1,2}\$?\d+\s*$")
_QTY_RATE_RE = re.compile(r"^\s*=\s*\$?[A-Z]{1,2}\$?\d+\s*\*\s*\$?[A-Z]{1,2}\$?\d+")


def _is_lump_sum(amount_formula: str) -> bool:
    """``=G38`` is a lump sum; ``=E8*G8`` is quantity × rate.

    A cached VALUE tells us nothing — both are just numbers — which is why the workbook must be
    read with formulas intact and why a render can never establish this.
    """
    if not amount_formula.startswith("="):
        return False
    if _QTY_RATE_RE.match(amount_formula):
        return False
    return bool(_LUMP_SUM_RE.match(amount_formula))


def read_workbook(data: bytes, on_note: Note = None) -> WorkbookBill:
    """Every priced row of every bill sheet in one workbook. No model call, no chunking.

    Read with ``data_only=False`` so formulas survive: quantities and Employer rates are literals
    and come back as numbers either way, but ``is_lump_sum`` exists only in the formula.
    """
    import io

    import openpyxl  # lazy — a PDF-only run never loads it

    out = WorkbookBill()
    book = openpyxl.load_workbook(io.BytesIO(data), data_only=False, read_only=False)
    try:
        for sheet in book.worksheets:
            title = sheet.title or ""
            if _SKIP_SHEETS.match(title) or not _BILL_SHEET.match(title):
                out.sheets_skipped.append(title)
                continue
            note = on_note or out.notes.append
            items, bill = read_bill_sheet(sheet, note)
            _report_duplicate_refs(items, bill or title, note)
            out.sheets_read.append(title)
            out.per_bill[bill or title] = len(items)
            out.items.extend(items)
    finally:
        book.close()

    if out.sheets_skipped:
        (on_note or out.notes.append)(
            f"{len(out.sheets_skipped)} sheet(s) carry no priced rows and were not read: "
            + ", ".join(repr(s) for s in out.sheets_skipped[:8])
        )
    return out


def _report_duplicate_refs(items: list[SorItem], bill: str, on_note: Note) -> None:
    """Say so when one bill carries the same reference twice.

    This is the trailing-zero problem at its irreducible worst. `1.1` and `1.10` stored as Excel
    NUMBERS are the same number — no format string recovers the difference, because there is no
    difference left in the file. Two distinct priced rows arrive indistinguishable, and neither the
    reader nor anything downstream can tell which is which.

    So it is REPORTED and both rows are kept. Silently dropping one would lose a priced item;
    silently renaming one would invent a reference the tender does not contain. Whoever prices this
    bill has to open the workbook and look.
    """
    if on_note is None:
        return
    seen: dict[str, int] = {}
    for item in items:
        seen[item.item_ref] = seen.get(item.item_ref, 0) + 1
    dupes = sorted(ref for ref, n in seen.items() if n > 1)
    if dupes:
        on_note(
            f"bill {bill}: {len(dupes)} reference(s) appear more than once — "
            + ", ".join(repr(d) for d in dupes[:8])
            + ". Stored as Excel numbers, `1.1` and `1.10` are the SAME number, so this cannot be "
            "reconciled from the file. Every row is kept; the bill needs a human eye."
        )


def is_workbook(filename: str) -> bool:
    return filename.lower().rsplit(".", 1)[-1] in ("xlsx", "xlsm", "xls")
