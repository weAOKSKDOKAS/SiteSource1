"""Specifications are deferred by default, named rather than dropped, and one flag brings them back.

CEDD ND/2025/04 extracts to 206 parts. The old skip-list — ``{pricing, drawings}`` — was sized for
a set holding one bill plus a few contract documents, and on this pack it left roughly 150
specification appendices being read for contractual departures: 38 lab-testing under S/PS/PS31, 28
geotechnical under S/PS/PS7, 25 under S/PS/PS1. Borehole logs and test-result schedules are data.

The design decision, and it is a decision rather than a threshold: a departure register concerns
the CONDITIONS OF CONTRACT. But ``specifications`` is too coarse a category to condemn wholesale —
GP&PP is the Standard Method of Measurement rules (what a rate must include, which is commercial),
and the Particular Specification body carries obligations that are departures by any practical
definition. So the category is deferred, not excluded, and the operator decides per tender.

**Still a skip-list.** An allow-list would be faster to write and would silently omit any category
added to ``PART_CATEGORIES`` later; its failure mode is a MISSING FINDING, which is invisible. A
skip-list's failure mode is a SLOW RUN, which is visible. These tests pin both halves: the default
defers, and everything not named is still read.

Kept out of ``client_boq/tests`` on purpose — the source change there is a narrowly authorised one
in another developer's module, and his diff should be the lines that were agreed, nothing more.
"""

import pytest

from client_boq.models import PartSpec
from client_boq.review import s01_ingest


def _part(n, abbr, category):
    return PartSpec(n=n, abbr=abbr, slug=abbr.lower(), title=abbr, start=1, end=5,
                    category=category)


def _run(parts, notes, **kw):
    """No readable file on disk — the partition is what is under test, and a missing path is
    already a skip, so no model call and no PDF are involved."""
    return s01_ingest.ingest_from_parts(
        [(p, "") for p in parts], "ND/2025/04", on_note=notes.append, **kw)


# ---------------------------------------------------------------------------
# The two sets, and which is which
# ---------------------------------------------------------------------------
def test_the_never_read_list_did_not_widen():
    """`specifications` is NOT in it. Adding it there would say a specification carries no
    contractual position, which is false — that is why there are two sets and not one longer one."""
    assert s01_ingest.NON_CONTRACTUAL_CATEGORIES == frozenset({"pricing", "drawings"})
    assert s01_ingest.OPTIONAL_CATEGORIES == frozenset({"specifications"})
    assert not (s01_ingest.NON_CONTRACTUAL_CATEGORIES & s01_ingest.OPTIONAL_CATEGORIES)


def test_the_default_run_defers_specifications():
    assert s01_ingest.skip_set() == frozenset({"pricing", "drawings", "specifications"})


def test_asking_for_specifications_reads_them():
    assert s01_ingest.skip_set(include_specifications=True) == frozenset({"pricing", "drawings"})


def test_the_stage_default_is_unchanged_so_existing_callers_are_untouched():
    """The POLICY lives at the request boundary, not in the stage. `ingest_from_parts` keeps the
    contract it always had — which is why every existing test of it stayed green unedited."""
    import inspect

    default = inspect.signature(s01_ingest.ingest_from_parts).parameters["skip_categories"].default
    assert default == s01_ingest.NON_CONTRACTUAL_CATEGORIES


# ---------------------------------------------------------------------------
# What a deferred run actually reads
# ---------------------------------------------------------------------------
_ND_SHAPE = [
    _part(1, "BQ", "pricing"),
    _part(2, "DRG", "drawings"),
    _part(3, "ACC", "contract-conditions"),
    _part(4, "GCT", "tender-conditions"),
    _part(5, "FOT", "bid-forms"),
    _part(6, "PS7", "specifications"),
    _part(7, "PS31", "specifications"),
    _part(8, "SI", "site-information"),
]


def test_the_contract_documents_are_read_and_the_appendices_are_not():
    notes: list[str] = []
    parsed = _run(_ND_SHAPE, notes, skip_categories=s01_ingest.skip_set())
    assert parsed.clauses == []          # no readable file on disk; the partition is the subject
    said = " ".join(notes)
    assert "2 part(s) were NOT read on this run" in said       # the two specifications
    assert "2 specifications" in said


def test_including_specifications_leaves_only_the_bill_and_the_drawings_skipped():
    notes: list[str] = []
    _run(_ND_SHAPE, notes, skip_categories=s01_ingest.skip_set(include_specifications=True))
    said = " ".join(notes)
    assert "read only on request" not in said
    assert "01-bq (pricing)" in said and "02-drg (drawings)" in said


# ---------------------------------------------------------------------------
# Deferred is not dropped, and not the same statement as never-read
# ---------------------------------------------------------------------------
def test_every_deferred_part_is_named():
    """The whole argument for this shape over an allow-list. A part an allow-list omits leaves no
    trace; a part this defers is listed by id, so the operator can see exactly what was set aside."""
    notes: list[str] = []
    _run(_ND_SHAPE, notes, skip_categories=s01_ingest.skip_set())
    said = " ".join(notes)
    assert "06-ps7 (specifications)" in said
    assert "07-ps31 (specifications)" in said


def test_the_two_reasons_are_reported_separately():
    """A bill was never going to be read. A specification was set aside by this run's settings.
    Reporting them in one sentence would make the reversible one look permanent."""
    notes: list[str] = []
    _run(_ND_SHAPE, notes, skip_categories=s01_ingest.skip_set())
    deferred = [n for n in notes if "read only on request" in n]
    never = [n for n in notes if "carries priced items, not clauses" in n]
    assert len(deferred) == 1 and len(never) == 1
    assert "Re-run with specifications included" in deferred[0]
    # And the never-read note keeps its old shape exactly, down to the part ids.
    assert "01-bq (pricing)" in never[0] and "02-drg (drawings)" in never[0]


def test_the_deferral_note_does_not_claim_specifications_are_uncontractual():
    """The honest statement is "usually not worth 150 calls", never "carries no obligation" — the
    preambles are the measurement rules and the specification body carries real obligations."""
    notes: list[str] = []
    _run(_ND_SHAPE, notes, skip_categories=s01_ingest.skip_set())
    note = next(n for n in notes if "read only on request" in n)
    assert "not a claim that they carry none" in note
    assert "preambles are the measurement rules" in note


def test_a_set_of_only_specifications_is_not_told_to_upload_what_it_already_has(monkeypatch):
    """The worst available wrong message: "Upload the conditions of contract" to somebody who
    uploaded them, because this run chose not to read them. Different state, different sentence."""
    notes: list[str] = []
    _run([_part(1, "PS7", "specifications")], notes, skip_categories=s01_ingest.skip_set())
    said = " ".join(notes)
    assert "the documents ARE here" in said
    assert "Upload the conditions of contract" not in said
    assert "NO contractual document" not in said


def test_a_set_of_only_bills_still_says_upload_a_contract():
    """The original message must survive for the state it was written for — nothing was deferred
    here, so the set genuinely contains no contractual document."""
    notes: list[str] = []
    _run([_part(1, "BQ", "pricing")], notes, skip_categories=s01_ingest.skip_set())
    said = " ".join(notes)
    assert "NO contractual document" in said
    assert "Upload the conditions of contract" in said


# ---------------------------------------------------------------------------
# The skip-list property the whole shape exists for
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("category", [
    "contract-conditions", "contract-data", "tender-conditions", "bid-forms",
    "tender-instructions", "safety-requirements", "scope", "site-information", "other",
])
def test_a_category_not_named_is_read_by_default(category):
    """An allow-list would have to enumerate these, and would drop whichever one somebody forgot —
    or whichever one is added to PART_CATEGORIES next month. `other` is in here deliberately: it is
    the honestly-uncategorised bucket, and excluding it would silently drop a contractual document
    the classifier could not place."""
    notes: list[str] = []
    _run([_part(1, "X", category)], notes, skip_categories=s01_ingest.skip_set())
    assert not any("NOT read" in n for n in notes)


def test_every_category_in_both_sets_is_a_real_part_category():
    from client_boq.models import PART_CATEGORIES

    for category in s01_ingest.NON_CONTRACTUAL_CATEGORIES | s01_ingest.OPTIONAL_CATEGORIES:
        assert category in PART_CATEGORIES
