"""The archive extraction worker — the job half of `bridge/archive.py`.

Split from the endpoint so the long-running work runs on the same pool, reports through the same
strip, and stops with the same STOP as every other operation in the product. A 232 MB extraction is
the longest-running thing in this product and must not be the one thing a person cannot see or
interrupt.
"""

from __future__ import annotations

from client_boq import jobs, store
from client_boq import models as cb_models

# The shared job-boundary helpers. Private to that module by name, imported rather than copied on
# purpose: a second implementation of "check for cancel at a stage boundary" is a second thing to
# get wrong.
from client_boq.router import _begin, _count_cb, _stage_cb


def run_archive_extract_job(job_id: str, set_id: str, name: str) -> None:
    """Extract an approved tender pack, then record its parts.

    In `bridge/`, not in `client_boq/router.py` beside the other workers, and the difference is the
    ruling: ONE line was authorised in that file — the `_WORKFLOW_STAGES` entry — and a seventy-line
    worker is not one line. `_begin` / `_stage_cb` / `_count_cb` are IMPORTED from there rather than
    reimplemented here, so the cancel boundary and the stage bookkeeping keep exactly one owner; an
    import is a read, and a second copy of a cancel rule is how one of them starts to drift.

    Everything it calls in client_boq is public but for those three, and it edits nothing.
    """
    from pipeline.workspace import Workspace

    from bridge import archive as arch
    from bridge.router import _archive_path

    stage = _stage_cb(job_id, "archive")
    try:
        _begin(job_id, "reading")
        ws = Workspace()
        report = arch.read_tree(_archive_path(ws, name))
        arch.check_size(report)          # re-checked: the file on disk may not be the one proposed

        stage("extracting")
        written = arch.extract(report, ws, name, count_cb=_count_cb(job_id))

        stage("recording")
        conn = store.get_conn()
        try:
            manifest = store.load_manifest(conn, set_id)
            if manifest is None:
                raise ValueError(f"No split manifest for set {set_id!r}.")
            # Page counts, and the workbook flag, from the bytes now on disk — the one moment they
            # are free. The proposal could not know them without extracting, which is exactly what
            # it must not do.
            pdf_paths: dict[str, str] = {}
            for part in manifest.parts:
                path = written.get(part.source_doc)
                if path is None:
                    continue
                if arch.is_workbook(part.source_doc):
                    # Not cut, real extension kept, and the reason recorded — `scanned` is the only
                    # unreadable flag available without editing this package's models, and elsewhere
                    # it means "needs vision". A workbook needs the Excel reader.
                    part.scanned = True
                    continue
                part.end = max(1, _page_count_of(path))
                pdf_paths[part.part_id] = path
            store.save_manifest(conn, manifest)
            store.upsert_document(
                conn, set_id, doc_id="doc-0", filename="(archive)",
                kind=cb_models.DOC_BASE, ref="As issued",
            )
            store.save_parts(conn, set_id, manifest.parts, pdf_paths, doc_id="doc-0", rev=0)
            store.upsert_document_set(
                conn, set_id=set_id, name=name, slug=set_id, status="ingested"
            )
        finally:
            conn.close()

        stage("ingested")
        jobs.JOBS.update(
            job_id, status="done", stage="ingested",
            done=len(manifest.parts), total=len(manifest.parts),
            result={"set_id": set_id, "parts": len(manifest.parts),
                    "workbooks": sum(1 for p in manifest.parts if arch.is_workbook(p.source_doc))},
        )
        for part in manifest.parts:
            if arch.is_workbook(part.source_doc):
                jobs.JOBS.add_warning(job_id, f"{part.title}: {arch.WORKBOOK_NOTE}")
    except jobs.JobCancelled as stop:
        jobs.JOBS.update(job_id, status="cancelled", stage=f"stopped before {stop}")
    except Exception as exc:  # noqa: BLE001
        jobs.JOBS.update(job_id, status="error", error=str(exc))


def _page_count_of(path: str) -> int:
    """A PDF's page count, or 0 when it is not one. Never raises — an unreadable member is a part
    with no pages, not a failed extraction."""
    try:
        import fitz

        with fitz.open(path) as doc:
            return len(doc)
    except Exception:  # noqa: BLE001
        return 0
