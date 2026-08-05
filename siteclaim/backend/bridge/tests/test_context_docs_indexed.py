"""FIX 1 — the enquiry carries its documents, not just a sheet.

The bridge indexed the confirmed bill and nothing else. ``relevant_docs`` iterates the persisted
``doc_index`` for EVERY kind it attaches, so a bill-only index meant the plan could contain a
Schedule of Rates and nothing more: no Particular Specification, no Method of Measurement, no
General Specification, no addendum. The observed draft carried one attachment.

Two things had to change together, and neither is a new classifier:

* the CONTEXT parts are indexed alongside the bill, under the same tender slug;
* ``_kind_for`` learned to recover ``method_of_measurement`` and ``clarification`` from page 1 or
  the filename. It already recovered ``general_specification`` and ``appendix`` that way; those two
  were reachable ONLY from an explicit DocType, so a bridge part could never become one. The SMM
  ships in ``GP&PP/`` categorised ``specifications`` — which maps to PARTICULAR_SPECIFICATION — so
  without the page-1 recovery it would index as a PS and the preamble slice could never fire.

**These are FIXTURES.** The real pack is 232 MB and not in this repo. Every PDF here is built to
model the shape the indexer keys on — line-start ``SECTION n`` markers, clause ids, the SMM title.
Counts and branches reported from them are facts about the fixture.
"""

import pytest
from bridge import parts as parts_mod
from bridge import scope as scope_mod
from pipeline.stage_01_ingest.doc_index import load_doc_index
from pipeline.workspace import Workspace
from schemas.models import ScopePackages, SectionMeta, SorItem, TradeWorkPackage

SET_ID = "nd-2025-04"
NAME = "Contract No. ND/2025/04"


@pytest.fixture(autouse=True)
def _isolated_workspace(tmp_path, monkeypatch):
    monkeypatch.setenv("SITESOURCE_WORKDIR", str(tmp_path / "work"))


def _pdf(lines_by_page: list[list[str]]) -> bytes:
    fitz = pytest.importorskip("fitz")
    doc = fitz.open()
    for lines in lines_by_page:
        page = doc.new_page()
        for n, text in enumerate(lines):
            page.insert_text((40, 50 + n * 16), text, fontsize=9)
    out = doc.tobytes()
    doc.close()
    return out


def _sor_pdf():
    return _pdf([
        [f"SECTION {c} : GROUND INVESTIGATION"] + [f"{c}.{i} Priced item {i}" for i in (1, 2)]
        for c in ("1", "2", "3")
    ])


def _ps_pdf(section="7"):
    """A Particular Specification whose clause ids the SoR items reference."""
    return _pdf([
        [f"SECTION {section} : PARTICULAR SPECIFICATION — GROUND INVESTIGATION"],
        [f"{section}.01  Boring and drilling", "Requirements for cable percussion boring."],
        [f"{section}.02  Sampling", "Requirements for undisturbed sampling."],
        [f"{section}.03  Instrumentation", "Standpipe piezometer installation."],
    ])


def _smm_pdf():
    """The Standard Method of Measurement — the GP&PP folder's SMM files."""
    return _pdf([
        ["Standard Method of Measurement for Civil Engineering Works"],
        ["PB 71  Boreholes shall be measured by depth."],
        ["PB 72  Sampling shall be measured by number."],
    ])


def _gs_pdf():
    return _pdf([["General Specification for Civil Engineering Works"], ["Clause 1.01 General."]])


def _addendum_pdf():
    return _pdf([["Tender Addendum No. 1"], ["Clarification to the Conditions of Tender."]])


class StubClient:
    def __init__(self, scope):
        self._scope = scope

    def complete_json(self, *, system, user, target_model, **_kw):
        return self._scope


def _scope() -> ScopePackages:
    """SoR items that CITE the PS and the SMM, because the slicer works off the Clause Ref."""
    return ScopePackages(project_name=NAME, packages=[TradeWorkPackage(
        trade="ground_investigation", scope_summary="Ground investigation",
        sor_items=[
            SorItem(item_ref="2.1", description="Cable percussion borehole", unit="m", qty=100.0,
                    section="2", clause_refs=["PS 7.01", "PB 71"]),
            SorItem(item_ref="2.2", description="Undisturbed sampling", unit="nr", qty=40.0,
                    section="2", clause_refs=["PS 7.02"]),
            SorItem(item_ref="1.1", description="Preliminaries", unit="item", qty=1.0, section="1"),
        ],
        sections=[SectionMeta(code="1", item_count=1), SectionMeta(code="2", item_count=2)])])


@pytest.fixture
def nd_set(make_set, part_spec, tmp_path):
    """The pack in miniature: a PDF bill, a PS section, the SMM, a GS, an addendum, a drawing."""
    files = {
        "01-bq": ("BQ/I-ND_2025_04_BQ-0.pdf", "pricing", _sor_pdf()),
        "02-ps7": ("S/PS/PS7/PS-S07.pdf", "specifications", _ps_pdf("7")),
        "03-smm": ("GP&PP/SMM_Civil.pdf", "specifications", _smm_pdf()),
        "04-gs": ("GP&PP/General_Spec.pdf", "specifications", _gs_pdf()),
        "05-ta": ("TA #1/Tender_Addendum_1.pdf", "other", _addendum_pdf()),
        "06-drg": ("DRG/GA-01.pdf", "drawings", _pdf([["drawing"]])),
    }
    specs, paths = [], {}
    for n, (pid, (title, category, data)) in enumerate(files.items(), start=1):
        path = tmp_path / f"{pid}.pdf"
        path.write_bytes(data)
        abbr = pid.split("-", 1)[1].upper()
        specs.append(part_spec(n, abbr, title, category, start=1, end=3))
        paths[f"{n:02d}-{abbr.lower()}"] = str(path)
    make_set(SET_ID, NAME, specs, pdf_paths=paths)
    parts_mod.confirm_bill_parts(SET_ID, [specs[0].part_id])
    return _scope()


def _split(nd_set, notes=None):
    return scope_mod.scope_from_set(
        SET_ID, client=StubClient(nd_set), on_error=(notes.append if notes is not None else None))


def _dispatch_scope(package_key="ground_investigation:2") -> ScopePackages:
    """The scope AS DISPATCH RECEIVES IT — one package per routed unit, its ``trade`` set to the
    ``package_key``.

    `Sourcing.tsx` rebuilds it that way before calling `/dispatch/plan` (``trade: p.package_key``),
    and `plan_for_firms` looks the unit up as ``pkg_by_key.get(package_key)``. A fixture that hands
    it the pre-split scope gets ``pkg = None`` and therefore NO items — no Clause Refs, no PS, no
    Method of Measurement. That is a property of the call, not of the index, and it is the reason
    an earlier draft of this test reported an empty plan and looked like a slicer failure.
    """
    section = package_key.split(":", 1)[1] if ":" in package_key else ""
    full = _scope().packages[0]
    items = [i for i in full.sor_items if (i.section or "") == section] if section else full.sor_items
    return ScopePackages(project_name=NAME, packages=[TradeWorkPackage(
        trade=package_key, scope_summary=full.scope_summary, sor_items=items,
        sections=full.sections)])


def _plan(_scope_unused=None, package_key="ground_investigation:2"):
    from pipeline.stage_03_dispatch.drafts import plan_for_firms

    return plan_for_firms(
        _dispatch_scope(package_key), {package_key: ["F1"]}, tender_id=NAME)[package_key]


# ---------------------------------------------------------------------------
# The index now covers the context
# ---------------------------------------------------------------------------
def test_context_parts_reach_the_index(nd_set):
    _split(nd_set)
    kinds = sorted(e.kind for e in load_doc_index(Workspace(), SET_ID))
    assert "schedule_of_rates" in kinds
    assert "particular_specification" in kinds
    assert "method_of_measurement" in kinds
    assert "clarification" in kinds


def test_the_smm_is_a_method_of_measurement_not_a_specification(nd_set):
    """It is categorised `specifications`, which maps to PARTICULAR_SPECIFICATION — so without the
    page-1 recovery it would index as a PS and the preamble slice could never fire."""
    _split(nd_set)
    by_file = {e.filename: e.kind for e in load_doc_index(Workspace(), SET_ID)}
    assert by_file["GP&PP/SMM_Civil.pdf"] == "method_of_measurement"
    assert by_file["S/PS/PS7/PS-S07.pdf"] == "particular_specification"


def test_the_general_specification_is_not_swallowed_by_the_ps_branch(nd_set):
    """It is categorised `specifications` too, so the PS branch claimed it — and a PS entry with no
    section number is skipped by the assembler entirely, so the General Specification reached no
    enquiry at all. Recovered from its page-1 declaration, behind the no-competing-SECTION-header
    guard, so a PS that merely CITES the GS is never stolen."""
    _split(nd_set)
    by_file = {e.filename: e.kind for e in load_doc_index(Workspace(), SET_ID)}
    assert by_file["GP&PP/General_Spec.pdf"] == "general_specification"


def test_a_ps_that_cites_the_general_specification_stays_a_ps(nd_set):
    """The guard, asserted rather than assumed — `_GENERAL_SPEC` is a loose pattern."""
    from pipeline.stage_01_ingest.doc_index import build_doc_entry
    from schemas.models import DocType

    entry = build_doc_entry("PS-S07.pdf", DocType.PARTICULAR_SPECIFICATION, _pdf([
        ["SECTION 7 : PARTICULAR SPECIFICATION"],
        ["7.01 Comply with the General Specification for Civil Engineering Works."],
    ]))
    assert entry.kind == "particular_specification"


def test_the_addendum_becomes_a_clarification(nd_set):
    """Categorised `other` — an addendum is a KIND, not a category — so its page-1 declaration is
    the signal. Clarifications attach to every firm."""
    _split(nd_set)
    by_file = {e.filename: e.kind for e in load_doc_index(Workspace(), SET_ID)}
    assert by_file["TA #1/Tender_Addendum_1.pdf"] == "clarification"


def test_drawings_are_not_indexed(nd_set):
    """Not a guess about content — a declining to index what no consumer reads. `relevant_docs`
    attaches five kinds and a drawing is none of them, while being the most expensive page kind
    there is (raster -> the OCR/word-box path on every page)."""
    _split(nd_set)
    assert "DRG/GA-01.pdf" not in {e.filename for e in load_doc_index(Workspace(), SET_ID)}


def test_the_split_reports_what_it_indexed(nd_set):
    notes: list[str] = []
    _split(nd_set, notes)
    assert any("indexed" in n and "context document" in n for n in notes)


# ---------------------------------------------------------------------------
# The guard still reads the BILL only
# ---------------------------------------------------------------------------
def test_the_provenance_guard_is_not_widened_by_the_context(nd_set):
    """A context part misclassified as a schedule of rates would otherwise contribute section codes
    the bill never declared, and the quarantine would start accepting items on another document's
    authority. `sr_sections` is computed from the bill entries alone."""
    notes: list[str] = []
    scope, unrecognised = _split(nd_set, notes)
    # Sections 1 and 2 are the bill's own, so nothing is quarantined and nothing is skipped.
    assert unrecognised == []
    assert not any("provenance guard was skipped" in n for n in notes)


# ---------------------------------------------------------------------------
# The enquiry — the count, before and after
# ---------------------------------------------------------------------------
def test_the_enquiry_carried_one_attachment_before(nd_set):
    """Baseline, from the same fixture with nothing indexed: the generated sheet, alone."""
    plan = _plan(nd_set)
    assert [a.mode for a in plan.attachments] == ["generated"]


def test_the_enquiry_now_carries_the_sor_and_the_ps(nd_set):
    """The brief's acceptance test for `ground_investigation:2`."""
    from pipeline.stage_03_dispatch.relevant_docs import PRICED_RETURN

    _split(nd_set)
    plan = _plan(nd_set, "ground_investigation:2")
    kinds = {a.source_doc: (a.mode, a.flags) for a in plan.attachments}

    sor = next(a for a in plan.attachments if PRICED_RETURN in a.flags)
    assert sor.mode == "sliced"
    assert sor.source_doc.endswith(".pdf")            # the ORIGINAL bill

    ps = next((a for a in plan.attachments if "PS-S07" in a.source_doc), None)
    assert ps is not None, f"no PS in the plan: {list(kinds)}"
    assert ps.mode == "sliced"
    assert ps.pages                                    # cut to the referenced clause pages

    # And the rest of what an enquiry is supposed to carry.
    smm = next((a for a in plan.attachments if "SMM" in a.source_doc), None)
    assert smm is not None and smm.mode == "sliced"     # the referenced preamble clause only
    gs = next((a for a in plan.attachments if "General_Spec" in a.source_doc), None)
    assert gs is not None and gs.mode == "whole"        # a GS attaches whole, by design
    ta = next((a for a in plan.attachments if "Addendum" in a.source_doc), None)
    assert ta is not None and ta.mode == "whole"        # so does a clarification

    assert len(plan.attachments) == 5


def test_every_attachments_mode_and_flags_are_reportable(nd_set):
    """The plan is the gate's preview, so each entry must carry what the operator needs to judge
    it — a mode, a reason, and whatever flags apply."""
    _split(nd_set)
    for att in _plan(nd_set).attachments:
        assert att.mode in ("sliced", "whole", "generated")
        assert att.reason
