"""The confirmed bill part(s) -> ``ScopePackages``, via the EXISTING ``ingest_tender``.

The core of the join. Three things it does that a naive call would not:

1. **Reads each part from its OWN pdf** (the ``client_boq/review/s01_ingest.py::ingest_from_parts``
   pattern), so ``extract_document``'s 200-page cap applies per part rather than per binder — a
   411-page binder no longer loses half its pages.
2. **Builds ``context_text`` from the interpreted ``PartContext`` cards**, not from raw part text.
   ``_CONTEXT_MAX_CHARS`` is 6000 and is applied as a hard truncation, so joining raw text would
   let part 1 and a fragment of part 2 survive while the other ten were silently discarded — worse
   than what ``/ingest-upload`` does, not better. The cards (title, category, summary, key points)
   are denser and more relevant, and a dozen fit comfortably. A part whose card says ``readable``
   is false is skipped and REPORTED, never passed as an empty card.
3. **Keeps the provenance backstop**: the same ``quarantine_unrecognised_items`` guard
   ``/ingest-upload`` uses, so the bridge never ships weaker than the existing path.

``doc_text`` is assembled exactly as ``api.py:732`` does —
``"\\n\\n".join(f"=== {label} ===\\n{text}")`` — so extraction sees the shape it already expects.

Only human-confirmed parts become ``SCHEDULE_OF_RATES`` and so only they yield priced items. That
is what preserves the anti-phantom-item invariant here: not a count of how many parts are priced,
but the gate that a person chose them.
"""

from __future__ import annotations

import datetime as _dt
import json
import re
import sqlite3
from pathlib import Path
from typing import Callable, Optional

from pipeline.stage_01_ingest.doc_index import (
    UnrecognisedItem,
    apply_ps_index_titles,
    build_doc_entry,
    quarantine_unrecognised_items,
    save_doc_index,
)
from pipeline.stage_01_ingest.ingest import ingest_tender
from pipeline.workspace import Workspace
from schemas.models import DocType, ScopePackages, TenderDocument, TenderPackage

# Imported rather than repeated: if ingest ever changes its context budget, the warning below must
# move with it instead of quietly reporting against a stale number.
from pipeline.stage_01_ingest.ingest import _CONTEXT_MAX_CHARS

BILL_DOC_TYPE = DocType.SCHEDULE_OF_RATES
CATEGORY_DOC_TYPES = {
    # Only what the mapping actually needs; anything else is context, never priced.
    "specifications": DocType.PARTICULAR_SPECIFICATION,
}


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")


def _note(on_error: Optional[Callable[[str], None]], message: str) -> None:
    if on_error:
        on_error(message)


def doc_type_for(category: str, *, is_bill: bool) -> DocType:
    """The ``DocType`` a part carries into the split.

    A confirmed bill part is a ``SCHEDULE_OF_RATES`` — that is the whole point of the gate. Every
    other part is context: ``specifications`` maps to ``PARTICULAR_SPECIFICATION``, and anything
    else — including a category outside ``PART_CATEGORIES``, which is a plain unvalidated string —
    falls back to ``GENERAL`` rather than failing. An unknown category is not an error; it is just
    a document nobody classified.
    """
    if is_bill:
        return BILL_DOC_TYPE
    return CATEGORY_DOC_TYPES.get((category or "").strip().lower(), DocType.GENERAL)


def _label(spec) -> str:
    """The block label for a part — its title, falling back to its stable id."""
    return (spec.title or "").strip() or spec.part_id


def _part_bytes(pdf_path: str) -> Optional[bytes]:
    """The part's own cut pdf, or None when it has none on disk.

    ``pdf_path`` can legitimately be ``""`` (client_boq/store.py:649), and ``Path("")`` is
    ``Path('.')`` — truthy and a directory — so the raw string is tested before the file check,
    exactly as ``s01_ingest.py:115`` does.
    """
    if not pdf_path:
        return None
    path = Path(pdf_path)
    if not path.is_file():
        return None
    return path.read_bytes()


def _part_text(spec, pdf_path: str) -> str:
    """One part's text, read from its OWN pdf over pages 1..page_count().

    The cut per-part pdf is re-paginated from 1, so the range is the part's LENGTH, not its
    source-binder offsets — the ``ingest_from_parts`` contract. ``pdfops.page_text`` imposes no
    200-page cap, which is the entire reason for reading per part instead of per binder.
    """
    from client_boq.ingest import pdfops  # read-only import; local, to keep this module light

    data = _part_bytes(pdf_path)
    if data is None:
        return ""
    return pdfops.page_text(data, 1, spec.page_count())


def doc_text_from_parts(parts: list, on_error: Optional[Callable[[str], None]] = None) -> str:
    """The confirmed bill parts' text, joined in the ``=== label ===`` convention ``api.py`` uses.

    A bill part that yields no text is reported, not silently skipped: a scanned bill with no text
    layer is the difference between "this tender has no items" and "we could not read it".
    """
    blocks: list[str] = []
    for spec, pdf_path, _context in parts:
        text = _part_text(spec, pdf_path)
        if not text.strip():
            reason = (
                "no cut pdf on disk" if not _part_bytes(pdf_path)
                else "no text layer (scanned)" if spec.scanned else "empty text layer"
            )
            _note(on_error, (
                f"bill part {_label(spec)!r} ({spec.part_id}) produced no text — {reason}; it "
                "contributes NO priced items to this split"
            ))
            continue
        blocks.append(f"=== {_label(spec)} ===\n{text}")
    return "\n\n".join(blocks)


def context_text_from_cards(parts: list, on_error: Optional[Callable[[str], None]] = None) -> str:
    """Compact ``context_text`` built from each non-bill part's ``PartContext`` card.

    One block per part — title, category, summary, key points. This exists because the alternative,
    joining raw part text, meets a 6000-char hard truncation: on a twelve-part tender part 1 and a
    fragment of part 2 would survive and the other ten would vanish without a word.
    """
    blocks: list[str] = []
    for spec, _pdf_path, context in parts:
        label, category = _label(spec), (spec.category or "other")
        if context is not None and not context.readable:
            _note(on_error, (
                f"context part {label!r} ({spec.part_id}) is marked unreadable — skipped rather "
                "than passed as an empty card; it informs the trade split not at all"
            ))
            continue
        summary = (getattr(context, "summary", "") or "").strip()
        key_points = [p.strip() for p in (getattr(context, "key_points", None) or []) if p.strip()]
        if not summary and not key_points:
            _note(on_error, (
                f"context part {label!r} ({spec.part_id}) has no interpreted card — only its title "
                "and category inform the trade split"
            ))
        lines = [f"=== {label} ({category}) ==="]
        if summary:
            lines.append(summary)
        lines += [f"- {point}" for point in key_points]
        blocks.append("\n".join(lines))

    text = "\n\n".join(blocks)
    if len(text) > _CONTEXT_MAX_CHARS:
        # ingest truncates hard. It is allowed to — but it must not do so silently here.
        _note(on_error, (
            f"context cards total {len(text)} chars and will be truncated to {_CONTEXT_MAX_CHARS} "
            f"by the split — {len(text) - _CONTEXT_MAX_CHARS} chars of later parts' context are "
            "dropped; the priced items are unaffected"
        ))
    return text


def _tender_for(name: str, parts: list, bill_ids: set[str]) -> TenderPackage:
    """The ``TenderPackage`` handed to ``ingest_tender`` — its ``documents`` name each part and
    carry the DocType mapping (used for the prompt preamble and the structural doc index)."""
    return TenderPackage(
        project_name=name,
        description="",
        documents=[
            TenderDocument(
                doc_type=doc_type_for(spec.category, is_bill=spec.part_id in bill_ids),
                filename=_label(spec),
            )
            for spec, _p, _c in parts
        ],
    )


# Categories whose parts nothing downstream reads, and which are the most expensive to index.
#
# `relevant_docs` attaches exactly five kinds — clarification, general_specification,
# method_of_measurement, particular_specification, appendix — plus the priced-return SoR. A
# DRAWING is none of them: it is raster, so every page goes through the OCR/word-box path at
# roughly 150-200 ms even with no OCR engine installed and 1-3 s with one, and nothing would ever
# read the result. On ND/2025/04 that is 35 of 206 parts, and the most costly 35.
#
# Skipping them is not a guess about content — it is declining to index what no consumer reads.
_NEVER_INDEXED = {"drawings"}


def _index_each(
    docs: list, count_cb: Optional[Callable[[int, int], None]], done: int, total: int,
) -> tuple[list, int]:
    """``build_doc_index`` one document at a time, ticking after each. Returns ``(entries, done)``.

    Same entries in the same order — ``build_doc_index`` is a list comprehension over
    ``build_doc_entry`` and carries no cross-document state, so per-document is not a different
    reading of the pack, only a slower-looking one.

    The tick is the reason. Indexing ~170 parts took minutes with nothing to show for it, and a
    document is the only boundary this loop has. ``count_cb`` MAY RAISE — that is how a cancel
    takes effect here, at a part boundary, exactly as a stage callback stops a workflow between
    stages. Nothing is left half-written: the index is only persisted once the whole loop is past.
    """
    entries = []
    for name, doc_type, data, source_path in docs:
        # `source_path` is the whole of the fix for the empty draft: this index names a document by
        # the PART'S TITLE ("Schedule of Rates"), and no such file exists in the workspace's
        # `docs/`. `assemble_firm_attachments` looked there, found nothing, and skipped every
        # attachment in silence — while the preview, which reads this index and never touches disk,
        # showed the full set. Recording where the bytes actually are costs one string per part.
        entries.append(build_doc_entry(name, doc_type, data, source_path))
        done += 1
        if count_cb:
            count_cb(done, total)
    return entries, done


def _apply_quarantine(
    scope: ScopePackages, bill: list, on_error: Optional[Callable[[str], None]] = None,
    *, tender_id: str = "", context: Optional[list] = None,
    count_cb: Optional[Callable[[int, int], None]] = None,
) -> tuple[ScopePackages, list[UnrecognisedItem]]:
    """The provenance backstop, on the same terms ``/ingest-upload`` uses.

    Index the confirmed bill parts structurally; when at least one declared its OWN section
    headers, drop any extracted item whose section is not among them — surfaced, never routed.
    With no headers to check against, skip the guard rather than block a legitimate split.

    **And PERSIST that index**, which is FIX 10. It was built here, read for ``sor_section_pages``,
    and thrown away — while ``save_doc_index`` had exactly one call site in the whole codebase
    (``api.py``'s ``/ingest-upload``). So a tender that entered through the archive/bridge path
    never had a ``doc_index.json``, ``drafts.load_doc_index`` returned ``[]`` for it, and
    ``relevant_docs``' ``if not sr_entries`` fired UNCONDITIONALLY — regardless of whether the
    bill was a PDF or a workbook.

    That is the real root cause of the generated-sheet substitution, and my FIX 9 diagnosis (the
    workbook) was wrong: the workbook was present and irrelevant. The pack ships BOTH
    ``E-ND_2025_04_BQ-0.xlsx`` and ``I-ND_2025_04_BQ-0.pdf``, and the PDF would have been discarded
    just the same.

    The slug matches by construction: ``doc_index_path`` resolves through
    ``Workspace.tender_dir`` -> ``root / tender_slug(tender_id)``, ``tender_slug`` is idempotent,
    and ``set_id == run_ref == tender_slug(name)`` — so writing under ``ref`` here and loading
    under ``scope.project_name`` there reach the same file.
    """
    docs: list[tuple[str, DocType, bytes, str]] = []
    for spec, pdf_path, _context in bill:
        data = _part_bytes(pdf_path)
        if data is not None:
            docs.append((_label(spec), BILL_DOC_TYPE, data, str(Path(pdf_path).resolve())))
    if not docs:
        # Nothing readable to index. Notably the workbook-only split arrives here with `bill=[]`,
        # and correctly writes no index: a workbook has no pages and yields no section spans.
        return scope, []

    # The CONTEXT parts, indexed for dispatch. `relevant_docs` iterates the persisted doc_index for
    # every kind it attaches, so a bill-only index means an enquiry carries a Schedule of Rates and
    # nothing else — no Particular Specification, no Method of Measurement, no General
    # Specification, no addendum. That was the observed one-attachment draft.
    #
    # Collected BEFORE the bill is indexed so the total is known from the first tick: a progress
    # bar that discovers its own denominator halfway through is worse than none.
    context_docs: list[tuple[str, DocType, bytes, str]] = []
    for spec, pdf_path, _ctx in (context or []):
        category = (spec.category or "").strip().lower()
        if category in _NEVER_INDEXED:
            continue
        data = _part_bytes(pdf_path)
        if data is not None:
            context_docs.append((_label(spec), doc_type_for(category, is_bill=False), data,
                                 str(Path(pdf_path).resolve())))

    total = len(docs) + len(context_docs)
    bill_entries, done = _index_each(docs, count_cb, 0, total)
    # The GUARD reads the BILL only. A context part misclassified as a schedule of rates would
    # otherwise contribute section codes the bill never declared, and the quarantine would start
    # accepting items on another document's authority.
    sr_sections = {c for e in bill_entries if e.kind == "schedule_of_rates" for c in e.sor_section_pages}

    context_entries, _done = _index_each(context_docs, count_cb, done, total)
    # The PS index names every specification section; a section that declares no title of its own
    # takes it from there. A CROSS-DOCUMENT pass, so it runs once over the whole set rather than
    # inside `_index_each` — `build_doc_index` does the same for the upload path.
    all_entries = apply_ps_index_titles(bill_entries + context_entries)
    if tender_id:
        save_doc_index(Workspace(), tender_id, all_entries)
    if on_error and context_docs:
        kinds: dict[str, int] = {}
        for e in context_entries:
            kinds[e.kind] = kinds.get(e.kind, 0) + 1
        _note(on_error, (
            f"indexed {len(context_docs)} context document(s) for dispatch — "
            + (", ".join(f"{n} {k}" for k, n in sorted(kinds.items())) or "none classified")
            + ". The enquiry's relevant-only attachments are assembled from this index."
        ))
    if not sr_sections:
        _note(on_error, (
            "the confirmed bill declared no Schedule-of-Rates section headers, so the provenance "
            "guard was skipped for this split (nothing to check an item's section against)"
        ))
        return scope, []

    scope, unrecognised = quarantine_unrecognised_items(scope, sr_sections)
    for item in unrecognised:
        _note(on_error, (
            f"item {item.item_ref!r} — {item.reason} (SoR sections {sorted(sr_sections)}); "
            "quarantined, not routed"
        ))
    return scope, unrecognised


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------
def ensure_tables(conn: sqlite3.Connection) -> None:
    """Create the bridge's scope table if absent (lazy DDL, idempotent)."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS bridge_scopes (
            set_id TEXT PRIMARY KEY,
            scope_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        """
    )
    conn.commit()


def save_scope_on(conn: sqlite3.Connection, set_id: str, scope: ScopePackages) -> None:
    ensure_tables(conn)
    conn.execute(
        "INSERT INTO bridge_scopes (set_id, scope_json, created_at) VALUES (?, ?, ?) "
        "ON CONFLICT(set_id) DO UPDATE SET scope_json = excluded.scope_json, "
        "created_at = excluded.created_at",
        (set_id, scope.model_dump_json(), _now()),
    )
    conn.commit()


def load_scope_on(conn: sqlite3.Connection, set_id: str) -> Optional[ScopePackages]:
    ensure_tables(conn)
    row = conn.execute(
        "SELECT scope_json FROM bridge_scopes WHERE set_id = ?", (set_id,)
    ).fetchone()
    if not row or not row["scope_json"]:
        return None
    try:
        return ScopePackages.model_validate_json(row["scope_json"])
    except (ValueError, json.JSONDecodeError):
        return None


def save_scope(set_id: str, scope: ScopePackages) -> None:
    """Persist the split for ``set_id`` so the routing gate can read it back."""
    from bridge.identity import bridge_conn, run_ref_for

    conn = bridge_conn()
    try:
        save_scope_on(conn, run_ref_for(set_id), scope)
    finally:
        conn.close()


def load_scope(set_id: str) -> Optional[ScopePackages]:
    """The persisted split for ``set_id``, or None when it has not been run."""
    from bridge.identity import bridge_conn, run_ref_for

    conn = bridge_conn()
    try:
        return load_scope_on(conn, run_ref_for(set_id))
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# The split
# ---------------------------------------------------------------------------
def scope_from_set(
    set_id: str,
    *,
    on_error: Optional[Callable[[str], None]] = None,
    client=None,
    demo_fixture: Optional[str] = None,
    progress_cb: Optional[Callable[[str], None]] = None,
    count_cb: Optional[Callable[[int, int], None]] = None,
    extract_cb: Optional[Callable[[int, int], None]] = None,
) -> tuple[ScopePackages, list[UnrecognisedItem]]:
    """Split a client_boq set's confirmed bill into ``ScopePackages`` — one package per trade.

    Raises ``LookupError`` when the set has no parts and ``ValueError`` when no bill part has been
    confirmed. It never guesses which part is the bill: that is the Phase-3 gate, and guessing
    here would defeat it.

    Three job hooks, all optional, all called directly with no import of the job store — this
    module still knows nothing about jobs:

    * ``progress_cb(stage)`` — the stage name. MAY RAISE (a cancel at a stage boundary).
    * ``count_cb(done, total)`` — DOCUMENTS INDEXED, in the ``indexing`` loop. MAY RAISE: that loop
      is plain and sequential, so stopping it genuinely saves the remainder.
    * ``extract_cb(done, total)`` — EXTRACTION UNITS, in the long ``splitting`` phase. Its own
      parameter rather than a second use of ``count_cb``, because the two count different
      populations against different denominators, and a caller reading document progress must not
      silently start receiving chunk progress on the same channel. **Reporting only — do not raise
      here.** `run_calls` submits every unit to one `pool.map`, whose context manager waits for
      every future regardless, so raising would stop nothing and would report a cancel after a
      full-price run.
    """
    from bridge import parts as parts_mod
    from bridge.identity import bridge_conn, register_set_on, run_ref_for
    from client_boq import store as cb_store

    def _stage(name: str) -> None:
        if progress_cb:
            progress_cb(name)

    _stage("reading")
    ref = run_ref_for(set_id)
    conn = bridge_conn()
    try:
        parts = cb_store.load_parts(conn, ref)
        if not parts:
            raise LookupError(
                "No parts found for this tender — upload its documents first.")
        bill_ids = set(parts_mod.confirmed_bill_parts(conn, ref))
        if not bill_ids:
            raise ValueError(
                "No document has been confirmed as the priced bill yet — choose it on the Route "
                "tab first. The priced bill is a human decision; this will not guess it."
            )
        name = _project_name(conn, ref)
        register_set_on(conn, ref, name=name)
    finally:
        conn.close()

    bill = [t for t in parts if t[0].part_id in bill_ids]
    context = [t for t in parts if t[0].part_id not in bill_ids]

    # A confirmed bill that is a WORKBOOK is read deterministically — no model call, no chunking,
    # and the three facts a render cannot carry. Everything else goes down the PDF path unchanged.
    workbook_items, bill = _read_confirmed_workbooks(bill, name, on_error)
    if workbook_items and not bill:
        # Every confirmed bill was a workbook: the split is complete without the extractor.
        scope = _scope_from_items(workbook_items, name)
        _stage("indexing")
        return _apply_quarantine(scope, [], on_error, tender_id=ref, count_cb=count_cb)

    _stage("splitting")
    doc_text = doc_text_from_parts(bill, on_error)
    if not doc_text.strip() and not workbook_items:
        raise ValueError(
            "The confirmed bill part(s) produced no readable text, so there is nothing to "
            "split. Check the parts are cut and carry a text layer."
        )
    context_text = context_text_from_cards(context, on_error)

    scope = ingest_tender(
        _tender_for(name, parts, bill_ids),
        demo_fixture=demo_fixture,
        client=client,
        doc_text=doc_text,
        context_text=context_text,
        on_error=on_error,
        # THE 199 SECONDS. This is the long phase — the bill is chunked and each chunk extracted —
        # and `ingest_tender` has counted its units all along; nothing was reading them. Live, the
        # strip sat on `splitting` with 0/0 for the whole run, which is indistinguishable from a
        # hang. `progress_cb(0, total)` fires first so the DENOMINATOR is known from the start, then
        # once per unit ON COMPLETION.
        #
        # REPORTING ONLY — this one does not raise. The units are submitted to `run_calls` in one
        # `pool.map`, whose context manager waits for every future regardless, so raising here
        # would stop nothing and would report "stopped before indexing" after a full-price run.
        # The cancel that takes effect stays on the indexing loop below, where the work is a plain
        # sequential loop and stopping it genuinely saves the remainder.
        progress_cb=extract_cb,
    )
    if workbook_items:
        # Both kinds of bill were confirmed and neither shadowed the other. The workbook's items
        # come FIRST so its facts win the dedupe in `_merge_items` — a render cannot establish a
        # lump sum or an Employer rate, so a render's version of a row is strictly the poorer one.
        scope = _merge_items(workbook_items, scope, name)
    _stage("indexing")
    return _apply_quarantine(scope, bill, on_error, tender_id=ref, context=context,
                             count_cb=count_cb)


def _project_name(conn: sqlite3.Connection, set_id: str) -> str:
    from bridge.identity import set_name

    return set_name(conn, set_id) or set_id


# ---------------------------------------------------------------------------
# Workbook bills
# ---------------------------------------------------------------------------
_RENDERING_PREFIX = re.compile(r"^[a-z]-(?=.{4})")


def _bill_identity(filename: str) -> str:
    """What two files have to share to be the SAME bill in two renderings.

    **THE GUARD COULD NOT MATCH THE PACK IT WAS WRITTEN FOR.** It compared raw stems, and this
    issuer distinguishes the renderings by a one-letter prefix: `BQ/E-ND_2025_04_BQ-0.xlsx` is the
    workbook and `BQ/I-ND_2025_04_BQ-0.pdf` is its PDF render. `e-nd_2025_04_bq-0` and
    `i-nd_2025_04_bq-0` share no stem, so the guard never fired on the one pack it exists for: the
    same bill was read twice — once deterministically from the workbook and once by putting a
    26-page render through the extractor — and the second reading can establish neither a lump sum
    nor an Employer-fixed rate.

    Only a SINGLE letter followed by a hyphen is dropped, and only when four characters remain, so
    a bill genuinely named `A-something` is not collapsed onto `B-something`; anything longer is a
    name, not a rendering marker. A PDF sharing no identity with a workbook is a DIFFERENT bill and
    is read as normal — that behaviour is what this must not cost.
    """
    from pathlib import Path as _Path

    stem = _Path(filename or "").stem.lower()
    return _RENDERING_PREFIX.sub("", stem)


def _read_confirmed_workbooks(bill: list, name: str, on_error=None):
    """Read every confirmed bill part that is a workbook. Returns ``(items, remaining_pdf_parts)``.

    THE PACK CONTAINS BOTH. CEDD ND/2025/04 ships `BQ/E-ND_2025_04_BQ-0.xlsx` and a PDF render of
    the same bill, and pricing one bill twice is worse than reading it from the wrong one. So where
    a confirmed PDF shares its stem with a confirmed workbook, the WORKBOOK wins and the render is
    dropped from the split — reported, never silently. A render can establish neither a lump sum
    nor an Employer-fixed rate, so it is strictly the poorer source for the same rows.

    A PDF that shares no stem with any workbook is a DIFFERENT bill and is read as normal.
    """
    from pathlib import Path as _Path

    from pipeline.stage_01_ingest import workbook as wb

    books = [t for t in bill if wb.is_workbook(_label(t[0]) or t[1] or "")]
    if not books:
        return [], bill

    items = []
    stems = set()
    for spec, pdf_path, _ctx in books:
        label = _label(spec)
        stems.add(_bill_identity(label))
        data = _part_bytes(pdf_path)
        if data is None:
            _note(on_error, (
                f"bill part {label!r} ({spec.part_id}) is a workbook with no file on disk, so it "
                "contributes NO priced items to this split"
            ))
            continue
        try:
            read = wb.read_workbook(data, on_note=lambda m: _note(on_error, f"{label}: {m}"))
        except Exception as exc:  # noqa: BLE001 — an unreadable workbook is a gap, not a crash
            _note(on_error, (
                f"bill part {label!r} could not be read as a workbook ({exc}); it contributes no "
                "priced items. If it is really a PDF, re-confirm the PDF part instead."
            ))
            continue
        counts = ", ".join(f"bill {b}: {n}" for b, n in sorted(read.per_bill.items()))
        _note(on_error, (
            f"{label}: read deterministically from the workbook — {len(read.items)} priced "
            f"item(s) across {len(read.sheets_read)} bill sheet(s) ({counts}), with zero model "
            "calls."
        ))
        items.extend(read.items)

    remaining = []
    for spec, pdf_path, ctx in bill:
        label = _label(spec)
        if wb.is_workbook(label or pdf_path or ""):
            continue
        if _bill_identity(label) in stems:
            _note(on_error, (
                f"bill part {label!r} is a PDF render of a bill this set also carries as a "
                "workbook, so it was NOT read: pricing the same bill twice is worse than reading "
                "it from the wrong one, and a render can establish neither a lump sum nor an "
                "Employer-fixed rate."
            ))
            continue
        remaining.append((spec, pdf_path, ctx))
    return items, remaining


def _scope_from_items(items: list, name: str) -> ScopePackages:
    """The workbook's items as a `ScopePackages`, in the shape `ingest_tender` emits.

    One package, `ground_investigation` being wrong to assume, so the trade is left for the routing
    split to divide by section — the bill numbers are already on every item, and `route_units`
    splits by section exactly as it does for an extracted bill.
    """
    from pipeline.stage_01_ingest.ingest import annotate_sections
    from schemas.models import TradeWorkPackage

    scope = ScopePackages(project_name=name, packages=[TradeWorkPackage(
        trade="general_building", scope_summary=f"{len(items)} priced items read from the workbook",
        sor_items=items, source_refs=["the priced bill (workbook)"],
    )])
    return annotate_sections(scope, "")


def _merge_items(workbook_items: list, scope: ScopePackages, name: str) -> ScopePackages:
    """Add the workbook's items to an extracted scope, workbook winning on a shared ``item_ref``."""
    have = {it.item_ref for it in workbook_items}
    packages = []
    for pkg in scope.packages:
        kept = [it for it in pkg.sor_items if it.item_ref not in have]
        if kept:
            packages.append(pkg.model_copy(update={"sor_items": kept}))
    merged = _scope_from_items(workbook_items, name)
    return merged.model_copy(update={"packages": merged.packages + packages})
