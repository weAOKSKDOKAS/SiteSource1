"""The manifest defects, all six reproduced on CEDD ND/2025/04 — 26 pages, nine bills.

The night's shape: the planning call returned ONE part bounded 1-1 for a 26-page document. Every
bounds check passed (1 >= 1, 1 <= 26, 1 >= 1). The coverage walk saw no pairs, so it reported
**0 gaps**. `validate` called the shortfall a warning, so the screen offered a green Approve over
a manifest that threw away 25 of 26 pages. Then "Edit page bounds" had nothing behind it and the
approval could not be undone, so the split was repaired by hand over PowerShell.

Each test here fails on the code as it was, for the reason named in its docstring.
"""

import pytest

from client_boq.ingest import pdfops
from client_boq.models import PartSpec, SplitManifest

PAGES = 26


def _manifest(parts, pages=PAGES, source="ND-2025-04.pdf"):
    return SplitManifest(source_doc=source, pages=pages, parts=parts)


def _part(n, start, end, **kw):
    return PartSpec(n=n, title=kw.pop("title", f"Part {n}"), start=start, end=end, **kw)


# -- B1: coverage() walked only consecutive pairs -----------------------------------------------
def test_the_tail_of_the_document_is_a_gap():
    """The night's manifest exactly: one part, page 1 of 26. `zip(ordered, ordered[1:])` over a
    single part yields nothing, so the walk reported zero gaps over 25 orphaned pages."""
    report = pdfops.coverage(_manifest([_part(1, 1, 1)]), PAGES)
    assert report["gaps"] == [{"start": 2, "end": 26}]
    assert report["covered_pages"] == 1


def test_the_head_of_the_document_is_a_gap():
    """Pages orphaned BEFORE the first part were equally invisible — the walk starts at the first
    part, so nothing above it was ever anyone's business."""
    report = pdfops.coverage(_manifest([_part(1, 5, 26)]), PAGES)
    assert report["gaps"] == [{"start": 1, "end": 4}]


def test_head_interior_and_tail_gaps_are_all_reported_in_page_order():
    report = pdfops.coverage(_manifest([_part(1, 3, 8), _part(2, 12, 20)]), PAGES)
    assert report["gaps"] == [
        {"start": 1, "end": 2}, {"start": 9, "end": 11}, {"start": 21, "end": 26},
    ]


def test_the_tail_is_measured_from_the_furthest_end_not_the_last_to_begin():
    """The parts are ordered by START. A part that begins earlier can still end later, and taking
    `ordered[-1].end` would invent a gap over pages another part already covers."""
    report = pdfops.coverage(_manifest([_part(1, 1, 26), _part(2, 4, 6)]), PAGES)
    assert report["gaps"] == []


def test_a_full_cover_still_reports_no_gaps():
    report = pdfops.coverage(_manifest([_part(1, 1, 10), _part(2, 11, 26)]), PAGES)
    assert report["gaps"] == [] and report["covered_pages"] == 26


def test_covered_pages_counts_a_page_once_however_many_parts_claim_it():
    """`covered` sums the parts' own lengths and double-counts an overlap; the figure the gate
    judges on must not — a manifest that covers page 4 twice has not covered five pages."""
    report = pdfops.coverage(_manifest([_part(1, 1, 6), _part(2, 4, 26)]), PAGES)
    assert report["covered"] == 6 + 23        # unchanged: callers depend on this
    assert report["covered_pages"] == 26      # the honest one


def test_covered_pages_is_clamped_to_the_real_document():
    report = pdfops.coverage(_manifest([_part(1, 1, 999)]), PAGES)
    assert report["covered_pages"] == 26


# -- B2 / B3: coverage far below the document is an error ---------------------------------------
def test_one_page_of_twenty_six_is_refused_not_warned():
    """The whole defect in one line: this manifest was offered with a green Approve button."""
    errors, _warnings = pdfops.validate(_manifest([_part(1, 1, 1)]), PAGES)
    assert errors and "cover only 1 of 26 pages" in errors[0]


def test_the_refusal_says_the_share_and_what_to_do():
    errors, _ = pdfops.validate(_manifest([_part(1, 1, 1)]), PAGES)
    assert "(4%)" in errors[0] and "Edit the page ranges" in errors[0]


def test_a_near_miss_is_still_only_a_warning():
    """A stray unassigned divider page is recoverable and the human gate exists to weigh it.
    Turning that into a hard refusal would block real work to catch a fault of a different size."""
    errors, warnings = pdfops.validate(_manifest([_part(1, 1, 12), _part(2, 14, 26)]), PAGES)
    assert errors == []
    assert any("Pages 13-13 belong to no part" in w for w in warnings)


def test_the_threshold_is_the_documented_one():
    """Pinned so the constant cannot drift without this test saying so. 60% of 26 is 15.6, so 15
    pages is under and 16 is over."""
    assert pdfops.MIN_COVERAGE_SHARE == 0.6
    assert pdfops.validate(_manifest([_part(1, 1, 15)]), PAGES)[0] != []
    assert pdfops.validate(_manifest([_part(1, 1, 16)]), PAGES)[0] == []


def test_a_loose_annex_is_not_judged_against_the_binder():
    """The binder filter has to survive the new check: an annex uploaded beside the binder has its
    own page numbering and cannot contribute to — or be measured by — the binder's coverage."""
    m = _manifest([_part(1, 1, 26), _part(2, 1, 400, source_doc="annex.pdf")])
    assert pdfops.validate(m, PAGES) == ([], [])


def test_the_whole_document_fallback_covers_the_whole_document():
    """B3 at its source. Tier 4 is a degraded SUCCESS — the document still ingests — but a
    whole-document fallback that covers one page of 26 is not a fallback, it is data loss."""
    parts, tier, _reason = pdfops.plan_draft(
        doc=None, n_pages=PAGES, nodes=[], page_chars=[0] * PAGES, toc_text="",
    )
    assert tier == pdfops.TIER_WHOLE
    assert len(parts) == 1 and (parts[0].start, parts[0].end) == (1, PAGES)
    assert pdfops.validate(_manifest(parts), PAGES)[0] == []


def test_a_planner_stub_is_rejected_and_the_deterministic_draft_stands():
    """The end-to-end consequence, at the seam that actually failed: `plan_split` keeps the
    deterministic draft when the proposal does not validate. Before the coverage check the stub
    validated clean and REPLACED a correct 1-26 draft."""
    from client_boq.models import InspectReport, PlannedSplit

    draft = _manifest([_part(1, 1, PAGES, title="Whole document (not split)")])
    report = InspectReport(filename="ND-2025-04.pdf", pages=PAGES, draft=draft,
                           page_chars=[500] * PAGES)
    stub = PlannedSplit(parts=[PartSpec(n=1, abbr="ALL", title="Bills of Quantities")])  # 1-1

    import client_boq.ingest.s01_plan_split as planner

    class _Stub:
        def complete_json(self, **_kw):
            return stub

    kept = _plan_with(planner, _Stub(), report)
    assert [(p.start, p.end) for p in kept.parts] == [(1, PAGES)]
    assert "does not fit the document" in kept.tier_reason


def _plan_with(planner, client, report):
    """Run `plan_split` against a stubbed model client — no fixture, no network."""
    real = planner.make_client
    planner.make_client = lambda: client
    try:
        return planner.plan_split(report)
    finally:
        planner.make_client = real


# -- B5: an approved manifest reopens when a new draft replaces it -------------------------------
def test_a_new_upload_reopens_the_gate_it_replaces(tmp_path, monkeypatch):
    """`save_manifest` preserves the approval flag on purpose — re-PLANNING the same document must
    not move a gate a human set. But a new upload is not a re-plan: it replaces the draft, and
    carrying the old approval forward would leave a manifest nobody has read already past its
    gate."""
    from client_boq import store
    from client_boq.ingest import run as ingest_run

    data = _pdf(PAGES)
    conn = store.get_conn()
    try:
        first = ingest_run.run_inspect([("ND-2025-04.pdf", "application/pdf", data)], "ND 2025 04")
        store.approve_manifest(conn, first.set_id, True)
        assert store.manifest_is_approved(conn, first.set_id) is True

        notes: list[str] = []
        ingest_run.run_inspect([("ND-2025-04.pdf", "application/pdf", data)], "ND 2025 04",
                               on_note=notes.append)
        assert store.manifest_is_approved(conn, first.set_id) is False
    finally:
        conn.close()
    assert notes and "not a new tender" in notes[0]
    assert "reopens that gate" in notes[0]


def test_a_genuinely_new_set_says_nothing(tmp_path):
    from client_boq.ingest import run as ingest_run

    notes: list[str] = []
    ingest_run.run_inspect([("Fresh.pdf", "application/pdf", _pdf(4))], "Fresh Tender",
                           on_note=notes.append)
    assert notes == []


def _pdf(pages: int) -> bytes:
    fitz = pytest.importorskip("fitz")
    doc = fitz.open()
    for i in range(pages):
        doc.new_page().insert_text((60, 80), f"page {i + 1} of {pages}", fontsize=11)
    out = doc.tobytes()
    doc.close()
    return out
