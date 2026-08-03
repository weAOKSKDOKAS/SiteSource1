"""Selecting the bill part(s) from a client_boq set — a human gate, never automatic.

``PartSpec.category`` is written by an AI interpretation stage. Letting it silently decide which
document produces every priced row in a tender is exactly the class of thing this codebase gates,
so the bridge PROPOSES and a human CONFIRMS.

The confirmation is a **set** of part ids, not one: a real tender can carry a bill of quantities
AND a separate daywork or provisional-items schedule, and both are priceable (``PART_CATEGORIES``
defines ``pricing`` as "bills of quantities, schedules of rates, fee proposals" — a family). Every
confirmed part yields items; every unconfirmed part — including a ``pricing`` part the human left
out — becomes context only.

The confirmation lives in a table in THIS package, keyed by ``set_id``. No column is added to any
``client_boq_*`` table.
"""

from __future__ import annotations

import sqlite3


def ensure_tables(conn: sqlite3.Connection) -> None:
    """Create the bridge's bill-part table if absent (lazy DDL, idempotent).

    Will create ``bridge_bill_parts(set_id, part_id, ...)`` with a UNIQUE constraint on
    ``(set_id, part_id)`` — the constraint is there from the start, so a re-confirmation
    updates rather than duplicating.
    """
    raise NotImplementedError(
        "ensure_tables: CREATE TABLE IF NOT EXISTS bridge_bill_parts, UNIQUE(set_id, part_id)"
    )


def bq_candidates(set_id: str) -> dict:
    """Every part in the set with what a human needs to choose the bill, and what is proposed.

    Will return, per part: ``part_id``, ``title``, ``category``, ``pages``, ``scanned``, plus
    ``proposed`` (category == ``pricing``) and ``confirmed`` (already chosen). Degrades honestly:
    when no part is ``pricing`` the full list comes back with nothing proposed and a message
    saying so — it never guesses by title.
    """
    raise NotImplementedError(
        "bq_candidates: list every part with category/pages/scanned, propose the pricing parts"
    )


def confirm_bill_parts(set_id: str, part_ids: list[str]) -> dict:
    """Record the human's chosen SET of bill parts for ``set_id`` and return the stored state.

    Will reject a part id that is not in the set (never store a phantom part) and reject an
    empty selection at the caller's discretion, replacing any previous confirmation.
    """
    raise NotImplementedError(
        "confirm_bill_parts: validate every id against the set's real parts, then persist the set"
    )


def confirmed_bill_parts(conn: sqlite3.Connection, set_id: str) -> list[str]:
    """The confirmed bill ``part_id``s for ``set_id``, in document order — empty when unconfirmed."""
    raise NotImplementedError(
        "confirmed_bill_parts: read the persisted bill-part ids for a set, in document order"
    )
