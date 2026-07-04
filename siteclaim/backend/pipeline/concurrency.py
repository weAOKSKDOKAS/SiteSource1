"""Bounded, order-preserving fan-out for independent LLM calls (Layer 2 performance).

Chunked extraction (ingest) and chunked reply parsing (level) issue several independent
``complete_json`` calls whose results are then merged. Run sequentially, a 58-page
Schedule of Rates took ~7 minutes (6 chunks × ~1 min). :func:`run_calls` overlaps them on
a small thread pool.

Two invariants the merge depends on:

* **Order is preserved.** Results come back in input order, never completion order —
  ``ThreadPoolExecutor.map`` guarantees this — so an order-sensitive merge (dedupe by
  ``item_ref``, first wins) behaves exactly as it did sequentially.
* **The single-call path is untouched.** One item runs inline with no thread, so the
  DEMO_MODE path (a single fixture call) is byte-for-byte identical and opens no pool.

Stdlib only — no SDK import — so importing this module stays offline-safe.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Callable, TypeVar

T = TypeVar("T")
R = TypeVar("R")

MAX_WORKERS = 4  # a handful of concurrent provider calls, not a flood


def run_calls(fn: Callable[[T], R], items: list[T], *, max_workers: int = MAX_WORKERS) -> list[R]:
    """Apply ``fn`` to each item and return results IN INPUT ORDER.

    ``len(items) <= 1`` runs inline (no pool — the DEMO single-call path is unchanged).
    Otherwise the calls overlap on a bounded pool sized to ``min(max_workers, len(items))``.
    Exceptions propagate (``map`` re-raises the first), so a failing call fails the batch
    exactly as the sequential comprehension did.
    """
    if len(items) <= 1:
        return [fn(item) for item in items]
    with ThreadPoolExecutor(max_workers=min(max_workers, len(items))) as pool:
        return list(pool.map(fn, items))
