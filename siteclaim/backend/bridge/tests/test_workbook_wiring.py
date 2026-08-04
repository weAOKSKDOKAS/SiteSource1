"""The workbook reader, wired into the bill split — and the both-formats question.

THE PACK CONTAINS BOTH. CEDD ND/2025/04 ships `BQ/E-ND_2025_04_BQ-0.xlsx` and a PDF render of the
same bill, and pricing one bill twice is worse than reading it from the wrong one. These tests pin
which one wins and that the loser is reported rather than silently dropped.

A separate file rather than an append to `test_scope_bills.py`, so "zero edits to existing tests"
stays a thing anyone can verify with a diff instead of a reading.
"""

import pytest

from bridge import parts as parts_mod
from bridge import scope as scope_mod
from schemas.models import ScopePackages, SorItem, TradeWorkPackage


def _workbook_bytes(rows=(("1.1", "Bond"), ("1.2", "Insurances"))) -> bytes:
    import io

    openpyxl = pytest.importorskip("openpyxl")
    book = openpyxl.Workbook()
    book.remove(book.active)
    sheet = book.create_sheet("Bill No.1")
    sheet.append(["Item No.", "Item Description", None, None, "Quantity", "Unit", "Rate", "Amount"])
    sheet.append([None, "General and Preliminaries"])
    for ref, desc in rows:
        r = sheet.max_row + 1
        sheet.append([ref, None, desc, None, 1, "sum", None, f"=E{r}*G{r}"])
    buf = io.BytesIO()
    book.save(buf)
    return buf.getvalue()


@pytest.fixture
def workbook_set(make_set, part_spec, tmp_path):
    """A set whose confirmed bill is a WORKBOOK, beside a PDF render of the same bill — which is
    what the real pack ships."""
    xlsx = tmp_path / "E-ND_2025_04_BQ-0.xlsx"
    xlsx.write_bytes(_workbook_bytes())
    pdf = tmp_path / "E-ND_2025_04_BQ-0.pdf"
    import fitz

    doc = fitz.open()
    doc.new_page().insert_text((60, 80), "1.1 Bond", fontsize=11)
    doc.save(str(pdf))
    doc.close()
    make_set("nd-2025-04", "ND/2025/04", [
        part_spec(1, "BQX", "E-ND_2025_04_BQ-0.xlsx", "pricing", start=1, end=1),
        part_spec(2, "BQP", "E-ND_2025_04_BQ-0.pdf", "pricing", start=1, end=1),
    ], pdf_paths={"01-bqx": str(xlsx), "02-bqp": str(pdf)})
    return "nd-2025-04"


def test_a_workbook_bill_is_read_deterministically(workbook_set):
    parts_mod.confirm_bill_parts(workbook_set, ["01-bqx"])
    notes: list[str] = []

    class Explodes:
        def complete_json(self, **_kw):
            raise AssertionError("a workbook bill must reach no model at all")

    scope, unrecognised = scope_mod.scope_from_set(
        workbook_set, client=Explodes(), on_error=notes.append)

    refs = {it.item_ref for p in scope.packages for it in p.sor_items}
    assert refs == {"1.1", "1.2"}
    assert unrecognised == []
    assert any("zero model calls" in n for n in notes)


def test_the_workbook_carries_what_the_render_cannot(workbook_set, tmp_path):
    """A heading chain that is a FACT about which column the text sits in, not a reading of how
    many spaces PyMuPDF padded with."""
    parts_mod.confirm_bill_parts(workbook_set, ["01-bqx"])
    scope, _ = scope_mod.scope_from_set(workbook_set, client=object())
    item = next(it for p in scope.packages for it in p.sor_items if it.item_ref == "1.1")
    assert item.heading_path == ["General and Preliminaries"]
    assert item.section == "1"


def test_the_render_of_the_same_bill_is_not_priced_twice(workbook_set):
    """THE PACK CONTAINS BOTH. Pricing one bill twice is worse than reading it from the wrong one,
    and a render can establish neither a lump sum nor an Employer-fixed rate — so the workbook
    wins and the render is dropped, reported rather than silently."""
    parts_mod.confirm_bill_parts(workbook_set, ["01-bqx", "02-bqp"])
    notes: list[str] = []

    class Explodes:
        def complete_json(self, **_kw):
            raise AssertionError("the render should not have been extracted")

    scope, _ = scope_mod.scope_from_set(workbook_set, client=Explodes(), on_error=notes.append)

    refs = [it.item_ref for p in scope.packages for it in p.sor_items]
    assert refs == ["1.1", "1.2"]                       # once each, from the workbook
    assert any("PDF render of a bill this set also carries as a workbook" in n for n in notes)


def test_a_pdf_bill_alone_still_takes_the_extraction_path(workbook_set):
    """The PDF path is unchanged — this is a second producer of one shape, not a second pipeline."""
    parts_mod.confirm_bill_parts(workbook_set, ["02-bqp"])
    called: list[str] = []

    class Records:
        def complete_json(self, *, user, target_model, **_kw):
            called.append(user)
            return ScopePackages(project_name="ND", packages=[TradeWorkPackage(
                trade="ground_investigation", scope_summary="GI",
                sor_items=[SorItem(item_ref="1.1", description="Bond")])])

    scope_mod.scope_from_set(workbook_set, client=Records())
    assert called, "the PDF bill must still go through the extractor"
