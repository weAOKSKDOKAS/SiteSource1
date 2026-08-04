"""Orchestrate the REVIEW workflow for one document set: s01 → s02 → s03 → s07 → s08.

This is the single sync entry the router calls (as a background job in live, inline in DEMO). It
threads the typed handoffs between stages, assigns the stable set identity, and persists each result
to BOTH homes — the readable Workspace artifacts and the ``client_boq_*`` tables (the source of truth
for the gate). Slice 1 deliberately skips s04–s06 (scope alignment, program, cash flow); the register
records them in ``slice2_pending`` so the gap is explicit.

No workflow decision is made here — this is plumbing over the stages. The only writer of a
confirmed/dismissed verdict remains the human approve endpoint.
"""

from __future__ import annotations

from typing import Callable, Optional

from client_boq import criteria_store, store
from client_boq.models import DepartureRegister, RawUpload
from client_boq.review import (
    s01_ingest,
    s02_context_summary,
    s03_criteria_match,
    s04_scope_align,
    s05_program_check,
    s06_cashflow,
    s07_register,
    s08_citation_verify,
)
from pipeline.llm_client import demo_mode
from pipeline.workspace import Workspace, tender_slug

DEFAULT_REVIEW_NAME = "Client document set"
SLICE = "2"  # s01→s02→s03→s04→s05→s06→s07→s08 (the full review)

ProgressCB = Callable[[str], None]


def _set_name(set_id: str) -> str:
    """The project name an ingested set was created under (its Workspace directory key)."""
    conn = store.get_conn()
    try:
        row = conn.execute(
            "SELECT name FROM client_boq_document_sets WHERE set_id = ?", (set_id,)
        ).fetchone()
        return (row["name"] if row else "") or ""
    finally:
        conn.close()


def _ingested_parts(set_id: str):
    """The approved, split parts of a set — or an empty list when it never went through ingest.

    Two-tuples, deliberately: ``s08_citation_verify.locate_citations`` consumes this same list and
    unpacks it as ``(spec, path)``. The interpreted contexts the skip-list needs come from
    :func:`_part_contexts` instead, as a separate lookup — widening this tuple broke citation
    verification across the whole suite the first time it was tried.
    """
    if not set_id:
        return []
    conn = store.get_conn()
    try:
        if not store.manifest_is_approved(conn, set_id):
            return []
        return [(spec, path) for spec, path, _ctx in store.load_parts(conn, set_id) if path]
    finally:
        conn.close()


def _part_contexts(set_id: str) -> dict:
    """``part_id -> PartContext`` for a set: the category the interpreter chose after READING each
    part's pages and images.

    The planner's ``PartSpec.category`` is a guess from a digest that contains no body text, and on
    the first real bill of quantities it said ``other`` — so the review's skip-list passed a
    26-page pricing document through to be read as a contract. The better answer was already
    persisted; it was simply never asked for.
    """
    if not set_id:
        return {}
    conn = store.get_conn()
    try:
        return {
            spec.part_id: ctx
            for spec, _path, ctx in store.load_parts(conn, set_id)
            if ctx is not None
        }
    finally:
        conn.close()


def run_review(
    uploads: list[RawUpload], project_name: str = "", *, set_id: str = "",
    progress_cb: Optional[ProgressCB] = None,
    on_note: Optional[Callable[[str], None]] = None,
) -> DepartureRegister:
    """Run the review end to end and persist it. Returns the assembled, citation-checked register.

    Give it a ``set_id`` to review a set that has already been through ingest: the review then
    reads the approved parts, a part at a time, and every clause carries the part it came from.
    Give it ``uploads`` to review loose documents directly, as before.

    ``on_note`` carries what the person reading the register needs to know that is not IN it —
    today, which parts were not read for contractual positions, and whether the set contained a
    contractual document at all.
    """

    def step(stage: str) -> None:
        if progress_cb:
            progress_cb(stage)

    ws = Workspace()

    # s01 — parse the document set, then stamp the stable identity onto it.
    step("ingesting")
    parts = _ingested_parts(set_id)
    if parts and not demo_mode():
        parsed = s01_ingest.ingest_from_parts(
            parts, project_name, on_note=on_note, contexts=_part_contexts(set_id),
        )
    else:
        parsed = s01_ingest.ingest_review_documents(uploads, project_name, workspace=ws)
    final_name = (project_name or parsed.name or DEFAULT_REVIEW_NAME).strip() or DEFAULT_REVIEW_NAME
    slug = tender_slug(final_name)
    if set_id:
        # Reviewing an ingested set: keep ITS identity, or the register would attach to a second,
        # parallel set and the manifest, parts and register would drift apart.
        slug = set_id
        final_name = _set_name(set_id) or final_name
    parsed = parsed.model_copy(update={"set_id": slug, "name": final_name, "slug": slug})

    conn = store.get_conn()
    try:
        store.save_parsed_artifact(ws, final_name, parsed)
        store.upsert_document_set(
            conn, set_id=slug, name=final_name, slug=slug, status="ingested",
            parsed_json=parsed.model_dump_json(),
        )

        # s02 — commercial-risk summary (draft).
        step("summarising")
        summary = s02_context_summary.summarise_context(parsed)
        store.upsert_document_set(
            conn, set_id=slug, name=final_name, slug=slug, status="ingested",
            summary_json=summary.model_dump_json(),
        )

        # s03 — propose matches, then deterministic threshold rules.
        step("matching")
        # The DB-backed library (seeded from the markdown on first access). enabled_only:
        # a criterion someone disabled stops being checked in FUTURE reviews, while past
        # registers still resolve it through the full list.
        library = criteria_store.load(conn, enabled_only=True)
        departures = s03_criteria_match.match_criteria(parsed, summary, library)

        # s04 — scope alignment (AI propose + deterministic precedence + input gaps).
        step("scope")
        scope_items = s04_scope_align.check_scope_alignment(parsed, summary)

        # s05 — program check (program-not-provided guard + AI propose + deterministic recompute).
        step("program")
        program_items = s05_program_check.check_program(parsed, summary)

        # s06 — deterministic cash-flow profile (no AI) from the extracted terms.
        step("cashflow")
        cashflow_section, cashflow_items = s06_cashflow.check_cashflow(
            parsed, summary, departures.departures,
        )

        # s07 — fold everything into the one register.
        step("assembling")
        register = s07_register.assemble_register(
            slug, parsed, summary, departures,
            scope_items=scope_items, program_items=program_items,
            cashflow=cashflow_section, cashflow_items=cashflow_items,
        )

        # s08 — deterministic citation guard over ALL line items (mutates failed lines).
        step("verifying")
        s08_citation_verify.verify_citations(register, parsed)

        # ...and the physical half: look for each quotation in the document it cites, so the page
        # on a register line is measured rather than claimed. Only possible once a set has been
        # split into parts; a set reviewed from loose uploads simply skips it.
        if parts:
            step("locating")
            s08_citation_verify.locate_citations(register, parsed, parts)

        # Persist the register to both homes; the tables copy is authoritative for the gate.
        store.save_register(conn, register)
        store.save_register_artifact(ws, final_name, register)
        store.upsert_document_set(conn, set_id=slug, name=final_name, slug=slug, status="reviewed")
        # Reload so the register carries the authoritative approved flag from the tables.
        return store.load_register(conn, slug) or register
    finally:
        conn.close()
