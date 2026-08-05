"""The scope-split worker — the job half of `bridge/scope.py`.

`POST /bridge/{set_id}/scope` read every part's pdf, ran the extraction, and indexed ~170 documents
inside the request. On the real pack that blocked for minutes with no progress, no stage, and no
way to stop it. It was a sync `def`, so it did not block the event loop — the server stayed up and
answered other requests, which is precisely why the failure was invisible: the only symptom was one
request that never came back.

Split from the endpoint on the same terms as `bridge/archive_job.py`, and for the same reason: the
long-running work runs on the same pool, reports through the same strip, and stops with the same
STOP as every other operation in the product. `_begin` / `_stage_cb` / `_count_cb` are IMPORTED
from `client_boq.router` rather than reimplemented, so the cancel boundary and the stage
bookkeeping keep exactly one owner — an import is a read, and a second copy of a cancel rule is how
one of them starts to drift.
"""

from __future__ import annotations

from client_boq import jobs

from client_boq.router import _begin, _count_cb, _stage_cb


def run_scope_split_job(job_id: str, set_id: str) -> None:
    """Split a set's confirmed bill, persist the scope, and put the SAME payload on the job.

    ``result`` is byte-for-byte the dict the endpoint used to return — set_id, scope,
    unrecognised_items, notes — so a caller reading the finished job reads what it always read.
    Nothing about the split's answer changed; only where the caller collects it from.
    """
    from bridge import scope as scope_mod

    notes: list[str] = []
    # No `_WORKFLOW_STAGES` entry, and no line added to `client_boq/router.py` to give it one:
    # that dict's own rule is that a workflow appears in it only if its stages are CERTAIN, and
    # these are not — a workbook bill skips `splitting` entirely. So the stage NAME is reported and
    # the position is not, which is what that file does with every other uncertain-length run.
    stage = _stage_cb(job_id, "scope_split")

    def _count(done: int, total: int) -> None:
        # The cancel check lives HERE rather than in `_count_cb` because a part boundary is the
        # only boundary this stage has: indexing is one long loop, not a sequence of stages, so
        # without this a STOP pressed during indexing would wait for all ~170 documents.
        if jobs.JOBS.cancelled(job_id):
            raise jobs.JobCancelled("indexing")
        _count_cb(job_id)(done, total)

    try:
        _begin(job_id, "reading")
        scope, unrecognised = scope_mod.scope_from_set(
            set_id, on_error=notes.append, progress_cb=stage, count_cb=_count,
        )
        scope_mod.save_scope(set_id, scope)
        stage("split")
        jobs.JOBS.update(
            job_id, status="done", stage="split",
            result={
                "set_id": set_id,
                "scope": scope.model_dump(),
                "unrecognised_items": [u.model_dump() for u in unrecognised],
                "notes": notes,
            },
        )
        # The split's own honest-degradation messages, on the job as well as in the result: a
        # quarantined item or an unreadable part is worth seeing while the run is still on screen,
        # not only after someone opens the finished payload.
        for note in notes[:20]:
            jobs.JOBS.add_warning(job_id, note)
    except jobs.JobCancelled as stop:
        jobs.JOBS.update(job_id, status="cancelled", stage=f"stopped before {stop}")
    except (LookupError, ValueError) as exc:
        # The two the endpoint turned into a 404 and a 409. On a job there is no status code to
        # carry that distinction, so the message does — both already name what to do next.
        jobs.JOBS.update(job_id, status="error", error=str(exc))
    except Exception as exc:  # noqa: BLE001
        jobs.JOBS.update(job_id, status="error", error=str(exc))
