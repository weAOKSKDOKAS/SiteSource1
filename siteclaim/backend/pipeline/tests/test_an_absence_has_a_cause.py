"""Five absences that were reported as facts about the pack, and one signal read off a rendering.

**An unreadable index is not an empty one.** `load_doc_index` catches a parse failure and returns
`[]`, which is byte-for-byte its answer for "this tender was never indexed". So a corrupt or
half-written `doc_index.json` — a killed split, a full disk, a restart mid-write — reached
`_why_no_bill` and was reported as *"the pack that was indexed carries none"*: a confident claim
about a file nobody parsed, sending the operator to look for a bill instead of re-running. The read
still returns `[]` (a raise would turn a pure read into a 500) but the reason is now recoverable
and logged, the same rule as `OcrEngineUnavailable`.

**A page of unreadable rows ended the specification's contents page.** `parse_ps_index` stopped at
the first page contributing no entry, and a row whose title came out blank did not count as an
entry — so an index page that scanned badly read as "the list ended here" and every section after
it was dropped in silence. A page with rows on it participated, whatever their titles said.

**And the rows it could not read reached nobody.** `ps_index_unreadable` was populated, stored and
consumed by no production code. The PS Index is what gives a bill→PS title match a specification
side at all, so an unread row is a section that can never be matched by title.

**The workbook-vs-render guard could not match the pack it was written for.** It compared raw
stems, and this issuer marks the rendering with a one-letter prefix: `E-ND_2025_04_BQ-0.xlsx` is
the workbook, `I-ND_2025_04_BQ-0.pdf` its render. They share no stem, so the guard never fired and
the same bill was read twice — once deterministically, once by putting a 26-page render through
the extractor.

**The specialty firm pool was chosen by four item descriptions.** `_section_specialty_for` matched
keywords over `pkg.scope_summary`, and for a routed sub-package that string is a RENDERING that
ends in the first four item descriptions. One description mentioning "geophysical" among 28
rotary-drilling items moved the whole section to the geophysical pool — and which four are sampled
is decided by document order. A sample is evidence for a reader, never a signal.
"""

import json

import pytest

from pipeline.stage_01_ingest.doc_index import (
    DocIndexEntry,
    index_read_error,
    load_doc_index,
    parse_ps_index,
    save_doc_index,
)
from pipeline.stage_03_dispatch.relevant_docs import PRICED_RETURN, resolve_section_plan
from pipeline.workspace import Workspace
from schemas.models import SectionMeta, SorItem, TradeWorkPackage

ENTRY = DocIndexEntry(filename="BQ/I-ND_2025_04_BQ-0.pdf", kind="schedule_of_rates",
                      text_layer=True, page_count=26, sor_section_pages={"2": [8]})


@pytest.fixture
def ws(monkeypatch, tmp_path):
    monkeypatch.setenv("SITESOURCE_WORKDIR", str(tmp_path))
    return Workspace()


# -- an unreadable index says so ----------------------------------------------------------------
def test_a_healthy_index_reports_no_read_error(ws):
    save_doc_index(ws, "nd-2025-04", [ENTRY])
    assert index_read_error(ws, "nd-2025-04") == ""


def test_no_index_at_all_is_not_a_read_error(ws):
    """Absent and damaged are different states, and this is the one that is simply absent."""
    assert index_read_error(ws, "never-split") == ""


@pytest.mark.parametrize("payload,needle", [
    ("{not json", "not readable JSON"),
    ('{"filename": "x"}', "not the list of entries"),
    ('[{"filename": 5, "kind": []}]', "cannot parse"),
])
def test_a_damaged_index_says_what_is_wrong_with_it(ws, payload, needle):
    save_doc_index(ws, "nd-2025-04", [ENTRY])
    ws.doc_index_path("nd-2025-04").write_text(payload, encoding="utf-8")

    assert needle in index_read_error(ws, "nd-2025-04")


def test_the_load_still_degrades_rather_than_raising(ws):
    """Every caller treats "no index" as a state; a raise here turns a pure read into a 500."""
    save_doc_index(ws, "nd-2025-04", [ENTRY])
    ws.doc_index_path("nd-2025-04").write_text("{not json", encoding="utf-8")

    assert load_doc_index(ws, "nd-2025-04") == []


def test_the_gate_calls_a_damaged_index_damaged(ws, monkeypatch):
    from bridge import doc_index_state as mod

    save_doc_index(ws, "nd-2025-04", [ENTRY])
    ws.doc_index_path("nd-2025-04").write_text("{not json", encoding="utf-8")
    state = mod.doc_index_state("nd-2025-04")

    assert state["unreadable"]
    assert state["stale"] is True
    assert "UNREADABLE" in state["warning"]
    assert "not a statement about the pack" in state["warning"]


def test_a_healthy_index_says_nothing_new(ws):
    from bridge import doc_index_state as mod

    save_doc_index(ws, "nd-2025-04", [ENTRY])
    state = mod.doc_index_state("nd-2025-04")

    assert state["unreadable"] == "" and state["stale"] is False and state["warning"] == ""


def test_the_dispatch_sentence_no_longer_claims_the_pack_has_no_bill(ws, tmp_path):
    """`_why_no_bill`'s fifth state. The old sentence — "the pack that was indexed carries none" —
    is a fact about a file that was never parsed."""
    from pipeline.stage_03_dispatch.relevant_docs import _why_no_bill

    path = tmp_path / "doc_index.json"
    path.write_text("{not json", encoding="utf-8")
    why = _why_no_bill([], str(path))

    assert "COULD NOT BE READ" in why
    assert "says nothing about what the pack contains" in why
    assert "carries none" not in why


def test_a_genuinely_bill_less_pack_still_says_so(tmp_path):
    """The narrowing must not remove the honest answer."""
    from pipeline.stage_03_dispatch.relevant_docs import _why_no_bill

    path = tmp_path / "doc_index.json"
    path.write_text(json.dumps([{"filename": "S/PS/x.pdf", "kind": "particular_specification"}]),
                    encoding="utf-8")

    assert "carries none" in _why_no_bill([], str(path))


# -- the contents page is read to its end ----------------------------------------------------------
HEADER = "SECTION   TITLE\n"


def test_a_page_whose_titles_all_failed_does_not_end_the_list():
    """The defect: `found_here` counted only rows that PARSED, so a badly-scanned page read as the
    end of the list and every section below it vanished."""
    pages = [HEADER + "  1   General\n", "  7\n  8\n", "  26   Preservation of Trees\n"]
    titles, unreadable = parse_ps_index(pages)

    assert titles == {"1": "General", "26": "Preservation of Trees"}
    assert unreadable == ["7", "8"]


def test_one_quiet_page_inside_the_list_is_tolerated():
    """A real two-page list can be broken by a page holding nothing at all."""
    pages = [HEADER + "  1   General\n", "AECOM-AtkinsRealis JV   PS/iii\n",
             "  26   Preservation of Trees\n"]
    titles, _ = parse_ps_index(pages)

    assert titles == {"1": "General", "26": "Preservation of Trees"}


def test_two_quiet_pages_end_the_list():
    """The behaviour the stop condition exists for — the list has finished."""
    pages = [HEADER + "  1   General\n", "prose\n", "more prose\n",
             "  99   Something Later In The Document\n"]
    titles, _ = parse_ps_index(pages)

    assert titles == {"1": "General"}


def test_the_single_page_list_is_unchanged():
    """The real pack's list is one page, and that is the case that must not move."""
    pages = [HEADER + "  1   General\n  2   Site Clearance\n", "the specification body begins\n"]
    assert parse_ps_index(pages)[0] == {"1": "General", "2": "Site Clearance"}


def test_nothing_before_the_header_is_read():
    """The anchor is the whole reason a clause reference elsewhere cannot become an entry."""
    pages = ["  7   Not An Entry\n" + HEADER + "  1   General\n"]
    assert parse_ps_index(pages)[0] == {"1": "General"}


# -- an unread contents row reaches the gate ----------------------------------------------------------
def _plan(index):
    return resolve_section_plan(
        package_key="gi:2", trade="ground_investigation", section_title="GI", section="2",
        sections=["2"], items=[SorItem(item_ref="2.1", description="Drilling", section="2")],
        doc_index=list(index), sor_sheet_name="SoR.xlsx")


BILL = DocIndexEntry(filename="BQ/BQ-0.pdf", kind="schedule_of_rates", text_layer=True,
                     page_count=26, sor_section_pages={"2": [8]})


def test_rows_the_contents_page_lost_are_named_on_the_gate():
    idx = DocIndexEntry(filename="S/PS/I-ND_2025_04-S_PS_Index-0.pdf", kind="ps_index",
                        text_layer=True, page_count=2,
                        ps_index_titles={"1": "General"}, ps_index_unreadable=["7", "8"])
    note = next(m for m in _plan([BILL, idx]).missing_specs if "contents page" in m.spec)

    assert "2 row(s)" in note.spec and "7; 8" in note.spec
    assert "cannot be matched to a bill by title" in note.referenced_by


def test_a_fully_read_contents_page_says_nothing():
    idx = DocIndexEntry(filename="S/PS/I-ND_2025_04-S_PS_Index-0.pdf", kind="ps_index",
                        text_layer=True, page_count=2, ps_index_titles={"1": "General"})
    assert not any("contents page" in m.spec for m in _plan([BILL, idx]).missing_specs)


# -- one bill, one reading -----------------------------------------------------------------------------
@pytest.mark.parametrize("a,b", [
    ("BQ/E-ND_2025_04_BQ-0.xlsx", "BQ/I-ND_2025_04_BQ-0.pdf"),
    ("BQ/E-ND_2025_04_BQ-0.xlsx", "BQ/ND_2025_04_BQ-0.pdf"),
    ("bill.xlsx", "bill.pdf"),
])
def test_a_render_and_its_workbook_are_one_bill(a, b):
    from bridge.scope import _bill_identity

    assert _bill_identity(a) == _bill_identity(b)


@pytest.mark.parametrize("a,b", [
    ("BQ/E-ND_2025_04_BQ-0.xlsx", "BQ/E-ND_2025_04_BQ-1.pdf"),   # a different revision
    ("BQ/dayworks.xlsx", "BQ/I-ND_2025_04_BQ-0.pdf"),            # a different bill
    ("x/A-abc.pdf", "x/B-abc.pdf"),                              # too short to be a rendering mark
])
def test_two_different_bills_stay_two_bills(a, b):
    """A PDF sharing no identity with a workbook is a different bill and is read as normal — the
    behaviour this must not cost."""
    from bridge.scope import _bill_identity

    assert _bill_identity(a) != _bill_identity(b)


# -- the sample does not choose the firm pool -----------------------------------------------------------
def _pkg(title: str, summary: str, section_trade: str = "") -> TradeWorkPackage:
    return TradeWorkPackage(
        trade="ground_investigation:2", scope_summary=summary,
        sor_items=[SorItem(item_ref="2.1")],
        sections=[SectionMeta(code="2", title=title, item_count=28, section_trade=section_trade)])


def test_one_item_description_does_not_move_the_whole_section_to_another_pool():
    """The rendering: `Section 2 — DRILLING (28 items): rotary core drilling, …, geophysical …`.
    Matched over the whole string, item 4's wording decided the pool."""
    from pipeline.stage_02_shortlist.shortlist import _section_specialty_for

    pkg = _pkg("DRILLING", "Section 2 — DRILLING (28 items): rotary core drilling, casing, "
                           "sampling, geophysical logging of one hole")
    assert _section_specialty_for(pkg) is None, "DRILLING names no specialty; the sample must not"


def test_the_section_title_still_chooses_the_pool():
    from pipeline.stage_02_shortlist.shortlist import _section_specialty_for

    pkg = _pkg("GEOPHYSICAL SURVEY",
               "Section 4 — GEOPHYSICAL SURVEY (12 items): seismic refraction, resistivity")
    assert _section_specialty_for(pkg) == "geophysical_survey"


def test_the_specialty_annotated_at_ingest_still_wins():
    from pipeline.stage_02_shortlist.shortlist import _section_specialty_for

    pkg = _pkg("", "Section 5 — (4 items): install standpipes", section_trade="field_installations")
    assert _section_specialty_for(pkg) == "field_installations"


def test_a_whole_trade_package_still_reads_its_own_summary():
    """A whole-trade package's summary is an LLM sentence, not a rendering — there is nothing to
    strip and the keyword match is the only signal there is."""
    from pipeline.stage_02_shortlist.shortlist import _section_specialty_for

    pkg = TradeWorkPackage(trade="ground_investigation",
                           scope_summary="Geophysical survey across the site",
                           sor_items=[SorItem(item_ref="1")])
    assert _section_specialty_for(pkg) == "geophysical_survey"


@pytest.mark.parametrize("summary,expected", [
    ("Section 2 — DRILLING (28 items): a, b, c", "Section 2 — DRILLING"),
    ("Section 2 — DRILLING (1 item)", "Section 2 — DRILLING"),
    ("Section 2 (28 items): a, b", "Section 2"),
    ("Geophysical survey across the site", "Geophysical survey across the site"),
    ("", ""),
])
def test_the_heading_is_separated_from_the_sample(summary, expected):
    from pipeline.routing.split import summary_heading

    assert summary_heading(summary) == expected
