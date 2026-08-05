"""The review's reading loop, split in two so the calls can overlap and the bar can move.

The old loop read a part and called the model in the same breath, which forced two things:

* every model call was sequential — a 33-part set is well over a hundred calls at 20-120 seconds
  each, one after another;
* the only countable unit was the PART, because a part's chunk count is not known until its text
  has been read. So `count_cb` fired once per part, with the index taken BEFORE the work, and a
  40-page part's eight calls all happened under one unchanging number. The strip sat at 0/33.

Reading everything first costs a few seconds of local PDF extraction and buys the real
denominator — the number of model calls this run will make — and lets `run_calls` overlap them
four at a time.

What must NOT change, and is asserted here: the clauses, their order, the documents list, and
every note the skip-list emits. This is a performance change; if it were also a behaviour change
the register would differ between two runs of the same tender, which is the one thing a
departure register cannot do.
"""

import re
import threading
import time

import pytest

from client_boq.models import ClauseItem, ParsedDocumentSet, PartSpec
from client_boq.review import s01_ingest


@pytest.fixture
def make_part(tmp_path):
    """A real part on disk whose page count drives its chunk count."""
    def _make(n: int, abbr: str, pages: int, category: str = "contract-conditions"):
        fitz = pytest.importorskip("fitz")
        doc = fitz.open()
        for i in range(pages):
            page = doc.new_page()
            # Short lines: `insert_text` clips at the page edge, so one long string would extract
            # back as the ~90 characters that fit and every part would be a single chunk.
            for line in range(40):
                page.insert_text((40, 40 + line * 18),
                                 f"{abbr} p{i} l{line} clause text " + "lorem ipsum dolor " * 3,
                                 fontsize=7)
        path = tmp_path / f"{abbr}.pdf"
        doc.save(str(path))
        doc.close()
        spec = PartSpec(n=n, abbr=abbr, slug=abbr.lower(), title=f"Part {abbr}",
                        start=1, end=pages, category=category)
        return (spec, str(path))
    return _make


class RecordingClient:
    """Returns one clause per call, tagged with the body it saw, and records concurrency."""

    def __init__(self, fail_on: str = ""):
        self.calls: list[str] = []
        self.fail_on = fail_on
        self._lock = threading.Lock()
        self.live = 0
        self.peak = 0

    def complete_json(self, *, system, user, target_model, **_kw):
        with self._lock:
            self.calls.append(user)
            self.live += 1
            self.peak = max(self.peak, self.live)
        try:
            # A real provider call takes 20-120 seconds; an instant stub would let each call
            # finish before the next begins and `peak` would read 1 on a genuinely parallel run.
            # The sleep is what makes overlap observable at all.
            time.sleep(0.02)
            if self.fail_on and self.fail_on in user:
                raise RuntimeError("this chunk is unreadable")
            # The framed header names the part: `=== {source} — part 01 Part AAA (source pages …)`.
            # Echo back just the part identity so ordering and stitching are checkable.
            m = re.search(r"— part (\d+) (Part \w+)", user)
            return ParsedDocumentSet(name="T", documents=[], clauses=[
                ClauseItem(clause="1.1", heading=f"{m.group(1)} {m.group(2)}" if m else "?",
                           text="body"),
            ])
        finally:
            with self._lock:
                self.live -= 1


@pytest.fixture
def stub(monkeypatch):
    def _install(client):
        monkeypatch.setattr(s01_ingest, "make_client", lambda: client)
        return client
    return _install


# ---------------------------------------------------------------------------
# Identical output to the sequential run
# ---------------------------------------------------------------------------
def test_clauses_come_back_in_input_order_across_parts_and_chunks(make_part, stub):
    """`run_calls` preserves INPUT order, not completion order. Without that the register would
    be ordered by whichever provider call happened to answer first — different every run."""
    client = stub(RecordingClient())
    parts = [make_part(1, "AAA", 6), make_part(2, "BBB", 6)]
    parsed = s01_ingest.ingest_from_parts(parts, "T")

    headings = [c.heading for c in parsed.clauses]
    # Every clause of part 01 precedes every clause of part 02, whatever order the provider
    # answered in — the stub sleeps, so completion order is genuinely not input order.
    assert headings == sorted(headings)
    assert headings[0].startswith("01 ") and headings[-1].startswith("02 ")
    assert len(parsed.clauses) == len(client.calls)      # one clause per call, none lost


def test_every_clause_carries_its_own_parts_identity(make_part, stub):
    """Stitching by `zip(tasks, results)` has to attach the right part to the right result — an
    off-by-one here would cite the wrong document on every finding."""
    stub(RecordingClient())
    parts = [make_part(1, "AAA", 6), make_part(2, "BBB", 6)]
    parsed = s01_ingest.ingest_from_parts(parts, "T")

    for clause in parsed.clauses:
        # `part_id` is `01-aaa`; the heading the stub echoed back begins `01 Part AAA`.
        assert clause.heading.startswith(clause.part_id.split("-", 1)[0] + " ")


def test_doc_names_keep_first_seen_input_order(make_part, stub):
    stub(RecordingClient())
    parts = [make_part(1, "AAA", 2), make_part(2, "BBB", 2)]
    parsed = s01_ingest.ingest_from_parts(parts, "T")
    assert parsed.documents == [parts[0][1], parts[1][1]]


def test_a_part_with_no_file_contributes_nothing_and_does_not_crash(make_part, stub):
    stub(RecordingClient())
    ghost = (PartSpec(n=9, abbr="GHO", slug="gho", title="Missing", start=1, end=3,
                      category="contract-conditions"), "")
    parsed = s01_ingest.ingest_from_parts([make_part(1, "AAA", 2), ghost], "T")
    assert all(not c.part_id.startswith("09") for c in parsed.clauses)


# ---------------------------------------------------------------------------
# The calls actually overlap
# ---------------------------------------------------------------------------
def test_the_calls_run_concurrently(make_part, stub):
    """The point of the change. A 12-chunk run on a 4-worker pool must show more than one call in
    flight — if `peak` were 1 this would be the sequential loop with extra steps."""
    client = stub(RecordingClient())
    s01_ingest.ingest_from_parts([make_part(1, "AAA", 12)], "T")
    assert len(client.calls) > 1
    assert client.peak > 1


def test_concurrency_is_bounded_at_four(make_part, stub):
    """Not raised. Four is the number already proven against these providers in procurement
    ingest, and DeepSeek's rate limits are not documented — a fan-out that trips a 429 is slower
    than the sequential run it replaced, because every retry is a fresh minute."""
    from pipeline import concurrency

    assert concurrency.MAX_WORKERS == 4
    client = stub(RecordingClient())
    s01_ingest.ingest_from_parts([make_part(1, "AAA", 24)], "T")
    assert client.peak <= 4


# ---------------------------------------------------------------------------
# Progress: honest, monotonic, and per completed call
# ---------------------------------------------------------------------------
def test_progress_is_per_call_and_ends_at_the_total(make_part, stub):
    client = stub(RecordingClient())
    seen: list[tuple[int, int]] = []
    s01_ingest.ingest_from_parts([make_part(1, "AAA", 12)], "T",
                                 count_cb=lambda d, t: seen.append((d, t)))
    total = len(client.calls)
    assert seen[0] == (0, total)              # the denominator, before any call
    assert seen[-1] == (total, total)
    assert {t for _d, t in seen} == {total}   # never contradicted mid-run


def test_progress_never_goes_backwards(make_part, stub):
    """Written from four threads under a lock. Without it two completions could interleave and
    report 5 after 6, which reads as the run losing work."""
    stub(RecordingClient())
    seen: list[int] = []
    s01_ingest.ingest_from_parts([make_part(1, "AAA", 24)], "T",
                                 count_cb=lambda d, _t: seen.append(d))
    assert seen == sorted(seen)


def test_the_denominator_is_calls_not_parts(make_part, stub):
    stub(RecordingClient())
    seen: list[tuple[int, int]] = []
    s01_ingest.ingest_from_parts([make_part(1, "AAA", 12), make_part(2, "BBB", 12)], "T",
                                 count_cb=lambda d, t: seen.append((d, t)))
    assert seen[0][1] > 2


# ---------------------------------------------------------------------------
# One bad chunk is a gap, never a crash
# ---------------------------------------------------------------------------
def test_one_failing_chunk_yields_a_gap_not_an_exception(make_part, stub):
    """`run_calls` re-raises the first exception `map` sees, so `_structure`'s swallow MUST stay
    inside the worker. If it moved outside, one unreadable chunk of one part would lose the whole
    document set — which is precisely the failure the swallow was written for."""
    client = stub(RecordingClient(fail_on="p3 "))
    parsed = s01_ingest.ingest_from_parts([make_part(1, "AAA", 12)], "T")
    assert len(parsed.clauses) == len(client.calls) - 1     # exactly one gap
    assert parsed.clauses                                    # and the rest survived


def test_a_failing_chunk_still_advances_the_bar(make_part, stub):
    """Progress counts calls COMPLETED, not calls that succeeded. A bar that stalls on a failure
    reports the run as hung when it is merely lossy — and the gap is reported elsewhere."""
    client = stub(RecordingClient(fail_on="p3 "))
    seen: list[tuple[int, int]] = []
    s01_ingest.ingest_from_parts([make_part(1, "AAA", 12)], "T",
                                 count_cb=lambda d, t: seen.append((d, t)))
    assert seen[-1] == (len(client.calls), len(client.calls))


# ---------------------------------------------------------------------------
# The skip-list is untouched by the restructure
# ---------------------------------------------------------------------------
def test_skipped_parts_are_still_reported_and_still_not_read(make_part, stub):
    client = stub(RecordingClient())
    notes: list[str] = []
    parts = [make_part(1, "BQ", 6, category="pricing"), make_part(2, "CC", 6)]
    s01_ingest.ingest_from_parts(parts, "T", on_note=notes.append)
    assert any("were NOT read for contractual positions" in n for n in notes)
    assert all("BQ p" not in body for body in client.calls)


def test_a_deferred_specification_still_produces_its_own_note(make_part, stub):
    stub(RecordingClient())
    notes: list[str] = []
    parts = [make_part(1, "PS", 4, category="specifications"), make_part(2, "CC", 4)]
    s01_ingest.ingest_from_parts(parts, "T", on_note=notes.append,
                                 skip_categories=s01_ingest.skip_set())
    assert any("read only on request" in n for n in notes)
