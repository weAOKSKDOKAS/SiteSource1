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

from client_boq import criteria_loader, store
from client_boq.models import DepartureRegister, RawUpload
from client_boq.review import (
    s01_ingest,
    s02_context_summary,
    s03_criteria_match,
    s07_register,
    s08_citation_verify,
)
from pipeline.workspace import Workspace, tender_slug

DEFAULT_REVIEW_NAME = "Client document set"
SLICE = "1"  # s01→s03→s07→s08; s04–s06 are slice 2

ProgressCB = Callable[[str], None]


def run_review(
    uploads: list[RawUpload], project_name: str = "", *, progress_cb: Optional[ProgressCB] = None,
) -> DepartureRegister:
    """Run the review end to end and persist it. Returns the assembled, citation-checked register."""

    def step(stage: str) -> None:
        if progress_cb:
            progress_cb(stage)

    ws = Workspace()

    # s01 — parse the document set, then stamp the stable identity onto it.
    step("ingesting")
    parsed = s01_ingest.ingest_review_documents(uploads, project_name, workspace=ws)
    final_name = (project_name or parsed.name or DEFAULT_REVIEW_NAME).strip() or DEFAULT_REVIEW_NAME
    slug = tender_slug(final_name)
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
        library = criteria_loader.load_criteria()
        departures = s03_criteria_match.match_criteria(parsed, summary, library)

        # s07 — assemble the register (slice-2 stages absent → recorded as pending).
        step("assembling")
        register = s07_register.assemble_register(slug, parsed, summary, departures)

        # s08 — deterministic citation guard (mutates the register's failed lines).
        step("verifying")
        s08_citation_verify.verify_citations(register, parsed)

        # Persist the register to both homes; the tables copy is authoritative for the gate.
        store.save_register(conn, register)
        store.save_register_artifact(ws, final_name, register)
        store.upsert_document_set(conn, set_id=slug, name=final_name, slug=slug, status="reviewed")
        # Reload so the register carries the authoritative approved flag from the tables.
        return store.load_register(conn, slug) or register
    finally:
        conn.close()
