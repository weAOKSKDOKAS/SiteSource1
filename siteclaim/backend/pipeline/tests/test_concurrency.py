"""Bounded, order-preserving fan-out (pipeline.concurrency.run_calls)."""

import threading
import time

from pipeline.concurrency import run_calls


def test_results_are_in_input_order_despite_out_of_order_completion():
    # Earlier items sleep LONGER, so they finish LAST — yet the output must stay in input
    # order (the merge downstream depends on chunk order, not completion order).
    def fn(i: int) -> int:
        time.sleep((5 - i) * 0.02)  # item 0 sleeps longest, item 4 shortest
        return i

    assert run_calls(fn, [0, 1, 2, 3, 4]) == [0, 1, 2, 3, 4]


def test_calls_actually_overlap():
    # With >1 item the calls run concurrently — observe the peak concurrency exceed 1.
    lock = threading.Lock()
    state = {"live": 0, "peak": 0}

    def fn(_):
        with lock:
            state["live"] += 1
            state["peak"] = max(state["peak"], state["live"])
        time.sleep(0.05)
        with lock:
            state["live"] -= 1
        return None

    run_calls(fn, list(range(4)))
    assert state["peak"] >= 2  # genuinely parallel, not sequential


def test_single_and_empty_run_inline():
    # One item runs inline on the calling thread (the DEMO single-call path is unchanged).
    caller = threading.get_ident()
    seen: list[int] = []
    run_calls(lambda _: seen.append(threading.get_ident()), [object()])
    assert seen == [caller]
    assert run_calls(lambda x: x, []) == []


def test_max_workers_is_bounded():
    # The pool never exceeds max_workers even with many items.
    lock = threading.Lock()
    state = {"live": 0, "peak": 0}

    def fn(_):
        with lock:
            state["live"] += 1
            state["peak"] = max(state["peak"], state["live"])
        time.sleep(0.02)
        with lock:
            state["live"] -= 1

    run_calls(fn, list(range(20)), max_workers=3)
    assert state["peak"] <= 3
