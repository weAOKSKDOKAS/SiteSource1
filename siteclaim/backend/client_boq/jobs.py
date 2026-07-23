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
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Job:
    """One background job's live state (mirrors the main app's ``_IngestJob``)."""

    kind: str = ""                 # "review" | "estimate"
    status: str = "queued"         # queued | running | done | error
    stage: str = ""                # workflow-specific stage label
    done: int = 0
    total: int = 0
    result: Optional[dict] = None
    error: str = ""
    warnings: list[str] = field(default_factory=list)


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


# Module-level singletons, exactly as api.py holds _INGEST_JOBS / _INGEST_POOL.
JOBS = JobStore()
POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix="client_boq")
