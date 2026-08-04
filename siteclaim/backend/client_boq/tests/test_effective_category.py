"""Two categories, and both consumers were reading the worse one.

The `{pricing, drawings}` skip-list did not fire on the document it was written for. The planner
categorised a 26-page bill of quantities as `other`, so the review read all 26 pages as a contract
document — roughly ten minutes and a dozen model calls, every one hitting the 8,000-token ceiling,
producing findings like "No letter of offer in the document set" about documents nobody uploaded.
The Route tab, keying on the same field, reported "No part is categorised 'pricing'" and made the
operator find the bill by hand.

Neither was a case of the label being wrong in a way nothing could know. `s02_interpret` chooses a
category AFTER reading the part's pages and images, persists it to `client_boq_part_contexts`, and
`store.load_parts` returns it as the third element of every tuple. Both consumers discarded it and
read the planner's guess — made from a digest containing no body text at all.

Widening the skip-list would not have fixed this: `other` is the honest-unknown bucket and adding it
would silently drop every genuinely uncategorised contract document.
"""

from client_boq.models import PartContext, PartSpec
from client_boq.review.s01_ingest import effective_category


def _part(n=1, abbr="BQ", category="other", title="Bills of Quantities"):
    return PartSpec(n=n, abbr=abbr, slug=abbr.lower(), title=title,
                    start=1, end=26, category=category)


def _ctx(category="pricing", readable=True, part_id="01-bq"):
    return PartContext(part_id=part_id, category=category, readable=readable)


# -- the ruling: prefer the reader over the guesser ---------------------------------------------
def test_the_interpreted_category_wins():
    """The night's document exactly: planner said `other`, interpreter read the pages and said
    `pricing`."""
    assert effective_category(_part(category="other"), _ctx("pricing")) == ("pricing", "interpreted")


def test_the_planners_guess_stands_when_there_is_no_context():
    """A set that never reached the interpreter behaves exactly as before."""
    assert effective_category(_part(category="specifications"), None) == \
        ("specifications", "planned")


def test_an_unreadable_part_falls_back_to_the_planner():
    """The one case the interpreter's answer is worth nothing: it did not read anything, so its
    category is its own default rather than a judgement about this document."""
    assert effective_category(_part(category="pricing"), _ctx("other", readable=False)) == \
        ("pricing", "planned")


def test_an_empty_interpreted_category_falls_back():
    assert effective_category(_part(category="drawings"), _ctx("")) == ("drawings", "planned")


def test_the_answer_is_normalised():
    assert effective_category(_part(category="  PRICING  "), None) == ("pricing", "planned")
    assert effective_category(_part(), _ctx("  Pricing ")) == ("pricing", "interpreted")


def test_the_interpreter_can_also_RESCUE_a_document_the_planner_condemned():
    """The inverse of the failure, and the reason this is a preference rather than a union: a
    contract document the planner mislabelled `pricing` must be READ once the interpreter has
    seen it is conditions of contract."""
    assert effective_category(_part(category="pricing"), _ctx("contract-conditions")) == \
        ("contract-conditions", "interpreted")


# -- the review, keyed on the better answer -----------------------------------------------------
def _run(parts, notes, contexts=None):
    from client_boq.review import s01_ingest

    return s01_ingest.ingest_from_parts(
        [(p, "") for p in parts], "ND/2025/04", on_note=notes.append, contexts=contexts,
    )


def test_the_bill_that_slipped_through_is_now_skipped():
    notes: list[str] = []
    part = _part(category="other")
    _run([part], notes, contexts={part.part_id: _ctx("pricing", part_id=part.part_id)})
    assert any("were NOT read for contractual positions" in n for n in notes)


def test_the_skip_says_which_category_decided_it():
    """A reader who sees a skip has to be able to tell whether a document was skipped on evidence
    or on a guess."""
    notes: list[str] = []
    part = _part(category="other")
    _run([part], notes, contexts={part.part_id: _ctx("pricing", part_id=part.part_id)})
    assert "01-bq (pricing) on the interpreter's reading" in notes[0]

    notes.clear()
    _run([_part(category="pricing")], notes)
    assert "01-bq (pricing) on the planner's guess" in notes[0]


def test_a_contract_document_the_planner_mislabelled_is_still_read():
    notes: list[str] = []
    part = _part(category="pricing", abbr="SCC", title="Special Conditions of Contract")
    _run([part], notes, contexts={part.part_id: _ctx("contract-conditions", part_id=part.part_id)})
    assert notes == []                       # read, not skipped


def test_a_set_of_only_bills_still_says_so_honestly():
    notes: list[str] = []
    part = _part(category="other")
    parsed = _run([part], notes, contexts={part.part_id: _ctx("pricing", part_id=part.part_id)})
    assert parsed.clauses == []
    assert any("NO contractual document" in n for n in notes)


def test_no_contexts_at_all_is_the_old_behaviour():
    """The two-tuple signature is unchanged, so a caller with no contexts gets exactly what it
    got before — which is what keeps the loose-upload path and the existing tests intact."""
    notes: list[str] = []
    _run([_part(category="pricing")], notes)
    assert any("were NOT read" in n for n in notes)
