"""The scope split reports progress through its long phase, not only its short one.

Observed live: 199 seconds with `stage` stuck at `splitting` and `done`/`total` both 0, then
completion. The job no longer blocks the server — that half worked — but the operator was blind for
the whole run and could not tell work from a hang.

The counts existed the whole time. `ingest_tender` has taken a `progress_cb(done, total)` since it
was written, ticking once per extraction unit ON COMPLETION, and `bridge/scope.py` never passed it.
The only counted phase was the indexing loop AFTER extraction — the short one.

One thing this deliberately does NOT claim: a cancel during extraction. `run_calls` submits every
unit to one `pool.map`, whose context manager waits for every future regardless, so raising there
would stop nothing and would report "stopped before indexing" after a full-price run. The cancel
that takes effect stays on the indexing loop, where the work is a plain sequential loop — asserted
below so the boundary is a fact, not a hope.
"""

import pytest

from bridge import parts as parts_mod
from bridge import scope as scope_mod
from client_boq import jobs
from schemas.models import ScopePackages, SorItem, TradeWorkPackage

fitz = pytest.importorskip("fitz")

SET_ID = "gi-2026-16"


@pytest.fixture
def make_pdf(tmp_path):
    def _make(name: str, pages: list[str]) -> str:
        doc = fitz.open()
        for body in pages:
            page = doc.new_page()
            y = 70
            for line in body.splitlines():
                page.insert_text((55, y), line, fontsize=10)
                y += 14
        path = tmp_path / name
        doc.save(str(path))
        doc.close()
        return str(path)

    return _make


class StubClient:
    """Layer 2, scripted — one call per extraction unit, exactly as the live path makes."""

    def __init__(self):
        self.calls = 0

    def complete_json(self, *, system, user, target_model, **_kw):
        self.calls += 1
        return ScopePackages(project_name="GI/2026/16", packages=[TradeWorkPackage(
            trade="ground_investigation", scope_summary="GI",
            sor_items=[SorItem(item_ref="G1", description="Borehole", unit="m", qty=10.0,
                               section="G")])])


def _bill_pages(n_rows: int) -> list[str]:
    """A bill long enough to chunk into SEVERAL extraction units — the case the strip was blind to."""
    rows = [f"G{i}   Cable percussion borehole in soil, depth stage {i}   m   {i * 10}"
            for i in range(1, n_rows + 1)]
    return ["SECTION G : DRILLING AND SAMPLING\n" + "\n".join(rows[i:i + 20])
            for i in range(0, len(rows), 20)]


@pytest.fixture
def a_set(make_set, part_spec, make_pdf, tmp_path, monkeypatch):
    monkeypatch.setenv("SITESOURCE_WORKDIR", str(tmp_path / "ws"))
    pages = _bill_pages(120)
    specs = [
        part_spec(1, "SR", "Schedule of Rates", "pricing", end=len(pages)),
        part_spec(2, "PS", "Particular Specification", "specifications", end=1),
        part_spec(3, "CL", "Clarification", "correspondence", end=1),
    ]
    paths = {
        specs[0].part_id: make_pdf("bill.pdf", pages),
        specs[1].part_id: make_pdf("spec.pdf", ["SECTION 3 : GROUND INVESTIGATION\n3.1 Boring."]),
        specs[2].part_id: make_pdf("clar.pdf", ["Clarification No. 1"]),
    }
    make_set(SET_ID, "Contract No. GI/2026/16", specs, pdf_paths=paths)
    parts_mod.confirm_bill_parts(SET_ID, [specs[0].part_id])
    return SET_ID


def _run(set_id, monkeypatch):
    """Both counted channels, kept apart exactly as the job wires them.

    `extract_cb` is a SEPARATE parameter from `count_cb` on purpose: they count different
    populations against different denominators, and a caller reading document progress must not
    silently start receiving chunk progress on the same channel.
    """
    client = StubClient()
    monkeypatch.setattr("pipeline.stage_01_ingest.ingest.LLMClient", lambda *a, **k: client)
    stages: list[str] = []
    extract: list[tuple[int, int]] = []
    indexed: list[tuple[int, int]] = []
    scope_mod.scope_from_set(
        set_id, progress_cb=stages.append,
        extract_cb=lambda d, t: extract.append((d, t)),
        count_cb=lambda d, t: indexed.append((d, t)),
    )
    return stages, extract, indexed, client


# -- the long phase is counted ------------------------------------------------------------------------
def test_the_splitting_stage_counts_its_extraction_units(a_set, monkeypatch):
    """The 199 seconds. `done`/`total` were 0/0 for the whole of it; now they move."""
    stages, extract, _indexed, client = _run(a_set, monkeypatch)

    assert stages == ["reading", "splitting", "indexing"]
    assert client.calls > 1, "the fixture must chunk, or this asserts nothing"
    # The denominator is known from the FIRST tick — 0/N, never 0/0.
    assert extract[0] == (0, client.calls)
    # ...and it reaches N/N.
    assert extract[-1] == (client.calls, client.calls)


def test_progress_is_monotonic_within_each_phase_and_ends_at_n_over_n(a_set, monkeypatch):
    """Monotonic WITHIN a phase, which is the only place it can be.

    Extraction counts units and indexing counts documents — two populations with two denominators,
    so the sequence restarts when the stage does. That is not a bar going backwards: `_stage_cb`
    clears `done`/`total` at every stage boundary for exactly this reason ("the previous stage's
    8/8 must not be left standing over a stage that has not counted anything yet"), so the strip
    shows 6/6, then nothing, then 1/3.
    """
    _stages, extract, indexed, _client = _run(a_set, monkeypatch)

    for name, counts in (("extraction", extract), ("indexing", indexed)):
        assert counts, f"{name} reported nothing at all"
        done = [d for d, _t in counts]
        assert done == sorted(done), f"{name} went backwards: {done}"
        assert counts[-1][0] == counts[-1][1], f"{name} ended at {counts[-1]}, not complete"
        assert counts[-1][1] > 0
        assert len({t for _d, t in counts}) == 1, f"{name}'s denominator moved mid-phase"


def test_the_indexing_stage_still_counts_documents_after_extraction(a_set, monkeypatch):
    """Two counted phases, each with its own denominator: units, then documents."""
    _stages, extract, indexed, client = _run(a_set, monkeypatch)

    # Bill + spec + clarification; drawings are never indexed. Unchanged by the new channel — the
    # existing `test_scope_job.py` assertion on this exact sequence still holds, unedited.
    assert indexed == [(1, 3), (2, 3), (3, 3)]
    assert extract[-1][1] == client.calls != 3, "the two channels must not be the same count"


def test_a_tick_reports_completed_work_never_work_about_to_start(a_set, monkeypatch):
    _stages, extract, indexed, _client = _run(a_set, monkeypatch)
    assert all(0 <= d <= t for d, t in extract + indexed)
    # Indexing counts only COMPLETED documents, so it never reports a bare zero the way the
    # extraction phase does when it announces its denominator.
    assert indexed[0][0] == 1


# -- the cancel boundary, stated as it actually is -----------------------------------------------------
def test_a_cancel_lands_at_a_document_boundary_in_the_indexing_loop(a_set, monkeypatch):
    client = StubClient()
    monkeypatch.setattr("pipeline.stage_01_ingest.ingest.LLMClient", lambda *a, **k: client)
    seen: list[tuple[int, int]] = []

    def _cb(done: int, total: int) -> None:
        seen.append((done, total))
        if done == 2:
            raise jobs.JobCancelled("indexing")

    with pytest.raises(jobs.JobCancelled):
        scope_mod.scope_from_set(a_set, count_cb=_cb)
    assert seen == [(1, 3), (2, 3)]               # stopped there, did not index the third


def test_no_progress_callback_at_all_still_runs(a_set, monkeypatch):
    """Both hooks are optional — the endpoint's DEMO path passes neither."""
    client = StubClient()
    monkeypatch.setattr("pipeline.stage_01_ingest.ingest.LLMClient", lambda *a, **k: client)
    scope, _unrecognised = scope_mod.scope_from_set(a_set)
    assert scope.packages
