"""The confirmed bill part(s) -> ``ScopePackages``, via the EXISTING ``ingest_tender``.

The core of the join. Three things it does that a naive call would not:

1. **Reads each part from its OWN pdf** (the ``client_boq/review/s01_ingest.py::ingest_from_parts``
   pattern), so ``extract_document``'s 200-page cap applies per part rather than per binder — a
   411-page binder no longer loses half its pages.
2. **Builds ``context_text`` from the interpreted ``PartContext`` cards**, not from raw part text.
   ``_CONTEXT_MAX_CHARS`` is 6000 and is applied as a hard truncation, so joining raw text would
   let part 1 and a fragment of part 2 survive while the other ten are silently discarded. The
   cards (title, category, summary, key points) are denser and more relevant, and a dozen fit
   comfortably. An unreadable part is reported via ``on_error``, never passed as an empty card.
3. **Keeps the provenance backstop**: the same ``_quarantine_unrecognised_items`` guard the
   ``/ingest-upload`` path uses, so the bridge never ships weaker than the existing route.

``doc_text`` is assembled exactly as ``api.py`` does — ``"\\n\\n".join(f"=== {label} ===\\n{text}")``
— so extraction sees the shape it already expects.
"""

from __future__ import annotations

from typing import Callable, Optional

from schemas.models import ScopePackages


def context_text_from_cards(parts: list, on_error: Optional[Callable[[str], None]] = None) -> str:
    """Compact ``context_text`` built from each non-bill part's ``PartContext`` card.

    Will emit one block per part — title, category, summary, key points — skipping any part whose
    ``readable`` is false and reporting it through ``on_error`` rather than passing an empty card.
    """
    raise NotImplementedError(
        "context_text_from_cards: one compact block per part (title/category/summary/key points), "
        "skipping unreadable parts loudly via on_error"
    )


def doc_text_from_parts(parts: list, on_error: Optional[Callable[[str], None]] = None) -> str:
    """The confirmed bill parts' text, joined in the ``=== label ===`` convention ``api.py`` uses."""
    raise NotImplementedError(
        "doc_text_from_parts: read each confirmed part from its own pdf and join as '=== label ==='"
    )


def scope_from_set(
    set_id: str,
    *,
    on_error: Optional[Callable[[str], None]] = None,
) -> ScopePackages:
    """Split a client_boq set's confirmed bill into ``ScopePackages`` — one package per trade.

    Will: load parts (``store.load_parts``), find the confirmed bill parts (raising when there is
    no confirmation — never guessing), read those from their own pdfs as ``doc_text``, build
    ``context_text`` from the other parts' cards, call ``ingest_tender`` unmodified, then apply
    the promoted provenance quarantine over the bill parts' own section headers.
    """
    raise NotImplementedError(
        "scope_from_set: confirmed bill parts -> doc_text, other parts' cards -> context_text, "
        "ingest_tender, then quarantine items whose section is not in the bill's own headers"
    )


def save_scope(set_id: str, scope: ScopePackages) -> None:
    """Persist the split for ``set_id`` so the routing gate can read it back."""
    raise NotImplementedError("save_scope: persist the ScopePackages for a set")


def load_scope(set_id: str) -> Optional[ScopePackages]:
    """The persisted split for ``set_id``, or None when it has not been run."""
    raise NotImplementedError("load_scope: read back the persisted ScopePackages for a set")
