"""Every door into a classification, and every population that can be reissued.

Found by a parallel audit of the whole pipeline, and each one is a defect ALREADY FIXED reappearing
through a route the fix did not cover. That is the shape worth naming: closing a defect at one door
is not closing it.

**The DocType doors.** `_kind_for` answers three coarse `DocType` values before any own-name guard
runs, so both of these came straight back:

* PS 1 arriving as `METHOD_OF_MEASUREMENT` took SMM 1's slot and *superseded the real one* — C18,
  through a different door.
* `TA #1/…-S_PS27-1.pdf` arriving as `TENDER_ADDENDUM` became a clarification and went WHOLE to
  every firm, never meeting the `-0` it supersedes — C12, through a different door.

`SCHEDULE_OF_RATES` is deliberately NOT guarded: a human confirms which part is the bill, and a
human's answer outranks a filename.

**Two views of one index.** `_effective_kind` was applied just before the attachment loop, so every
read above it — `all_ps_sections`, `withheld_appendices` — ran on the STORED kinds. A document the
override rescues was therefore absent from the relevant set and then dropped at a bare `continue` in
the very loop that had reclassified it. The same producer/consumer disagreement as any other seam,
close enough together to look impossible.

**The populations that could be reissued and were not contested.** Appendices: the pack ships
`PSA1.12-1` under `TA #1/`, and both revisions were enclosed with byte-identical reasons. Keying
that contest needed care — an appendix's `spec_section_number` is its PARENT'S, so a section-keyed
contest would have twenty-five appendices of PS 1 all claiming one identity.

**The Method-of-Measurement branch**, where a cited PB clause turned two guarantees off at once:
every SMM in the pack was enclosed under a description untrue of most of them, and every
bill-named section was simultaneously reported MISSING.
"""

import pytest

from pipeline.stage_01_ingest.doc_index import DocIndexEntry, _kind_for
from pipeline.stage_03_dispatch.relevant_docs import (
    SUPERSEDED_BY_ADDENDUM,
    _revision_key,
    resolve_section_plan,
)
from schemas.models import DocType, SorItem

PS1 = "TA #1/S/PS/PS1/I-ND_2025_04-S_PS1-1.pdf"
PS1_PAGE1 = ("PARTICULAR SPECIFICATION\nSECTION 1\nGENERAL\n\n"
             "1.01  Measurement shall be in accordance with the Standard Method of Measurement.\n")
PS27_1 = "TA #1/S/PS/PS27/I-ND_2025_04-S_PS27-1.pdf"
PSA_0 = "S/PS/PS1/I-ND_2025_04-S_PSA1.12-0.pdf"
PSA_1 = "TA #1/S/PS/PS1/I-ND_2025_04-S_PSA1.12-1.pdf"
PSA_OTHER = "S/PS/PS1/I-ND_2025_04-S_PSA1.13-0.pdf"


# -- the DocType doors ----------------------------------------------------------------------------
@pytest.mark.parametrize("doc_type,path,expected", [
    (DocType.METHOD_OF_MEASUREMENT, PS1, "particular_specification"),
    (DocType.TENDER_ADDENDUM, PS27_1, "particular_specification"),
    (DocType.TENDER_ADDENDUM, PSA_1, "appendix"),
    (DocType.METHOD_OF_MEASUREMENT, "S/GS/I-ND_2025_04-S_GS7-0.pdf", "general_specification"),
])
def test_a_doctype_cannot_override_the_name_the_issuer_gave_a_file(doc_type, path, expected):
    assert _kind_for(doc_type, PS1_PAGE1 if "PS1-" in path else "", path) == expected


@pytest.mark.parametrize("doc_type,path,expected", [
    (DocType.METHOD_OF_MEASUREMENT, "GP&PP/I-ND_2025_04-SMM_S02-0.pdf", "method_of_measurement"),
    (DocType.TENDER_ADDENDUM, "TA #1/I-ND_2025_04-Tender_Addendum_No_1.pdf", "clarification"),
    (DocType.SCHEDULE_OF_RATES, "BQ/I-ND_2025_04_BQ-0.pdf", "schedule_of_rates"),
])
def test_the_doors_still_answer_for_documents_that_name_no_section(doc_type, path, expected):
    """The guard must not cost the classifications it protects."""
    assert _kind_for(doc_type, "", path) == expected


def test_the_bill_door_is_deliberately_unguarded():
    """A human confirms which part is the bill. That answer outranks a filename, so this door is
    the one exception and it is an exception on purpose."""
    assert _kind_for(DocType.SCHEDULE_OF_RATES, PS1_PAGE1, "PS7") == "schedule_of_rates"


# -- one view of the index ---------------------------------------------------------------------------
def _e(fn, kind, sec="", **kw):
    return DocIndexEntry(filename=fn, kind=kind, spec_section_number=sec, text_layer=True,
                         page_count=10, **kw)


def _plan(index, *, confirmed=None, clause_refs=()):
    return resolve_section_plan(
        package_key="gi:2", trade="ground_investigation", section_title="GI", section="2",
        sections=["2"],
        items=[SorItem(item_ref="2.1", description="Drilling", section="2",
                       clause_refs=list(clause_refs))],
        doc_index=list(index), sor_sheet_name="SoR.xlsx", confirmed_ps_specs=confirmed)


def _docs(plan):
    return {a.source_doc for a in plan.attachments}


def test_a_rescued_specification_is_in_the_relevant_set_not_dropped_after_it():
    """A stale index stores the `-1` reissue as a `clarification`. `_effective_kind` rescues it —
    but `all_ps_sections` read the STORED kinds, so under the whole-specification fallback the
    rescued document was not relevant and the loop dropped it at a bare `continue`."""
    stale = [_e(PS27_1, "clarification", "27")]
    plan = _plan(stale)

    assert plan.relevance_source == "none", "no clauses, no confirmed map"
    assert PS27_1 in _docs(plan), "the rescued specification must reach the enquiry"


def test_a_rescued_appendix_is_withheld_WITH_a_line_on_the_gate():
    """`withheld_appendices` read the stored kinds too, so a rescued appendix was withheld in
    silence — withheld is fine, silent is not."""
    index = [_e(PS1, "particular_specification", "1"), _e(PSA_0, "particular_specification", "1")]
    plan = _plan(index, confirmed={"1"})

    assert PSA_0 not in _docs(plan), "clause-driven, and this bill cites none"
    assert any("appendices of PS 1" in m.spec for m in plan.missing_specs), \
        "the withheld appendix must be counted on the gate"


# -- the appendix revision contest ---------------------------------------------------------------------
def test_an_appendix_is_identified_by_its_own_name_not_its_parents_section():
    """Twenty-five appendices of PS 1 all carry `spec_section_number == "1"`. A section-keyed
    contest would have them all claim one identity and supersede each other."""
    assert _revision_key(_e(PSA_0, "appendix", "1")) == _revision_key(_e(PSA_1, "appendix", "1"))
    assert _revision_key(_e(PSA_OTHER, "appendix", "1")) != _revision_key(_e(PSA_0, "appendix", "1"))
    assert _revision_key(_e("x", "particular_specification", "27")) == "27", "unchanged for a PS"


def test_only_the_operative_revision_of_an_appendix_is_enclosed():
    index = [_e(PS1, "particular_specification", "1", clause_index={"1.02": [1]}),
             _e(PSA_0, "appendix", "1"), _e(PSA_1, "appendix", "1")]
    docs = _docs(_plan(index, clause_refs=["PS 1.02", "Appendix 1.12"]))

    assert PSA_1 in docs and PSA_0 not in docs


def test_two_different_appendices_of_one_section_both_survive():
    """The risk the keying must not take: they are not revisions of each other."""
    index = [_e(PS1, "particular_specification", "1", clause_index={"1.02": [1]}),
             _e(PSA_0, "appendix", "1"), _e(PSA_OTHER, "appendix", "1")]
    docs = _docs(_plan(index, clause_refs=["PS 1.02", "Appendix 1.12", "Appendix 1.13"]))

    assert PSA_0 in docs and PSA_OTHER in docs


def test_the_gate_states_an_appendix_revision():
    index = [_e(PS1, "particular_specification", "1", clause_index={"1.02": [1]}),
             _e(PSA_0, "appendix", "1"), _e(PSA_1, "appendix", "1")]
    att = next(a for a in _plan(index, clause_refs=["PS 1.02", "Appendix 1.12"]).attachments
               if a.source_doc == PSA_1)

    assert "Rev 1" in att.reason and "superseding" in att.reason
    assert SUPERSEDED_BY_ADDENDUM in att.flags


# -- the Method-of-Measurement branch ------------------------------------------------------------------
BQ = _e("BQ/BQ-0.pdf", "schedule_of_rates", bill_mm_sections={"2": ["2"]})
SMM2 = _e("GP&PP/SMM_S02-0.pdf", "method_of_measurement", "2", clause_index={"PB 71": [1]})
SMM24 = _e("GP&PP/SMM_S24-0.pdf", "method_of_measurement", "24")
SMM29 = _e("GP&PP/SMM_S29-0.pdf", "method_of_measurement", "29")


def test_a_cited_preamble_clause_does_not_enclose_every_measurement_section_in_the_pack():
    """With a PB clause cited the branch had no relevance filter at all — every SMM document went
    out, each described as "referenced preamble clauses", which was untrue of most of them."""
    docs = _docs(_plan([BQ, SMM2, SMM24, SMM29], clause_refs=["PB 71"]))

    assert SMM2.filename in docs, "the section the bill names AND the clause is in"
    assert SMM24.filename not in docs and SMM29.filename not in docs


def test_a_bill_named_section_is_not_reported_missing_while_it_is_being_enclosed():
    """`mm_present` was written only in the bill-named branch, so a unit citing a PB clause
    reported every bill-named SMM section as absent from a pack it was attaching from."""
    plan = _plan([BQ, SMM2], clause_refs=["PB 71"])

    assert SMM2.filename in _docs(plan)
    assert not any("Method of Measurement Section 2" in m.spec for m in plan.missing_specs)


def test_a_genuinely_absent_measurement_section_is_still_reported():
    """The report must keep working — this is a narrowing of a false positive, not its removal."""
    plan = _plan([BQ], clause_refs=[])
    assert any(m.spec == "Method of Measurement Section 2" for m in plan.missing_specs)


def test_a_contested_measurement_revision_is_named_on_the_gate():
    """`contested_mm` was computed and never used — the loser was set aside in silence, where the
    specification equivalent is reported."""
    a = _e("GP&PP/I-ND_2025_04-SMM_S02-1.pdf", "method_of_measurement", "2")
    b = _e("TA #2/GP&PP/I-ND_2025_04-SMM_S02-1.pdf", "method_of_measurement", "2")
    plan = _plan([BQ, a, b])

    assert any("claims the same section and revision" in m.spec for m in plan.missing_specs)
