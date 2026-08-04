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
    # Which document set this job is for, so "is one already in flight for this set?" is
    # answerable. Empty for a job over loose uploads, which belongs to no set.
    set_id: str = ""
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
    # TWO clocks, because they measure different things and reporting one as the other hid a
    # 20-minute queue wait inside a "34 minute" run.
    #
    # `started_at` is stamped at CREATE — when the job was enqueued. The pool holds two workers
    # shared by every workflow, so a job can sit here for a long time having spent nothing.
    # `running_at` is stamped when a worker actually picks it up (`mark_running`) and is None
    # until then. Waiting is not working, and a screen that adds them together is telling the
    # operator that the machine is slow when it is in fact busy elsewhere.
    #
    # Elapsed ONLY, in both directions: nothing in this system can honestly estimate remaining
    # time, and a countdown that lies is worse than a bar that says it does not know.
    started_at: float = field(default_factory=time.monotonic)
    running_at: Optional[float] = None
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

    def create(self, kind: str, set_id: str = "") -> str:
        job_id = uuid.uuid4().hex
        with self._lock:
            self._jobs[job_id] = Job(kind=kind, set_id=set_id)
        return job_id

    def live_for(self, kind: str, set_id: str) -> Optional[str]:
        """The id of a job of this kind already in flight for this set, or None.

        In flight means `queued` OR `running`. A queued job counts: it has a worker coming, and
        the whole point of refusing is that a second run must not be lined up behind the first.

        Loose-upload jobs carry no `set_id` and are never matched — they belong to no set, so
        "another one for the same set" is not a question that can be asked about them.
        """
        if not set_id:
            return None
        with self._lock:
            for job_id, job in self._jobs.items():
                if job.kind == kind and job.set_id == set_id and job.status in ("queued", "running"):
                    return job_id
        return None

    def live_any_for(self, set_id: str) -> Optional[str]:
        """The id of a job of ANY kind in flight for this set, or None.

        `live_for` answers "may this workflow start?"; this answers "what is this set doing right
        now?" — the question a screen has to ask when it opens. Without it a tab that mounts while
        a run is in flight knows nothing about it, renders its Run button, and the operator gets a
        409 from a button the UI had just told them to press.

        First match wins. The pool serialises anyway, and where two jobs are live for one set (one
        running, one queued behind it) either answer is true — the screen shows the set as busy,
        which is the fact it needs. Insertion order makes it the oldest, which is the one that will
        finish first.
        """
        if not set_id:
            return None
        with self._lock:
            for job_id, job in self._jobs.items():
                if job.set_id == set_id and job.status in ("queued", "running"):
                    return job_id
        return None

    def mark_running(self, job_id: str, stage: str) -> None:
        """A worker has picked this job up. Stops the queue clock and starts the run clock.

        `running_at` is stamped once and never restamped, so a job that reaches this twice (it
        should not) still reports the moment work actually began.
        """
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            job.status = "running"
            job.stage = stage
            if job.running_at is None:
                job.running_at = time.monotonic()

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
