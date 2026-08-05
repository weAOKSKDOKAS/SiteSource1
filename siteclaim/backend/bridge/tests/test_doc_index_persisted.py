"""FIX 10 — the bridge built a document index and threw it away, so dispatch could never slice.

``bridge/scope.py`` built a ``doc_index`` over the confirmed bill parts, read ``sor_section_pages``
off it for the provenance guard, and discarded the entries. ``save_doc_index`` had exactly ONE call
site in the whole codebase — ``api.py``'s ``/ingest-upload`` — which an archive/bridge tender never
touches. So ``drafts.load_doc_index`` returned ``[]``, and ``relevant_docs``' ``if not sr_entries``
fired **unconditionally** for every tender that entered this way.

**This corrects FIX 9.** That fix concluded the slice was impossible because the bill arrived as a
workbook. The workbook was real and irrelevant: the pack ships ``I-ND_2025_04_BQ-0.pdf`` beside
``E-ND_2025_04_BQ-0.xlsx``, and the PDF would have been discarded exactly the same way. The cause
was persistence, not format.

And it is not only the SoR. ``relevant_docs`` iterates ``doc_index`` for the directed PS search,
the onward-appendix pre-pass, and the main assembly loop — so an empty index means no PS, no Method
of Measurement, no clarification and no General Specification either. The enquiry went out carrying
one attachment: the generated sheet. Which is what was observed.

**These are FIXTURES.** The real pack is 232 MB and not in this repo; every PDF below is built here
to model the shape (line-start ``SECTION n`` markers, which is what ``_sor_section_markers``
matches). Counts and branches reported from them are facts about the fixture.
"""

import pytest
from bridge import parts as parts_mod
from bridge import scope as scope_mod
from pipeline.stage_01_ingest.doc_index import load_doc_index
from pipeline.workspace import Workspace

SET_ID = "nd-2025-04"


@pytest.fixture(autouse=True)
def _isolated_workspace(tmp_path, monkeypatch):
    """A throwaway workspace per test.

    `bridge/tests/conftest.py` isolates SITESOURCE_DB but not SITESOURCE_WORKDIR, so every test in
    this package shares one workspace on disk — and a doc_index written by one test is visible to
    the next. These tests assert on the ABSENCE of an index as well as its presence, so they need
    the isolation the package default does not give them.
    """
    monkeypatch.setenv("SITESOURCE_WORKDIR", str(tmp_path / "work"))


def _sor_pdf(sections=("1", "2", "3")) -> bytes:
    """A Bill of Quantities with line-start ``SECTION n`` headers — what `_sor_section_markers`
    matches, and the only thing that produces `sor_section_pages`."""
    fitz = pytest.importorskip("fitz")
    doc = fitz.open()
    for code in sections:
        page = doc.new_page()
        page.insert_text((40, 50), f"SECTION {code} : GROUND INVESTIGATION", fontsize=11)
        for n in range(6):
            page.insert_text((40, 80 + n * 16), f"{code}.{n + 1}  Priced item {n + 1}", fontsize=9)
    out = doc.tobytes()
    doc.close()
    return out


class StubClient:
    """Layer 2, scripted. The split itself is not what these tests are about."""

    def __init__(self, scope):
        self._scope = scope

    def complete_json(self, *, system, user, target_model, **_kw):
        return self._scope


@pytest.fixture
def nd_set(make_set, part_spec, tmp_path):
    """A bridge set whose confirmed bill is a PDF — the case FIX 9 wrongly excluded."""
    from schemas.models import ScopePackages, SectionMeta, SorItem, TradeWorkPackage

    path = tmp_path / "I-ND_2025_04_BQ-0.pdf"
    path.write_bytes(_sor_pdf())
    make_set(SET_ID, "Contract No. ND/2025/04",
             [part_spec(1, "BQ", "BQ/I-ND_2025_04_BQ-0.pdf", "pricing", start=1, end=3)],
             pdf_paths={"01-bq": str(path)})
    parts_mod.confirm_bill_parts(SET_ID, ["01-bq"])

    scope = ScopePackages(project_name="Contract No. ND/2025/04", packages=[TradeWorkPackage(
        trade="ground_investigation", scope_summary="Ground investigation",
        sor_items=[SorItem(item_ref=f"{s}.{i}", description=f"Priced item {i}", unit="m", qty=1.0,
                           section=s) for s in ("1", "2", "3") for i in (1, 2)],
        sections=[SectionMeta(code=s, item_count=2) for s in ("1", "2", "3")])])
    return scope


# ---------------------------------------------------------------------------
# The defect: nothing was ever written
# ---------------------------------------------------------------------------
def test_the_bridge_now_writes_a_doc_index(nd_set):
    ws = Workspace()
    assert load_doc_index(ws, SET_ID) == []          # nothing before the split
    scope_mod.scope_from_set(SET_ID, client=StubClient(nd_set))
    assert load_doc_index(ws, SET_ID)                # and something after it


def test_it_lands_under_the_slug_dispatch_loads_from(nd_set):
    """`doc_index_path` resolves through `Workspace.tender_dir` -> `root / tender_slug(id)`, and
    `tender_slug` is idempotent — so writing under the set_id and loading under the scope's
    human-readable `project_name` reach the same file. That equivalence is the whole fix: without
    it, persisting the index would still leave dispatch reading an empty one."""
    scope_mod.scope_from_set(SET_ID, client=StubClient(nd_set))
    ws = Workspace()
    by_set = load_doc_index(ws, SET_ID)
    by_name = load_doc_index(ws, "Contract No. ND/2025/04")   # what /dispatch/plan is given
    assert by_set and [e.filename for e in by_set] == [e.filename for e in by_name]


def test_the_persisted_entry_carries_the_section_pages(nd_set):
    scope_mod.scope_from_set(SET_ID, client=StubClient(nd_set))
    entry = next(e for e in load_doc_index(Workspace(), SET_ID) if e.kind == "schedule_of_rates")
    assert entry.text_layer is True
    assert sorted(entry.sor_section_pages) == ["1", "2", "3"]


# ---------------------------------------------------------------------------
# What dispatch does with it — the branch, named
# ---------------------------------------------------------------------------
def _plan_for(package_key="ground_investigation:2"):
    from pipeline.stage_03_dispatch.drafts import plan_for_firms

    return plan_for_firms(
        None, {package_key: ["F1"]}, tender_id="Contract No. ND/2025/04",
    )[package_key]


def test_before_the_fix_the_plan_is_only_the_generated_sheet():
    """The observed draft: ONE attachment. An empty index disables the whole assembler, not just
    the SoR branch — no PS, no Method of Measurement, no clarification, no General Specification."""
    from pipeline.stage_03_dispatch.relevant_docs import SUBSTITUTED

    plan = _plan_for()                                # nothing persisted in this test
    assert len(plan.attachments) == 1
    assert plan.attachments[0].mode == "generated"
    assert SUBSTITUTED in plan.attachments[0].flags


def test_after_the_fix_the_sor_is_sliced_to_the_units_section(nd_set):
    """`ground_investigation:2` — the package the brief names. `sr_entries` is non-empty, `hit`
    resolves (text_layer true AND "2" present in sor_section_pages), and the SLICED branch fires."""
    from pipeline.stage_03_dispatch.relevant_docs import PRICED_RETURN, SUBSTITUTED

    scope_mod.scope_from_set(SET_ID, client=StubClient(nd_set))
    plan = _plan_for("ground_investigation:2")
    sor = next(a for a in plan.attachments if PRICED_RETURN in a.flags)

    assert sor.mode == "sliced"
    assert sor.pages == [2]                           # section 2's own page, 1-based
    assert sor.out_filename.endswith("_Section_2.pdf")
    assert SUBSTITUTED not in sor.flags               # this IS the intended artifact
    assert sor.source_doc.endswith(".pdf")            # the ORIGINAL bill, not the generated sheet


def test_each_section_slices_to_its_own_pages(nd_set):
    """Not one bill sent three times: each unit gets its own section's pages, so a firm cannot
    price a section it was never enquired on."""
    from pipeline.stage_03_dispatch.relevant_docs import PRICED_RETURN

    scope_mod.scope_from_set(SET_ID, client=StubClient(nd_set))
    pages = {}
    for code in ("1", "2", "3"):
        plan = _plan_for(f"ground_investigation:{code}")
        pages[code] = next(a for a in plan.attachments if PRICED_RETURN in a.flags).pages
    assert pages == {"1": [1], "2": [2], "3": [3]}


def test_a_workbook_only_bill_still_writes_no_index(make_set, part_spec, tmp_path):
    """The branch FIX 9 described is still real and still correct — it was simply not what
    happened on the real pack. A workbook has no pages, so there is nothing to index or slice."""
    from schemas.models import ScopePackages

    make_set("wb-only", "Workbook Only",
             [part_spec(1, "BQ", "BQ/E-ND_2025_04_BQ-0.xlsx", "pricing",
                        source_doc="BQ__E-ND_2025_04_BQ-0.xlsx")],
             pdf_paths={"01-bq": ""})
    parts_mod.confirm_bill_parts("wb-only", ["01-bq"])
    with pytest.raises((ValueError, LookupError)):
        scope_mod.scope_from_set(
            "wb-only", client=StubClient(ScopePackages(project_name="Workbook Only", packages=[])))
    assert load_doc_index(Workspace(), "wb-only") == []


# ---------------------------------------------------------------------------
# The scope of what IS indexed — stated, because it bounds the fix
# ---------------------------------------------------------------------------
def test_only_the_confirmed_bill_is_indexed(nd_set):
    """The authorised change is persistence of what the bridge ALREADY builds, and what it builds
    is the CONFIRMED BILL only — that is all the provenance guard ever needed.

    So the SoR slices, and the Particular Specification, Method of Measurement, General
    Specification and clarifications still do NOT appear in the plan: they were never indexed on
    this path. Indexing the context parts is a separate change and is not made here.
    """
    scope_mod.scope_from_set(SET_ID, client=StubClient(nd_set))
    kinds = {e.kind for e in load_doc_index(Workspace(), SET_ID)}
    assert kinds == {"schedule_of_rates"}

    plan = _plan_for("ground_investigation:2")
    assert [a.mode for a in plan.attachments] == ["sliced"]   # one attachment, not five
