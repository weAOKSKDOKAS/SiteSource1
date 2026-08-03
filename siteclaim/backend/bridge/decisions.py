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

import datetime as _dt
import sqlite3
from typing import Callable, Optional

REVIEW_GATE_HINT = (
    "routing sits behind the review gate: you cannot decide self-perform vs sublet without knowing "
    "the contract terms, and you should not send an RFQ on terms nobody has read. Approve the "
    "review register (POST /client-boq/review/approve) first."
)


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")


def _note(on_error: Optional[Callable[[str], None]], message: str) -> None:
    if on_error:
        on_error(message)


class ReviewNotApproved(RuntimeError):
    """The client_boq review register for this set is not approved — the gate both forks inherit."""


def require_approved_review(conn: sqlite3.Connection, set_id: str) -> None:
    """Raise :class:`ReviewNotApproved` unless the set's review register is human-approved.

    Read-only: it asks client_boq's own ``review_is_approved`` — the authoritative flag — and never
    writes it. Only ``/client-boq/review/approve`` may.
    """
    from client_boq import store as cb_store

    if not cb_store.review_is_approved(conn, set_id):
        raise ReviewNotApproved(
            f"The review register for set {set_id!r} is not approved — {REVIEW_GATE_HINT}"
        )


def _signals_for(units: list[dict], on_error: Optional[Callable[[str], None]] = None) -> dict[str, dict]:
    """The Layer-1 coverage signal per package, read from the FIRM database.

    Deliberately opened through ``db.store.get_connection`` rather than the bridge's own
    connection: the signal counts firms, and the firm register is procurement's database. The read
    is read-only. When that database has no ``firms`` table — an unseeded test DB, or the DEMO
    scratch DB that holds only ``client_boq_*`` tables — the signal degrades to empty and says so
    LOUDLY, so a recommendation made without coverage data can never look like one made with it.
    """
    from db import store as db_store
    from pipeline.routing.signal import package_signal

    try:
        conn = db_store.get_connection()
    except FileNotFoundError as exc:
        _note(on_error, f"firm database unavailable ({exc}); routing signals are empty for this proposal")
        return {}
    try:
        return {u["package_key"]: package_signal(conn, u["trade"], u["scope_summary"]) for u in units}
    except sqlite3.OperationalError as exc:
        _note(on_error, (
            f"firm database has no firm register ({exc}); routing signals are empty for this "
            "proposal and every recommendation below is a deterministic fallback, not a "
            "coverage-backed one"
        ))
        return {}
    finally:
        conn.close()


def propose_routes(set_id: str, *, on_error: Optional[Callable[[str], None]] = None) -> dict:
    """Propose a route per package for ``set_id`` — behind the review gate.

    Raises :class:`ReviewNotApproved` until the register is approved, and ``LookupError`` when no
    scope split has been persisted. Calls the EXISTING ``route_units`` / ``package_signal`` /
    ``recommend_routes`` unchanged, and persists the proposal under ``run_ref == set_id``.

    An open query never blocks: client_boq's locked decision 8 is that an unanswered question does
    not stop pricing, because the submission deadline does not move because the client has not
    replied. The count rides on the response for a human to weigh; it is never a refusal.
    """
    from db import routing
    from pipeline.llm_client import demo_mode
    from pipeline.routing.recommend import ROUTE_SUGGESTIONS_FIXTURE, recommend_routes
    from pipeline.routing.split import route_units

    from bridge import scope as scope_mod
    from bridge.identity import bridge_conn, register_set_on, run_ref_for
    from client_boq import store as cb_store

    ref = run_ref_for(set_id)
    conn = bridge_conn()
    try:
        require_approved_review(conn, ref)
        scope = scope_mod.load_scope_on(conn, ref)
        if scope is None:
            raise LookupError(
                f"No scope split stored for set {ref!r} — POST /bridge/{ref}/scope first."
            )
        open_queries = cb_store.open_rfi_count(conn, ref)
        register_set_on(conn, ref)

        # The routable unit is the SECTION: route_units returns plain dicts keyed by package_key
        # (``trade`` or ``trade:SECTION``). Consumed as-is — no model is wrapped around it.
        units = route_units(scope)
        signals = _signals_for(units, on_error)
        packages = [
            {
                "package_key": u["package_key"], "trade": u["trade"],
                "scope_summary": u["scope_summary"], "signals": signals.get(u["package_key"], {}),
            }
            for u in units
        ]
        recommended = recommend_routes(
            packages, demo_fixture=ROUTE_SUGGESTIONS_FIXTURE if demo_mode() else None,
        )
        saved = routing.write_proposal(conn, ref, recommended)
    finally:
        conn.close()

    section = {u["package_key"]: u["section"] for u in units}
    section_title = {u["package_key"]: u["section_title"] for u in units}
    if open_queries:
        _note(on_error, (
            f"{open_queries} client question(s) still open — shown, not blocking: an unanswered "
            "query does not move the submission deadline"
        ))
    return {
        "set_id": ref,
        "run_ref": ref,
        "packages": [
            {**r, "section": section.get(r["package_key"]),
             "section_title": section_title.get(r["package_key"], "")}
            for r in saved
        ],
        "open_queries": open_queries,
    }


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
