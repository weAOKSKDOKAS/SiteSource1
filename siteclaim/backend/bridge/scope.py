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
import sqlite3
from pathlib import Path
from typing import Callable, Optional

from pipeline.stage_01_ingest.doc_index import (
    UnrecognisedItem,
    build_doc_index,
    quarantine_unrecognised_items,
)
from pipeline.stage_01_ingest.ingest import ingest_tender
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


def _apply_quarantine(
    scope: ScopePackages, bill: list, on_error: Optional[Callable[[str], None]] = None,
) -> tuple[ScopePackages, list[UnrecognisedItem]]:
    """The provenance backstop, on the same terms ``/ingest-upload`` uses.

    Index the confirmed bill parts structurally; when at least one declared its OWN section
    headers, drop any extracted item whose section is not among them — surfaced, never routed.
    With no headers to check against, skip the guard rather than block a legitimate split.
    """
    docs: list[tuple[str, DocType, bytes]] = []
    for spec, pdf_path, _context in bill:
        data = _part_bytes(pdf_path)
        if data is not None:
            docs.append((_label(spec), BILL_DOC_TYPE, data))
    if not docs:
        return scope, []

    entries = build_doc_index(docs)
    sr_sections = {c for e in entries if e.kind == "schedule_of_rates" for c in e.sor_section_pages}
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
) -> tuple[ScopePackages, list[UnrecognisedItem]]:
    """Split a client_boq set's confirmed bill into ``ScopePackages`` — one package per trade.

    Raises ``LookupError`` when the set has no parts and ``ValueError`` when no bill part has been
    confirmed. It never guesses which part is the bill: that is the Phase-3 gate, and guessing
    here would defeat it.
    """
    from bridge import parts as parts_mod
    from bridge.identity import bridge_conn, register_set_on, run_ref_for
    from client_boq import store as cb_store

    ref = run_ref_for(set_id)
    conn = bridge_conn()
    try:
        parts = cb_store.load_parts(conn, ref)
        if not parts:
            raise LookupError(f"No parts found for set {ref!r} — ingest the set first.")
        bill_ids = set(parts_mod.confirmed_bill_parts(conn, ref))
        if not bill_ids:
            raise ValueError(
                f"No bill part confirmed for set {ref!r} — POST /bridge/{ref}/bq-part first. "
                "The priced bill is a human decision; this will not guess it."
            )
        name = _project_name(conn, ref)
        register_set_on(conn, ref, name=name)
    finally:
        conn.close()

    bill = [t for t in parts if t[0].part_id in bill_ids]
    context = [t for t in parts if t[0].part_id not in bill_ids]

    doc_text = doc_text_from_parts(bill, on_error)
    if not doc_text.strip():
        raise ValueError(
            f"The confirmed bill part(s) for set {ref!r} produced no readable text, so there is "
            "nothing to split. Check the parts are cut and carry a text layer."
        )
    context_text = context_text_from_cards(context, on_error)

    scope = ingest_tender(
        _tender_for(name, parts, bill_ids),
        demo_fixture=demo_fixture,
        client=client,
        doc_text=doc_text,
        context_text=context_text,
        on_error=on_error,
    )
    return _apply_quarantine(scope, bill, on_error)


def _project_name(conn: sqlite3.Connection, set_id: str) -> str:
    from bridge.identity import set_name

    return set_name(conn, set_id) or set_id
