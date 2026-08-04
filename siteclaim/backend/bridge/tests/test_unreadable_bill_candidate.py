"""FIX 7 — an unreadable workbook is not put forward as the priced bill.

Observed in the Route list on the real pack:

    TA #2/BQ/E-ND_2025_04-BQ-2.xlsx    pricing   proposed   scanned
    202-ta # · 1 pages

Three faults in one row:

* **Proposed despite being unreadable.** `candidates_on` computed `proposed` from
  ``effective_category(...) == BILL_CATEGORY`` alone, with no readability test — though
  ``_describe`` had computed ``has_pdf`` all along precisely so a human could see a part that can
  contribute no text BEFORE choosing it.
* **"1 pages" is fiction.** ``page_count()`` is ``end - start + 1`` and an archive part is given
  ``start=1, end=1`` for want of anything better, so an arbitrary bound rendered as a fact.
* **``scanned`` was a bare chip** with no hint it meant "needs the Excel reader" rather than
  "needs OCR" — a different problem with a different answer.

It stays SELECTABLE throughout. The gate exists so a person can override a bad proposal, and a
workbook IS a real bill — the workbook reader handles it. What was wrong is putting it forward as
the answer when nothing here can read it.
"""

import pytest
from bridge import parts as parts_mod


def _candidates(set_id):
    return parts_mod.bq_candidates(set_id)


def _by_id(body):
    return {p["part_id"]: p for p in body["parts"]}


@pytest.fixture
def workbook_set(make_set, part_spec):
    """The observed row: a pricing part that is a workbook, so it has no cut pdf."""
    make_set("nd-2025-04", "ND/2025/04", [
        part_spec(1, "BQ", "TA #2/BQ/E-ND_2025_04-BQ-2.xlsx", "pricing",
                  start=1, end=1, source_doc="TA_2__BQ__E-ND_2025_04-BQ-2.xlsx"),
        part_spec(2, "ACC", "Additional Conditions", "contract-conditions"),
    ], pdf_paths={"01-bq": "", "02-acc": "02-acc.pdf"})
    return "nd-2025-04"


# ---------------------------------------------------------------------------
# Not proposed — but still selectable
# ---------------------------------------------------------------------------
def test_an_unreadable_pricing_part_is_not_proposed(workbook_set):
    assert _candidates(workbook_set)["proposed"] == []


def test_it_is_still_listed_and_still_selectable(workbook_set):
    """Not proposed is not hidden. The human gate exists to override a bad proposal, and a
    workbook is a real bill — removing it from the list would remove the override."""
    body = _candidates(workbook_set)
    assert "01-bq" in _by_id(body)
    parts_mod.confirm_bill_parts(workbook_set, ["01-bq"])
    assert _candidates(workbook_set)["confirmed"] == ["01-bq"]


def test_a_readable_pricing_part_is_still_proposed(make_set, part_spec):
    """The guard must not swallow the normal case."""
    make_set("ge-2026-14", "GE/2026/14",
             [part_spec(1, "BQ", "Bills of Quantities", "pricing")])
    assert _candidates("ge-2026-14")["proposed"] == ["01-bq"]


# ---------------------------------------------------------------------------
# What the screen says when this leaves NOTHING proposed
# ---------------------------------------------------------------------------
def test_the_empty_proposal_names_the_real_reason(workbook_set):
    """Reported before implementing, and it is the reason this got its own branch: telling someone
    "no part is categorised pricing" about a set holding a pricing workbook would send them looking
    for a document that is sitting right there in the list."""
    message = _candidates(workbook_set)["message"]
    assert "1 pricing part(s) were found" in message
    assert "01-bq" in message
    assert "readable page file" in message
    assert "Select it below if it is the bill" in message
    assert "No part is categorised" not in message


def test_a_set_with_no_pricing_part_at_all_keeps_its_own_message(make_set, part_spec):
    """The other empty-proposal case is unchanged — two reasons, two sentences."""
    make_set("ge-2026-14", "GE/2026/14",
             [part_spec(1, "CT", "Conditions of Tender", "tender-instructions")])
    message = _candidates("ge-2026-14")["message"]
    assert "No part is categorised 'pricing'" in message
    assert "neither by the interpreter" in message


def test_the_full_list_is_still_offered_when_nothing_is_proposed(workbook_set):
    """The honest-degrade case must not become an empty screen."""
    assert len(_candidates(workbook_set)["parts"]) == 2


# ---------------------------------------------------------------------------
# "1 pages" is fiction
# ---------------------------------------------------------------------------
def test_a_workbook_reports_no_page_count(workbook_set):
    assert _by_id(_candidates(workbook_set))["01-bq"]["pages"] is None


def test_a_real_page_span_is_still_reported(make_set, part_spec):
    """Keyed on the FORMAT, not on `has_pdf`. A part spanning pages 5-62 with no cut file spans a
    genuine 58 pages of its source; not having been cut is a different statement from not having a
    page count, and suppressing that number would throw away something true."""
    make_set("ge-2026-14", "GE/2026/14",
             [part_spec(1, "SR", "Schedule of Rates", "pricing", start=5, end=62)],
             pdf_paths={"01-sr": ""})
    assert _by_id(_candidates("ge-2026-14"))["01-sr"]["pages"] == 58


# ---------------------------------------------------------------------------
# The chip gets its reason
# ---------------------------------------------------------------------------
def test_a_workbook_says_it_needs_the_excel_reader(workbook_set):
    reason = _by_id(_candidates(workbook_set))["01-bq"]["unreadable_reason"]
    assert "workbook" in reason and "workbook reader handles it" in reason


def test_an_unreadable_non_workbook_says_something_different(make_set, part_spec):
    make_set("ge-2026-14", "GE/2026/14",
             [part_spec(1, "SR", "Schedule of Rates", "pricing", source_doc="binder.pdf")],
             pdf_paths={"01-sr": ""})
    reason = _by_id(_candidates("ge-2026-14"))["01-sr"]["unreadable_reason"]
    assert reason == "no page file was produced for this part"


def test_a_readable_part_carries_no_reason(make_set, part_spec):
    make_set("ge-2026-14", "GE/2026/14", [part_spec(1, "BQ", "Bills", "pricing")])
    assert _by_id(_candidates("ge-2026-14"))["01-bq"]["unreadable_reason"] == ""
