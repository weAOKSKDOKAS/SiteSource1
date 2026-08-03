"""The review reads contract documents, not bills.

The live run made six ``client_boq-review-ingest-01-bq-*`` calls, every one returning exactly
8,000 output tokens — two retried and still at the ceiling — because it was reading a bill of
quantities for contractual positions. The register that came back said "No letter of offer in the
document set" and "No tender clarifications in the document set": true, and useless, because the
set contained only a bill.

A bill carries priced items. A drawing set carries geometry. Neither carries clauses.
"""

from client_boq.models import PartSpec
from client_boq.review import s01_ingest


def _part(n, abbr, category, title=""):
    return PartSpec(n=n, abbr=abbr, slug=abbr.lower(), title=title or abbr,
                    start=1, end=5, category=category)


def _run(parts, notes):
    """`ingest_from_parts` with no readable file on disk — the filter is what is under test, and a
    missing path is already a skip, so no model call and no PDF are involved."""
    return s01_ingest.ingest_from_parts(
        [(p, "") for p in parts], "ND/2025/04", on_note=notes.append,
    )


def test_a_bill_is_not_read_for_contractual_positions():
    notes: list[str] = []
    _run([_part(1, "BQ", "pricing", "Bills of Quantities"),
          _part(2, "CC", "contract-conditions")], notes)
    assert any("were NOT read for contractual positions" in n for n in notes)
    assert any("01-bq (pricing)" in n for n in notes)


def test_drawings_are_not_read_either():
    notes: list[str] = []
    _run([_part(1, "DRG", "drawings"), _part(2, "PS", "specifications")], notes)
    assert any("01-drg (drawings)" in n for n in notes)


def test_a_set_with_no_contractual_document_says_so_plainly():
    """The point of the whole change: silence beats a register of findings about documents that
    were never uploaded."""
    notes: list[str] = []
    parsed = _run([_part(1, "BQ", "pricing"), _part(2, "DRG", "drawings")], notes)
    assert parsed.clauses == []
    said = " ".join(notes)
    assert "NO contractual document" in said
    assert "true and useless" in said
    assert "Upload the conditions of contract" in said


def test_a_set_that_has_contractual_parts_does_not_claim_otherwise():
    notes: list[str] = []
    _run([_part(1, "BQ", "pricing"), _part(2, "CC", "contract-conditions")], notes)
    assert not any("NO contractual document" in n for n in notes)


def test_nothing_is_reported_when_every_part_is_contractual():
    notes: list[str] = []
    _run([_part(1, "CT", "tender-instructions"), _part(2, "PS", "specifications")], notes)
    assert notes == []


def test_the_skip_list_is_exactly_pricing_and_drawings():
    """Pinned so the list cannot widen quietly. Everything else can carry a contractual position:
    safety requirements are obligations, bid forms carry the form of tender."""
    assert s01_ingest.NON_CONTRACTUAL_CATEGORIES == frozenset({"pricing", "drawings"})


def test_the_uncategorised_bucket_is_still_read():
    """`other` is honest-uncategorised, not junk. Skipping it would silently drop a contractual
    document the classifier failed to place — the exact failure this module exists to prevent."""
    notes: list[str] = []
    _run([_part(1, "X", "other")], notes)
    assert notes == []


def test_the_category_test_is_case_and_whitespace_tolerant():
    notes: list[str] = []
    _run([_part(1, "BQ", "  Pricing  ")], notes)
    assert any("NO contractual document" in n for n in notes)


def test_no_parts_at_all_reports_nothing():
    """An empty set is the loose-upload path's business, not this one's."""
    notes: list[str] = []
    _run([], notes)
    assert notes == []
