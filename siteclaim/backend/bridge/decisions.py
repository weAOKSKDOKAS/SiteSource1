"""Route decisions recorded against a client_boq set — and deliberately NOTHING seeded.

The procurement ``/route/confirm`` seeds one ``estimate_projects`` row per self-perform package.
That is the wrong destination for a client_boq tender: ``client_boq_estimates`` has ``set_id`` as
its PRIMARY KEY — one estimate per tender — and that is correct. A main contractor submits ONE
priced bill with a single tendered total; every item is priced. The route decision does not change
which items appear in the submission, only where each item's rate comes from (own build-up vs a
subcontractor's quote). Seeding N estimates would create N documents where the tender needs one.

So the bridge's confirm persists decisions and seeds nothing. It also never calls the procurement
``/route/confirm``: that endpoint only seeds when a ``scope`` is supplied, so the standalone
procurement path keeps working untouched and no edit to ``api.py`` is needed.

Decisions live in a table in THIS package, keyed by ``(set_id, package_key)``.
"""

from __future__ import annotations

import sqlite3


def ensure_tables(conn: sqlite3.Connection) -> None:
    """Create the bridge's route-decision table if absent (lazy DDL, idempotent).

    Will create ``bridge_route_decisions(set_id, package_key, chosen_route, ...)`` with a UNIQUE
    constraint on ``(set_id, package_key)`` from the start, so re-deciding updates in place.
    """
    raise NotImplementedError(
        "ensure_tables: CREATE TABLE IF NOT EXISTS bridge_route_decisions, UNIQUE(set_id, package_key)"
    )


def confirm_routes(set_id: str, decisions: dict[str, str], *, decided_by: str = "operator") -> dict:
    """Record the human's route per package for ``set_id`` and return the self-perform/sublet split.

    Will validate every route against ``schemas.routing.ROUTES`` before writing anything, persist
    by ``(set_id, package_key)``, and seed NO estimate on either side.
    """
    raise NotImplementedError(
        "confirm_routes: validate against ROUTES, persist by (set_id, package_key), seed nothing"
    )


def load_decisions(conn: sqlite3.Connection, set_id: str) -> list[dict]:
    """Every persisted route decision for ``set_id``, in package order."""
    raise NotImplementedError("load_decisions: read the persisted route decisions for a set")
