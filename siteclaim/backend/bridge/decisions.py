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


def _note(on_error: Optional[Callable[[str], None]], message: Optional[str]) -> None:
    """Record a note, if there is a channel and there is anything to say.

    ``None`` is accepted so a caller can pass a maybe-warning straight through —
    ``_note(on_error, require_approved_review(...))`` — rather than branching at every site and
    eventually forgetting at one of them.
    """
    if on_error and message:
        on_error(message)


class ReviewNotApproved(RuntimeError):
    """The client_boq review register for this set is not approved — the gate both forks inherit."""


def require_approved_review(conn: sqlite3.Connection, set_id: str) -> Optional[str]:
    """The review gate. Returns a warning string in soft mode, ``None`` when there is nothing to say.

    Read-only: it asks client_boq's own ``review_is_approved`` — the authoritative flag — and never
    writes it. Only ``/client-boq/review/approve`` may.

    **V1 DELIBERATE DEPARTURE from the locked review→routing hard-gate decision.** In the default
    ``REVIEW_GATE=soft`` mode an unapproved register no longer raises: it returns
    :data:`SOFT_GATE_WARNING`, which the caller MUST surface. ``REVIEW_GATE=hard`` restores the
    original :class:`ReviewNotApproved` byte-for-byte. See ``client_boq/gates.py`` for why.

    The return value is not optional to handle. A caller that drops it turns a warned bypass into a
    silent one, which is the failure mode this whole design is trying to avoid — so both call sites
    below thread it onto their response payload, and there is a test per site.
    """
    from client_boq import store as cb_store
    from client_boq.gates import SOFT_GATE_WARNING, review_gate_is_soft

    if cb_store.review_is_approved(conn, set_id):
        return None
    if review_gate_is_soft():
        return SOFT_GATE_WARNING
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
        # Soft mode returns a warning instead of raising; it goes onto the response through the
        # channel this function already has, so an unread-terms bypass is never silent.
        _note(on_error, require_approved_review(conn, ref))
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
        # A RE-ROUTE CAN CHANGE THE KEYS, AND A DECISION FOR A KEY THAT NO LONGER EXISTS IS NOT A
        # DECISION. `write_proposal` replaces `package_routes` wholesale, but `bridge_route_decisions`
        # is a separate table that nothing cleared — so after a re-route it still held rows for the
        # previous shape. `sublet_packages` is read straight off those rows, and the sourcing screen
        # then filters the CURRENT proposal by them: a stale key matches nothing and a new key has no
        # decision, so packages the operator had routed to sublet simply stopped arriving.
        #
        # Dropped, not silently: the operator is told which decisions the re-route invalidated, so a
        # re-confirm is a known step rather than a mystery.
        ensure_tables(conn)
        live = {p["package_key"] for p in saved}
        orphaned = [d["package_key"] for d in load_decisions(conn, ref)
                    if d["package_key"] not in live]
        if orphaned:
            conn.executemany(
                "DELETE FROM bridge_route_decisions WHERE set_id = ? AND package_key = ?",
                [(ref, key) for key in orphaned])
            conn.commit()
            _note(on_error, (
                f"{len(orphaned)} previous route decision(s) no longer apply after this re-route "
                f"({', '.join(sorted(orphaned))}) — the packages they named are not in the new "
                f"proposal. Confirm the routing again."
            ))
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

    UNIQUE ``(set_id, package_key)`` from the first version, so re-deciding a package updates in
    place instead of leaving two contradictory decisions to be read back in insertion order.
    (``package_routes`` has no such constraint; this table is not that table, and does not
    inherit its gap.)
    """
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS bridge_route_decisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            set_id TEXT NOT NULL,
            package_key TEXT NOT NULL,
            chosen_route TEXT NOT NULL,
            decided_by TEXT NOT NULL DEFAULT 'operator',
            decided_at TEXT NOT NULL,
            UNIQUE(set_id, package_key)
        );
        CREATE INDEX IF NOT EXISTS idx_bridge_route_decisions_set ON bridge_route_decisions(set_id);
        """
    )
    conn.commit()


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)
    ).fetchone()
    return bool(row["n"])


def load_decisions(conn: sqlite3.Connection, set_id: str) -> list[dict]:
    """Every persisted route decision for ``set_id``, in package order.

    A pure read: it does NOT create the table, so a GET that lands before any decision has been
    recorded returns ``[]`` rather than writing DDL. (``confirm_routes`` calls ``ensure_tables``
    itself before it writes, so nothing depends on this creating it.)
    """
    if not _table_exists(conn, "bridge_route_decisions"):
        return []
    rows = conn.execute(
        "SELECT package_key, chosen_route, decided_by, decided_at FROM bridge_route_decisions "
        "WHERE set_id = ? ORDER BY package_key",
        (set_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def stored_proposal(set_id: str) -> dict:
    """The persisted route proposal for ``set_id`` — a pure read, and NEVER a re-run.

    The step chips need to know whether a proposal exists. Calling ``propose_routes`` to find out
    would be a write (``write_proposal`` deletes and re-inserts) and, live, a model call — so this
    reads ``package_routes`` back instead.

    "Not yet run" is a STATE, not an error: a set with no proposal returns ``packages: []``.

    ``section``/``section_title`` are recovered by re-running ``route_units`` over the persisted
    split — deterministic Layer-1 Python, no model — so a reloaded tab shows the same headings as
    the one that just ran the analysis. With no split stored they are simply absent.
    """
    from db import routing
    from pipeline.routing.split import route_units

    from bridge import scope as scope_mod
    from bridge.identity import bridge_conn, run_ref_for
    from client_boq import store as cb_store

    ref = run_ref_for(set_id)
    conn = bridge_conn()
    try:
        saved = routing.read_proposal(conn, ref)
        split = scope_mod.load_scope_on(conn, ref)
        open_queries = cb_store.open_rfi_count(conn, ref)
        review_approved = cb_store.review_is_approved(conn, ref)
    finally:
        conn.close()

    section: dict[str, object] = {}
    section_title: dict[str, str] = {}
    if split is not None:
        for unit in route_units(split):
            section[unit["package_key"]] = unit["section"]
            section_title[unit["package_key"]] = unit["section_title"]

    return {
        "set_id": ref,
        "run_ref": ref,
        "packages": [
            {**row, "section": section.get(row["package_key"]),
             "section_title": section_title.get(row["package_key"], "")}
            for row in saved
        ],
        "open_queries": open_queries,
        "review_approved": review_approved,
        "has_split": split is not None,
    }


def stored_decisions(set_id: str) -> dict:
    """The persisted route decisions for ``set_id`` — a pure read.

    Same shape as ``confirm_routes`` returns, so a tab renders identically whether it just
    confirmed or is reading back after a reload. No decisions yet is ``decisions: []``, not a 404.
    """
    from schemas.routing import SELF_PERFORM, SUBLET

    from bridge.identity import bridge_conn, run_ref_for

    ref = run_ref_for(set_id)
    conn = bridge_conn()
    try:
        stored = load_decisions(conn, ref)
    finally:
        conn.close()
    return {
        "set_id": ref,
        "run_ref": ref,
        "decisions": stored,
        "self_perform_packages": [d["package_key"] for d in stored if d["chosen_route"] == SELF_PERFORM],
        "sublet_packages": [d["package_key"] for d in stored if d["chosen_route"] == SUBLET],
    }


def confirm_routes(set_id: str, decisions: dict[str, str], *, decided_by: str = "operator",
                   on_error: Optional[Callable[[str], None]] = None) -> dict:
    """Record the human's route per package for ``set_id`` and return the self-perform/sublet split.

    ``on_error`` is the note channel ``propose_routes`` already had and this did not. It exists for
    the soft review gate: confirming a route on unread contract terms has to say so on the response
    that records the confirmation, not only on the proposal that preceded it. The notes also ride
    on the returned payload under ``notes``, so a caller with no callback still receives them.

    Validates every route against ``schemas.routing.ROUTES`` and every package_key against the
    persisted proposal BEFORE writing anything — a decision for a package nobody proposed would
    otherwise sit in the table describing a package that does not exist.

    **Seeds nothing, on either side.** ``client_boq_estimates`` is keyed by ``set_id`` — ONE
    estimate per tender — and that is correct: a main contractor submits one priced bill with a
    single tendered total, and every item on it is priced. The route decision does not change which
    items appear in the submission; it changes only where each item's RATE comes from (our own
    build-up, or a subcontractor's quote). Seeding one estimate per self-perform package would
    create N documents where the tender needs one.

    It also never calls the procurement ``/route/confirm``, which seeds only when a ``scope`` is
    supplied — so that endpoint keeps working exactly as it does today, unedited, and remains the
    sole writer of ``package_routes.chosen_route``.
    """
    from schemas.routing import ROUTES, SELF_PERFORM, SUBLET

    from bridge.identity import bridge_conn, run_ref_for
    from db import routing

    ref = run_ref_for(set_id)
    if not decisions:
        raise ValueError("Decide at least one package — an empty confirmation records nothing.")
    bad = {key: route for key, route in decisions.items() if route not in ROUTES}
    if bad:
        raise ValueError(
            f"unknown route(s) {bad} (use one of {list(ROUTES)})"
        )

    conn = bridge_conn()
    try:
        # The same gate the proposal is behind: confirming a route IS routing, and a gate that only
        # covers the advisory step would be bypassed by posting straight here. In soft mode that
        # symmetry is what matters most — the bypass is recorded on the act, not just the advice.
        gate_note = require_approved_review(conn, ref)
        _note(on_error, gate_note)
        ensure_tables(conn)
        proposed = {p["package_key"] for p in routing.read_proposal(conn, ref)}
        if not proposed:
            raise LookupError(
                f"No route proposal for set {ref!r} — POST /bridge/{ref}/route/analyze first."
            )
        unknown = sorted(set(decisions) - proposed)
        if unknown:
            raise ValueError(
                f"Unknown package_key(s) for set {ref!r}: {', '.join(unknown)}. "
                f"Proposed: {', '.join(sorted(proposed))}."
            )

        stamp = _now()
        conn.executemany(
            "INSERT INTO bridge_route_decisions (set_id, package_key, chosen_route, decided_by, decided_at) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(set_id, package_key) DO UPDATE SET "
            "chosen_route = excluded.chosen_route, decided_by = excluded.decided_by, "
            "decided_at = excluded.decided_at",
            [(ref, key, route, decided_by, stamp) for key, route in decisions.items()],
        )
        conn.commit()
        stored = load_decisions(conn, ref)
    finally:
        conn.close()

    return {
        "set_id": ref,
        "run_ref": ref,
        "decisions": stored,
        "self_perform_packages": [d["package_key"] for d in stored if d["chosen_route"] == SELF_PERFORM],
        "sublet_packages": [d["package_key"] for d in stored if d["chosen_route"] == SUBLET],
        # Same field name and shape as `/route/analyze`'s notes, so one renderer serves both.
        "notes": [gate_note] if gate_note else [],
    }
