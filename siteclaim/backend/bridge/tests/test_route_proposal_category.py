"""The Route tab proposes the bill the INTERPRETER identified, not the one the planner guessed.

Route reported "No part is categorised 'pricing', so nothing is proposed" about a 26-page bill of
quantities, and the operator had to find it by hand. Same root cause as the review's skip-list:
`PartSpec.category` is the planning call's guess from a digest with no body text, while
`PartContext.category` is the interpreter's answer after reading the pages — and
`store.load_parts` was already handing this module both, as `(spec, path, _c)`.

These live in `bridge/tests/` rather than beside the other category tests because standing a real
client_boq set up needs this package's `make_set` / `part_spec` fixtures.
"""

from client_boq.models import PartContext
from client_boq.review.s01_ingest import effective_category


def test_route_proposes_the_bill_the_interpreter_identified(make_set, part_spec):
    from bridge import parts as parts_mod
    from client_boq import store as cb_store

    spec = part_spec(1, "BQ", "Bills of Quantities", "other", start=1, end=26)
    make_set("nd-2025-04", "ND/2025/04", [spec], pdf_paths={"01-bq": ""})
    conn = cb_store.get_conn()
    try:
        cb_store.save_part_context(conn, "nd-2025-04", "01-bq",
                                   PartContext(part_id="01-bq", category="pricing", readable=True))
    finally:
        conn.close()

    body = parts_mod.bq_candidates("nd-2025-04")
    assert body["proposed"] == ["01-bq"]           # was [] — "No part is categorised 'pricing'"
    assert "pre-selected" in body["message"]


def test_route_proposes_nothing_when_neither_category_says_pricing(make_set, part_spec):
    from bridge import parts as parts_mod

    make_set("ge-2026-14", "GE/2026/14",
             [part_spec(1, "CT", "Conditions of Tender", "tender-instructions")],
             pdf_paths={"01-ct": ""})

    body = parts_mod.bq_candidates("ge-2026-14")
    assert body["proposed"] == []
    assert "neither by the interpreter" in body["message"]   # says which authorities were consulted


def test_an_unreadable_part_keeps_the_planners_guess(make_set, part_spec):
    """The interpreter read nothing, so its category is its own default rather than a judgement
    about this document — the planner\'s guess is the better of the two here."""
    from bridge import parts as parts_mod
    from client_boq import store as cb_store

    spec = part_spec(1, "BQ", "Bills of Quantities", "pricing", scanned=True)
    make_set("nd-2025-04", "ND/2025/04", [spec], pdf_paths={"01-bq": ""})
    conn = cb_store.get_conn()
    try:
        cb_store.save_part_context(conn, "nd-2025-04", "01-bq",
                                   PartContext(part_id="01-bq", category="other", readable=False))
    finally:
        conn.close()

    assert parts_mod.bq_candidates("nd-2025-04")["proposed"] == ["01-bq"]


def test_route_and_the_review_cannot_disagree_about_what_a_part_is():
    """One function, two consumers. They read the same answer, so a part cannot be proposed as the
    priced bill on one screen and read as a contract document on another."""
    import inspect

    from bridge import parts as parts_mod

    assert parts_mod.effective_category is effective_category
    assert "effective_category" in inspect.getsource(parts_mod.candidates_on)
