"""In-package background-job store for client_boq's heavy handlers.

The REVIEW ingest (extract + AI-structure a full contract set) runs for far longer than a
client/proxy will hold a request open — the same problem the procurement ingest hit. The main app
solved it with a private ``_IngestJobStore`` + ``ThreadPoolExecutor`` + a poll endpoint inside
``api.py``; that machinery is private to that module, so — as agreed in Phase A — client_boq
REPLICATES the pattern here rather than importing it (importing would mean editing ``api.py``).

Same shape as the original: heavy work is a sync ``def`` submitted to a small pool, the kick-off
returns a job id, and the client polls a status endpoint. The store is in-process and ephemeral (a
restart drops jobs) — acceptable for a single-operator tool.

SCAFFOLD NOTE: the store and pool are real infra (deterministic, no workflow logic). The functions
that would submit actual review/estimate work are the stage stubs, still ``NotImplementedError``.
"""

from __future__ import annotations

import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Job:
    """One background job's live state (mirrors the main app's ``_IngestJob``)."""

    kind: str = ""                 # "review" | "estimate"
    status: str = "queued"         # queued | running | done | error | cancelled
    stage: str = ""                # workflow-specific stage label
    # Where this stage sits in its workflow, and how many there are. `stage_total` is 0 when the
    # sequence is not statically known — the UI then shows the position with no total rather than
    # a total it might contradict two stages later.
    stage_index: int = 0
    stage_total: int = 0
    # Progress WITHIN the current stage, written as the loop runs rather than once at the end.
    # 0/0 means "this stage is not batched, or its length is not known" — never a stand-in for
    # "starting", because a bar that moves without work behind it is worse than one that admits
    # it does not know.
    done: int = 0
    total: int = 0
    # Wall-clock seconds since the job was created, computed on read. Elapsed ONLY: nothing in this
    # system can honestly estimate remaining time, and a countdown that lies is worse than a bar
    # that says it does not know.
    started_at: float = field(default_factory=time.monotonic)
    result: Optional[dict] = None
    error: str = ""
    warnings: list[str] = field(default_factory=list)
    # Set by `cancel()`; READ by the worker at each stage boundary. It is a request, never a
    # kill: a model call already in flight is a blocking HTTP request on a pool thread and Python
    # cannot interrupt one. What cancelling buys is that the NEXT call is not started — on a run
    # of ~100 calls at 20-120 seconds each, that is the whole of the saving, and it is worth
    # having. The UI must say "stopping at the next step", not "stopped".
    cancel_requested: bool = False


class JobStore:
    """Thread-safe per-process registry for client_boq background jobs."""

    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def create(self, kind: str) -> str:
        job_id = uuid.uuid4().hex
        with self._lock:
            self._jobs[job_id] = Job(kind=kind)
        return job_id

    def get(self, job_id: str) -> Optional[Job]:
        with self._lock:
            return self._jobs.get(job_id)

    def update(self, job_id: str, **changes) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            for key, value in changes.items():
                setattr(job, key, value)

    def add_warning(self, job_id: str, message: str) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is not None:
                job.warnings.append(message)

    def cancel(self, job_id: str) -> bool:
        """Ask a job to stop at its next stage boundary. False when there is no such job, or it
        has already finished — cancelling a finished job is a no-op, not an error.

        A queued job that has not started yet is marked cancelled immediately: there is no
        boundary to wait for, and the worker checks before it does anything.
        """
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.status in ("done", "error", "cancelled"):
                return False
            job.cancel_requested = True
            if job.status == "queued":
                job.status = "cancelled"
                job.stage = "cancelled before it started"
            return True

    def cancelled(self, job_id: str) -> bool:
        """Whether this job has been asked to stop. Called by a worker at a stage boundary."""
        with self._lock:
            job = self._jobs.get(job_id)
            return bool(job and job.cancel_requested)


class JobCancelled(Exception):
    """Raised by a worker's stage-boundary check so the run unwinds through its own error path
    rather than each stage needing a return-value protocol."""


# Module-level singletons, exactly as api.py holds _INGEST_JOBS / _INGEST_POOL.
JOBS = JobStore()
POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix="client_boq")
