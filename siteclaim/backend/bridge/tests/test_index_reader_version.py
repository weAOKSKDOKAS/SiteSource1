"""An index built by older code carries older answers, and nothing said so.

`stale` meant exactly one thing: documents arrived after the index was built. It did not mean the
OTHER cause, which is the one the operator actually hit — **the index was written by a reader that
read documents differently.**

Titles, section numbers and kinds are decided at INDEXING time and written to `doc_index.json`. Six
rounds of fixes changed what that produces:

* the PS Index naming every specification section, so a title match has a specification side at all
* the amendment lead-in that made `SMM_S28-0.pdf` index itself as section **27**
* PS 1 quoting "Standard Method of Measurement" and so taking SMM 1's slot — and *superseding* it
* the bill header whose title came from its own collection footer, wrong for four bills
* a section title read from the running page header (`Technopole (Phase 2)`)

An index written before those still holds every one of those wrong answers. The gate reported
`stale: false` on exactly that index — a true statement about the wrong question — while the
operator's report was "the PS is missing and some documents are not attached".

`save_doc_index` now writes a sidecar naming the reader version. A sidecar rather than a header
inside the file because `load_doc_index` reads a plain list and every reader would have to learn a
new shape; and because its ABSENCE is itself the signal — an index written before versioning is
precisely the one most likely to be stale.
"""

import pytest

from pipeline.stage_01_ingest.doc_index import (
    DOC_INDEX_READER_VERSION,
    DocIndexEntry,
    index_reader_version,
    load_doc_index,
    save_doc_index,
)
from pipeline.workspace import Workspace

ENTRY = DocIndexEntry(filename="BQ/I-ND_2025_04_BQ-0.pdf", kind="schedule_of_rates",
                      text_layer=True, page_count=26, sor_section_pages={"2": [8]})


@pytest.fixture
def ws(monkeypatch, tmp_path):
    monkeypatch.setenv("SITESOURCE_WORKDIR", str(tmp_path))
    return Workspace()


def _meta(ws, tender):
    return ws.doc_index_path(tender).with_name("doc_index.meta.json")


# -- the version is recorded --------------------------------------------------------------------
def test_a_fresh_index_records_the_reader_that_wrote_it(ws):
    save_doc_index(ws, "nd-2025-04", [ENTRY])
    assert index_reader_version(ws, "nd-2025-04") == DOC_INDEX_READER_VERSION


def test_an_index_written_before_versioning_reports_none(ws):
    """The real case. Every index on the operator's disk predates this, and `None` is what says so
    — not an absence to be shrugged at."""
    save_doc_index(ws, "nd-2025-04", [ENTRY])
    _meta(ws, "nd-2025-04").unlink()
    assert index_reader_version(ws, "nd-2025-04") is None


def test_a_corrupt_sidecar_reads_as_unversioned_rather_than_raising(ws):
    save_doc_index(ws, "nd-2025-04", [ENTRY])
    _meta(ws, "nd-2025-04").write_text("{not json", encoding="utf-8")
    assert index_reader_version(ws, "nd-2025-04") is None


def test_no_index_at_all_reports_none(ws):
    assert index_reader_version(ws, "never-split") is None


# -- the index itself is unchanged ------------------------------------------------------------------
def test_the_index_file_keeps_its_plain_list_shape(ws):
    """The reason it is a sidecar: `load_doc_index` reads a list, and every reader would otherwise
    have to learn a wrapper to answer a question a second small file answers."""
    import json

    save_doc_index(ws, "nd-2025-04", [ENTRY])
    on_disk = json.loads(ws.doc_index_path("nd-2025-04").read_text(encoding="utf-8"))

    assert isinstance(on_disk, list) and on_disk[0]["filename"] == ENTRY.filename
    assert [e.filename for e in load_doc_index(ws, "nd-2025-04")] == [ENTRY.filename]


def test_an_unversioned_index_still_loads(ws):
    """Reporting it as outdated must not stop it being read — the operator can still see what is
    there while they re-split."""
    save_doc_index(ws, "nd-2025-04", [ENTRY])
    _meta(ws, "nd-2025-04").unlink()
    assert len(load_doc_index(ws, "nd-2025-04")) == 1


# -- what the gate says ------------------------------------------------------------------------------
def test_an_outdated_index_is_reported_stale_with_its_reason(ws, monkeypatch):
    from bridge import doc_index_state as mod

    save_doc_index(ws, "nd-2025-04", [ENTRY])
    _meta(ws, "nd-2025-04").unlink()          # written by an older reader
    state = mod.doc_index_state("nd-2025-04")

    assert state["exists"] is True
    assert state["stale"] is True, "an index built by an older reader is stale"
    assert state["reader_version"] is None
    assert state["current_reader_version"] == DOC_INDEX_READER_VERSION
    assert "reader version" in state["stale_reason"]
    assert "re-run the scope split" in state["stale_reason"].lower()


def test_a_current_index_with_nothing_added_is_not_stale(ws):
    from bridge import doc_index_state as mod

    save_doc_index(ws, "nd-2025-04", [ENTRY])
    state = mod.doc_index_state("nd-2025-04")

    assert state["stale"] is False and state["stale_reason"] == ""
    assert state["warning"] == ""
    assert state["reader_version"] == DOC_INDEX_READER_VERSION


def test_the_warning_names_the_older_reader_and_what_it_costs(ws):
    from bridge import doc_index_state as mod

    save_doc_index(ws, "nd-2025-04", [ENTRY])
    _meta(ws, "nd-2025-04").unlink()
    warning = mod.doc_index_state("nd-2025-04")["warning"]

    assert "OLDER READER" in warning
    assert "nd-2025-04" in warning
    for cost in ("missing", "stale title", "wrong section number"):
        assert cost in warning, warning


def test_the_documents_added_sentence_is_unchanged(ws):
    """That wording is pinned by `test_doc_index_gate.py` and a reader already recognises it. The
    older-reader sentence is appended beside it, never in place of it."""
    from bridge import doc_index_state as mod

    save_doc_index(ws, "nd-2025-04", [ENTRY])
    state = mod.doc_index_state("nd-2025-04")
    assert state["stale"] is False, "nothing added, current reader — the baseline for the above"


def test_the_version_is_an_integer_that_can_only_move_forward():
    """A bump is a deliberate act: it says 'indexing produces something different now'. Guarding the
    type keeps a string or a date from being dropped in, where `<` would compare wrongly."""
    assert isinstance(DOC_INDEX_READER_VERSION, int) and DOC_INDEX_READER_VERSION >= 1
