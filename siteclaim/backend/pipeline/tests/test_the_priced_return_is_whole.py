"""The one document the firm is asked to fill in went out short, and nothing said so.

`_priced_return_attachment` slices the bill to the sections it can locate::

    located = [sk for sk in section_keys if sk in hit.sor_section_pages]

Sections in `section_keys` but NOT in `located` were dropped with no flag, no gate line, and a
reason naming only the survivors — so a partial slice read exactly like a complete one. The
whole-bill fallback fires only when NOTHING is located, so a total miss was loud and a partial miss
was silent, which is the wrong way round: a total miss is obvious to whoever opens the attachment.

Reachable on the main path. `route_units` leaves a package whole when it has ≤3 sections and ≤60
items, and `drafts.plan_for_firms` then derives `unit_sections` from the items, so a whole-routed
unit routinely carries several section codes. The bill-header indexer is the component already
known to lose a bill outright (`doc_index`'s own note records Bill 9 being dropped).

The consequence is a wrong verdict two stages later: the firm returns section 9 with no rates, and
`stage_04` levels that as the firm's scope gap rather than as pages we never sent them.
"""

import pytest

from pipeline.stage_01_ingest.doc_index import DocIndexEntry
from pipeline.stage_03_dispatch.relevant_docs import (
    PRICED_RETURN,
    SUBSTITUTED,
    resolve_section_plan,
)
from schemas.models import SorItem


def _bill(pages: dict) -> DocIndexEntry:
    return DocIndexEntry(filename="BQ/I-ND_2025_04_BQ-0.pdf", kind="schedule_of_rates",
                         text_layer=True, page_count=26, sor_section_pages=pages)


def _plan(index, sections):
    return resolve_section_plan(
        package_key="gi", trade="ground_investigation", section_title="GI", sections=sections,
        items=[SorItem(item_ref=f"{s}.1", description="drilling", section=s) for s in sections],
        doc_index=list(index), sor_sheet_name="SoR_gi.xlsx")


def _priced(plan):
    return next(a for a in plan.attachments if PRICED_RETURN in a.flags)


# -- the partial miss is stated -----------------------------------------------------------------
def test_a_section_the_index_could_not_locate_is_named_on_the_attachment():
    att = _priced(_plan([_bill({"2": [3, 4, 5]})], ["2", "9"]))

    assert att.missing_sections == ["9"]
    assert "WITHOUT Section 9" in att.reason
    assert "return those lines unpriced" in att.reason


def test_a_partial_slice_is_flagged_as_a_substitution():
    """`SUBSTITUTED` is the existing flag for "what went out is not what the design sends", and a
    sheet missing a section the enquiry covers is exactly that."""
    att = _priced(_plan([_bill({"2": [3, 4, 5]})], ["2", "9"]))
    assert SUBSTITUTED in att.flags


def test_it_reaches_the_gate_where_the_operator_looks():
    plan = _plan([_bill({"2": [3, 4, 5]})], ["2", "9"])
    note = next(m for m in plan.missing_specs if "Section 9" in m.spec)

    assert note.spec == "Schedule of Rates Section 9 — not in the priced return"
    assert "not located in the Schedule of Rates index" in note.referenced_by


def test_several_unlocated_sections_are_all_named():
    plan = _plan([_bill({"2": [3]})], ["2", "8", "9"])

    assert _priced(plan).missing_sections == ["8", "9"]
    assert "WITHOUT Sections 8, 9" in _priced(plan).reason
    assert len([m for m in plan.missing_specs if "not in the priced return" in m.spec]) == 2


def test_the_pages_that_were_found_are_still_sent():
    """A narrowing, not a refusal: the firm still gets section 2's pages to price."""
    att = _priced(_plan([_bill({"2": [3, 4, 5]})], ["2", "9"]))

    assert att.mode == "sliced" and att.pages == [4, 5, 6]
    assert att.source_doc == "BQ/I-ND_2025_04_BQ-0.pdf"


# -- the complete cases are untouched ---------------------------------------------------------------
def test_a_fully_located_multi_section_unit_says_nothing():
    """A report that fires on every enquiry is a report nobody reads."""
    plan = _plan([_bill({"2": [3], "9": [11]})], ["2", "9"])
    att = _priced(plan)

    assert att.missing_sections == [] and SUBSTITUTED not in att.flags
    assert "WITHOUT" not in att.reason
    assert not any("not in the priced return" in m.spec for m in plan.missing_specs)


def test_a_single_section_unit_is_unchanged():
    att = _priced(_plan([_bill({"2": [3, 4]})], ["2"]))

    assert att.missing_sections == [] and att.flags == [PRICED_RETURN]
    assert att.reason == ("Schedule of Rates — Section 2 "
                          "(the priced-return sheet for this enquiry)")


def test_a_total_miss_still_falls_back_to_the_whole_bill():
    """The existing loud path: nothing located means the firm gets the entire bill, flagged. This
    change narrows a false negative and must not disturb it."""
    att = _priced(_plan([_bill({"7": [20]})], ["2", "9"]))

    assert att.mode == "whole" and SUBSTITUTED in att.flags
    assert "whole_section_not_located" in att.flags
    assert "WHOLE bill" in att.reason


def test_no_bill_at_all_still_generates_the_sheet():
    att = _priced(_plan([], ["2"]))

    assert att.mode == "generated" and att.source_doc == "SoR_gi.xlsx"
    assert att.missing_sections == []
