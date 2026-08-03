"""Phase 4 — a Bill of Quantities through ``scope_from_set``, end to end and offline.

CEDD contract ND/2025/04 was the first real Hong Kong bill to reach the live pipeline. Extraction
worked — 136 items came back with real references, ``1.17``, ``1.18``, ``2.1``…``2.24``, ``3.1`` —
and then the provenance guard quarantined every single one:

    item '1.17' — section — is not a Schedule-of-Rates section
    (SoR sections ['1', '2', '24', '28', '29', '3']); quarantined, not routed

Both halves of that message are wrong, and this file pins both:

* the item's own section was empty, because ``section_of("1.17")`` reads leading LETTERS;
* the declared sections were not the bill's. ND/2025/04 has nine bills, 1 to 9. ``24``, ``28`` and
  ``29`` are *specification* cross-references from the preambles, matched because the SoR header
  pattern's code class is ``[A-Za-z0-9]+``.

The fixture below reproduces that shape — Bill headers in three punctuation styles, plus the
specification sections bill 1's preamble lists, on their own lines. That last detail is load-
bearing: ``_sor_section_markers`` uses ``.match``, so only a LINE-START ``SECTION n`` poisons the
vocabulary. A first draft of this fixture buried the cross-reference mid-sentence, which made
``sr_sections`` empty, which made the guard skip, which made "nothing was quarantined" pass for
entirely the wrong reason. Both halves of the failure have to be on their own line to be real.

Offline throughout: a stub client stands in for Layer 2 and the part is a real PDF written by
pymupdf, so the per-part read, the doc index and the provenance guard all run for real.
"""

import pytest

from bridge import parts as parts_mod
from bridge import scope as scope_mod
from pipeline.routing.split import route_units
from schemas.models import ScopePackages, SorItem, TradeWorkPackage

# The ND shape. Bill 1 carries the specification cross-reference that used to poison the guard's
# vocabulary; the three Bill headers use the three punctuations real documents use.
ND_BILL_PAGE_1 = """Bill No. 1 - General and Preliminaries
Rates shall include for compliance with the following specification sections:
SECTION 1 : GENERAL
SECTION 24 : EARTHWORKS
SECTION 28 : GEOTECHNICAL WORKS
SECTION 29 : LANDSCAPE SOFT WORKS
1.1  Provide performance bond
1.2  Insurances of the Works
1.17 Provide and maintain site office accommodation
1.18 Attendance on the Engineer's staff"""

ND_BILL_PAGE_2 = """BILL NO. 2 : GROUND INVESTIGATION FIELDWORKS
2.1  Mobilisation and demobilisation of drilling plant
2.4  Rotary drilling in soil, depth not exceeding 10 m
2.24 Standpipe piezometer installation"""

ND_BILL_PAGE_3 = """Bill No.3 Laboratory Testing
3.1  Consolidated undrained triaxial test
3.2  Atterberg limits determination"""

# What the extractor returns for that bill: the printed refs, verbatim, and NO section — the
# section is Layer 1's to assign. `SorItem.section` is left unset on purpose; if these tests set
# it they would be asserting their own fixture rather than `annotate_sections`.
_ND_REFS = [
    ("1.1", "Provide performance bond"),
    ("1.2", "Insurances of the Works"),
    ("1.17", "Provide and maintain site office accommodation"),
    ("1.18", "Attendance on the Engineer's staff"),
    ("2.1", "Mobilisation and demobilisation of drilling plant"),
    ("2.4", "Rotary drilling in soil, depth not exceeding 10 m"),
    ("2.24", "Standpipe piezometer installation"),
    ("3.1", "Consolidated undrained triaxial test"),
    ("3.2", "Atterberg limits determination"),
]


def _nd_scope() -> ScopePackages:
    return ScopePackages(project_name="ND/2025/04", packages=[
        TradeWorkPackage(trade="ground_investigation", scope_summary="Ground investigation",
                         sor_items=[SorItem(item_ref=r, description=d) for r, d in _ND_REFS]),
    ])


class StubClient:
    """Returns the scripted split for every chunk; `_merge_scopes` dedupes by ``item_ref``."""

    def __init__(self, scope: ScopePackages):
        self._scope = scope
        self.prompts: list[str] = []

    def complete_json(self, *, system, user, target_model, **_kw):
        self.prompts.append(user)
        return self._scope


@pytest.fixture
def make_pdf(tmp_path):
    def _make(name: str, pages: list[str]) -> str:
        import fitz

        doc = fitz.open()
        for body in pages:
            page = doc.new_page()
            y = 80
            for line in body.splitlines():
                page.insert_text((60, y), line, fontsize=11)
                y += 16
        path = tmp_path / name
        doc.save(str(path))
        doc.close()
        return str(path)

    return _make


@pytest.fixture
def nd_set(make_set, part_spec, make_pdf):
    """A one-part set whose confirmed bill is the ND-shaped Bill of Quantities."""
    bq_pdf = make_pdf("nd_bq.pdf", [ND_BILL_PAGE_1, ND_BILL_PAGE_2, ND_BILL_PAGE_3])
    make_set("nd-2025-04", "Contract No. ND/2025/04", [
        part_spec(1, "BQ", "Bills of Quantities", "pricing", start=1, end=3),
    ], pdf_paths={"01-bq": bq_pdf})
    parts_mod.confirm_bill_parts("nd-2025-04", ["01-bq"])
    return "nd-2025-04"


@pytest.fixture
def nd_split(nd_set):
    """``(scope, unrecognised, notes)`` for the ND bill."""
    notes: list[str] = []
    scope, unrecognised = scope_mod.scope_from_set(
        nd_set, client=StubClient(_nd_scope()), on_error=notes.append,
    )
    return scope, unrecognised, notes


# -- the failure of the night -------------------------------------------------------------------
def test_not_one_item_is_quarantined(nd_split):
    scope, unrecognised, notes = nd_split
    assert unrecognised == []
    assert not [n for n in notes if "quarantined" in n]
    assert sum(len(p.sor_items) for p in scope.packages) == len(_ND_REFS)


def test_the_guard_was_actually_applied_not_skipped(nd_split):
    """The guard is skipped when the bill declares no section headers of its own — which would
    make an empty quarantine list meaningless. It ran: the Bill headers were indexed."""
    _scope, _unrecognised, notes = nd_split
    assert not [n for n in notes if "provenance guard was skipped" in n]


def test_every_item_carries_its_bill_number_as_its_section(nd_split):
    scope, _unrecognised, _notes = nd_split
    got = {it.item_ref: it.section for p in scope.packages for it in p.sor_items}
    assert got == {
        "1.1": "1", "1.2": "1", "1.17": "1", "1.18": "1",
        "2.1": "2", "2.4": "2", "2.24": "2",
        "3.1": "3", "3.2": "3",
    }


def test_the_declared_sections_are_the_bills_and_nothing_else(nd_set):
    """The other half of the failure: ``['1','2','24','28','29','3']``. The ``SECTION 24 / 28 / 29``
    lines in bill 1's preamble point at the specification; they are not sections of this document,
    and with them in the vocabulary the guard is checking items against the wrong list entirely."""
    from client_boq import store as cb_store
    from pipeline.stage_01_ingest.doc_index import build_doc_index
    from schemas.models import DocType

    conn = cb_store.get_conn()
    try:
        parts = cb_store.load_parts(conn, "nd-2025-04")
    finally:
        conn.close()
    data = open(parts[0][1], "rb").read()
    entry = build_doc_index([("Bills of Quantities", DocType.SCHEDULE_OF_RATES, data)])[0]
    assert sorted(entry.sor_section_pages) == ["1", "2", "3"]  # not 24 / 28 / 29


def test_section_titles_come_off_the_bill_headers(nd_split):
    """Including the collision: bill 1's preamble also cites ``SECTION 1 : GENERAL``. Both headers
    declare a code ``1``, and the BILL header must win — in a Bill of Quantities a ``SECTION n``
    line is pointing at the specification, not naming a section of this document."""
    scope, _unrecognised, _notes = nd_split
    titles = {s.code: s.title for p in scope.packages for s in p.sections}
    assert titles == {
        "1": "General and Preliminaries",          # NOT "GENERAL", the spec cross-reference
        "2": "GROUND INVESTIGATION FIELDWORKS",
        "3": "Laboratory Testing",
    }


def test_package_keys_are_well_formed_for_routing(nd_split):
    """``route_units`` is what the routing gate consumes. A bill must produce the same
    ``trade:SECTION`` identity a schedule does — nothing in it requires a letter."""
    scope, _unrecognised, _notes = nd_split
    units = route_units(scope, split_keys={"ground_investigation"})
    assert [u["package_key"] for u in units] == [
        "ground_investigation:1", "ground_investigation:2", "ground_investigation:3",
    ]
    assert [u["section"] for u in units] == ["1", "2", "3"]
    assert all(u["package"].sor_items for u in units)          # no empty routable unit
    assert units[1]["section_title"] == "GROUND INVESTIGATION FIELDWORKS"


def test_whole_package_routing_still_works_when_not_split(nd_split):
    scope, _unrecognised, _notes = nd_split
    units = route_units(scope)          # below the auto-split threshold, and not forced
    assert [u["package_key"] for u in units] == ["ground_investigation"]


# -- the count, reported from the fixture rather than a live call --------------------------------
def test_report_items_per_bill_and_nothing_unplaced(nd_split):
    from collections import Counter

    scope, unrecognised, _notes = nd_split
    per_bill = Counter(it.section or "(unplaced)" for p in scope.packages for it in p.sor_items)
    assert dict(per_bill) == {"1": 4, "2": 3, "3": 2}
    assert per_bill["(unplaced)"] == 0
    assert sum(per_bill.values()) == len(_ND_REFS) == 9
    assert unrecognised == []
    # And the rolled-up metadata agrees with the items, so Route shows the same nine.
    counts = {s.code: s.item_count for p in scope.packages for s in p.sections}
    assert counts == {"1": 4, "2": 3, "3": 2}


# -- the boundary: a Schedule of Rates through the same call is untouched ------------------------
def test_a_schedule_of_rates_set_still_splits_by_letter(make_set, part_spec, make_pdf):
    sr_pdf = make_pdf("sr.pdf", [
        "SECTION G : FIELD TESTING\nG1 In-situ vane shear\nG2 Standard penetration test",
        "SECTION H : FIELD INSTALLATIONS\nH1 Install standpipe piezometer",
    ])
    make_set("ge-2026-14", "GE/2026/14",
             [part_spec(1, "SR", "Schedule of Rates", "pricing", start=1, end=2)],
             pdf_paths={"01-sr": sr_pdf})
    parts_mod.confirm_bill_parts("ge-2026-14", ["01-sr"])
    scope = ScopePackages(project_name="GE/2026/14", packages=[
        TradeWorkPackage(trade="ground_investigation", scope_summary="GI", sor_items=[
            SorItem(item_ref="G1", description="In-situ vane shear"),
            SorItem(item_ref="G2", description="Standard penetration test"),
            SorItem(item_ref="H1", description="Install standpipe piezometer"),
        ]),
    ])
    out, unrecognised = scope_mod.scope_from_set("ge-2026-14", client=StubClient(scope))
    assert unrecognised == []
    assert [it.section for p in out.packages for it in p.sor_items] == ["G", "G", "H"]
    assert {s.code: s.title for p in out.packages for s in p.sections} == {
        "G": "FIELD TESTING", "H": "FIELD INSTALLATIONS",
    }
