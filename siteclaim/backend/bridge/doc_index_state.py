"""Is there a document index for THIS tender, and is it the one the split just built?

The last live failure was not a bug in any of the code below. The split ran under one tender slug
and the drafts were assembled under another, so `load_doc_index` returned `[]`, `relevant_docs`
took its `if not sr_entries` fallback, and the enquiry went out with a 7 KB generated workbook
where a sliced bill belonged. Every component behaved exactly as designed. The only symptom was
the attachment, and by then it had been sent.

So the index stops being an implicit precondition and becomes a stated one: the gate says whether
an index exists for the slug it is about to draft under, when it was built, and over how many
documents — before anything is composed.

The bridge is where this can be answered, because it is the one module that sees both sides: the
workspace file procurement reads, and the client_boq parts it was built from. Neither product
learns about the other to get it.
"""

from __future__ import annotations

import datetime as _dt
from typing import Optional


def _built_at(path) -> Optional[str]:
    """When the index was written, from the file's own mtime.

    The mtime rather than a field inside the file: `save_doc_index` writes a plain list and
    `load_doc_index` reads one, and adding a header would mean every reader learns a new shape to
    answer a question the filesystem already answers.
    """
    try:
        stamp = path.stat().st_mtime
    except OSError:
        return None
    return _dt.datetime.fromtimestamp(stamp, _dt.timezone.utc).isoformat(timespec="seconds")


def doc_index_state(set_id: str) -> dict:
    """What the dispatch gate needs to know about this tender's index, in one read.

    ``indexable_parts`` mirrors ``scope._apply_quarantine``'s own selection — the confirmed bill
    plus every context part that is not in ``_NEVER_INDEXED`` — so ``documents`` and it are the
    same population counted at two different times. That is what makes the comparison meaningful
    rather than two unrelated numbers next to each other.
    """
    from pipeline.stage_01_ingest.doc_index import (
        DOC_INDEX_READER_VERSION,
        index_read_error,
        index_reader_version,
        load_doc_index,
    )
    from pipeline.workspace import Workspace, tender_slug

    from bridge import parts as parts_mod
    from bridge.identity import bridge_conn, run_ref_for
    from bridge.scope import _NEVER_INDEXED

    ref = run_ref_for(set_id)
    workspace = Workspace()
    path = workspace.doc_index_path(ref)
    entries = load_doc_index(workspace, ref)

    kinds: dict[str, int] = {}
    for entry in entries:
        kinds[entry.kind] = kinds.get(entry.kind, 0) + 1
    sections = sorted({c for e in entries if e.kind == "schedule_of_rates"
                       for c in e.sor_section_pages})

    indexable = 0
    conn = bridge_conn()
    try:
        from client_boq import store as cb_store

        rows = cb_store.load_parts(conn, ref)
        bill_ids = set(parts_mod.confirmed_bill_parts(conn, ref))
        for spec, pdf_path, _ctx in rows:
            if not pdf_path:
                continue
            if spec.part_id in bill_ids:
                indexable += 1
            elif (spec.category or "").strip().lower() not in _NEVER_INDEXED:
                indexable += 1
    except Exception:  # noqa: BLE001 — a set this bridge does not know is not a failed read
        indexable = 0
    finally:
        conn.close()

    exists = path.is_file() and bool(entries)
    # STALE has TWO causes, and only one of them was reported.
    #
    # 1. Documents arrived after the index was built — an addendum, a re-upload, a part confirmed
    #    as the bill since. Fewer indexed than indexable is the only direction that costs an
    #    attachment; more is a part that has since been removed, which loses nothing.
    # 2. The index was built by an OLDER READER. Every recent fix changed what indexing produces —
    #    the PS section titles, the amendment lead-in that made SMM 28 index itself as 27, PS 1
    #    taking the Method-of-Measurement slot, the bill header read from its collection footer.
    #    An index written before them carries those wrong answers, and nothing said so: the gate
    #    reported `stale: false` on exactly the index whose PS was missing.
    #
    # Both are "re-run the split", so both set `stale` — and `stale_reason` says which, because the
    # remedy for one is uploading nothing and the remedy for the other is uploading nothing either,
    # but only one of them looks like a data problem.
    # ...and a THIRD state that is neither: the file is there and cannot be read. `load_doc_index`
    # degrades that to `[]`, which makes `exists` False and produces the "No document index for
    # this tender — run the split" sentence. The remedy happens to be right; the diagnosis is not,
    # and an operator who has just run the split reads it as the split having done nothing.
    unreadable = index_read_error(workspace, ref)
    written_by = index_reader_version(workspace, ref)
    outdated = exists and (written_by is None or written_by < DOC_INDEX_READER_VERSION)
    incomplete = exists and indexable > len(entries)
    stale = incomplete or outdated or bool(unreadable)
    reasons: list[str] = []
    if unreadable:
        reasons.append(f"the index file exists but could not be read ({unreadable}) — this says "
                       f"nothing about the pack; re-run the scope split to rebuild it")
    if incomplete:
        reasons.append(
            f"{indexable - len(entries)} document(s) have been added since this index was built")
    if outdated:
        reasons.append(
            f"this index was built by reader version {written_by if written_by is not None else 'unversioned'}, "
            f"and the current reader is version {DOC_INDEX_READER_VERSION} — document titles, "
            f"section numbers and kinds are decided at indexing time, so re-run the scope split to "
            f"pick up how documents are read now")
    return {
        "set_id": set_id,
        "tender_slug": tender_slug(ref),
        "exists": exists,
        "built_at": _built_at(path) if exists else None,
        "documents": len(entries),
        "indexable_parts": indexable,
        "kinds": kinds,
        "sor_sections": sections,
        "stale": stale,
        "stale_reason": "; ".join(reasons),
        "reader_version": written_by,
        "current_reader_version": DOC_INDEX_READER_VERSION,
        "unreadable": unreadable,
        "warning": _warning(exists, stale, len(entries), indexable, tender_slug(ref), reasons,
                            unreadable),
    }


def _warning(exists: bool, stale: bool, documents: int, indexable: int, slug: str,
             reasons: Optional[list] = None, unreadable: str = "") -> str:
    """The sentence the gate shows, or ``""`` when there is nothing to warn about.

    Written to name the slug. The failure this exists for was a slug mismatch, and a warning that
    says "no index" without saying which tender it looked under sends the reader to the same dead
    end the original failure did.
    """
    if unreadable:
        # Said BEFORE the no-index sentence, which would otherwise be the answer: an unreadable
        # index loads as `[]` and so looks exactly like a tender that was never split. The remedy
        # is the same re-split, but an operator who has just run one needs to know the file was
        # written and is damaged rather than that their split did nothing.
        return (f"The document index for {slug!r} EXISTS BUT IS UNREADABLE — {unreadable}. Nothing "
                f"can be sliced or attached from it, and its emptiness is a read failure, not a "
                f"statement about the pack. Re-run the scope split to rebuild it.")
    if not exists:
        return (
            f"No document index for {slug!r}. Every enquiry will carry the generated pricing sheet "
            "instead of the original bill sliced to its section, and no specification will be "
            "attached at all. Run the split for THIS tender first — an index built under a "
            "different slug is not visible here."
        )
    if stale:
        # Two causes, and they look identical from the outside. The documents-added sentence is
        # UNCHANGED — it is what the gate has always said and what a reader already recognises —
        # and the older-reader sentence is appended beside it, because only one of the two is about
        # documents at all and the remedy is the same for both.
        parts: list[str] = []
        if indexable > documents:
            parts.append(
                f"The index for {slug!r} covers {documents} document(s), but this set now has "
                f"{indexable} to index. Anything added since — an addendum, a re-upload — cannot be "
                "sliced or attached until the split is re-run.")
        if any("reader version" in r for r in (reasons or [])):
            parts.append(
                f"This index was also built by an OLDER READER: document titles, section numbers "
                f"and kinds are decided at indexing time, so it still carries whatever the code "
                f"understood when it ran. Re-run the scope split for {slug!r} to pick up how "
                f"documents are read now — otherwise a specification can be missing, or attached "
                f"under a stale title or the wrong section number."
                if not parts else
                f"It was also built by an OLDER READER, so its titles, section numbers and kinds "
                f"are whatever the code understood when it ran. The same re-split fixes both.")
        return " ".join(parts)
    return ""
