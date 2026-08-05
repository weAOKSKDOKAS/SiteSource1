"""Unit tests for REVIEW s08 (citation verify) — the deterministic anti-hallucination guard.

Asserts a cited clause that is absent from the parsed set, and a quote that is not contained in its
clause, are both marked ``citation_failed`` and kept visible; a real, supported citation passes; and
an unresolved line (no clause) is skipped.
"""

from __future__ import annotations

from client_boq.models import (
    STATUS_CANDIDATE,
    STATUS_CITATION_FAILED,
    STATUS_RULE_FLAGGED,
    STATUS_UNRESOLVED,
    ClauseItem,
    DepartureItem,
    DepartureRegister,
    ParsedDocumentSet,
)
from client_boq.review.s08_citation_verify import clause_candidates, verify_citations


def _parsed() -> ParsedDocumentSet:
    return ParsedDocumentSet(
        set_id="t", name="t", slug="t",
        clauses=[
            ClauseItem(clause_id="8.3", text="Liquidated damages apply with no cap on the aggregate amount."),
            ClauseItem(clause_id="5.2", text="Retention of 10% held to the Final Certificate."),
        ],
    )


def test_missing_clause_and_bad_quote_fail_present_ones_pass() -> None:
    register = DepartureRegister(
        set_id="t",
        items=[
            DepartureItem(item=1, clause="8.3", cited_text="no cap on the aggregate amount",
                          status=STATUS_RULE_FLAGGED),                       # real + supported -> ok
            DepartureItem(item=2, clause="5.2", cited_text="a phrase that is not in the clause",
                          status=STATUS_RULE_FLAGGED),                       # present but unsupported -> fail
            DepartureItem(item=3, clause="13.5", cited_text="call security without notice",
                          status=STATUS_CANDIDATE),                          # absent clause -> fail
            DepartureItem(item=4, clause="", criterion_id="TP-02", status=STATUS_UNRESOLVED),  # skipped
        ],
    )
    checks = verify_citations(register, _parsed())

    by_item = {c.item: c for c in checks}
    assert by_item[1].ok is True
    assert by_item[2].found is True and by_item[2].supported is False
    assert by_item[3].found is False
    # The unresolved line (no clause) produced no check.
    assert 4 not in by_item

    status = {d.item: d.status for d in register.items}
    assert status[1] == STATUS_RULE_FLAGGED               # unchanged
    assert status[2] == STATUS_CITATION_FAILED            # bad quote
    assert status[3] == STATUS_CITATION_FAILED            # absent clause
    assert status[4] == STATUS_UNRESOLVED                 # untouched
    # Nothing was dropped — the failed lines are still present, just marked.
    assert len(register.items) == 4


# ---------------------------------------------------------------------------
# Reference formatting — measured against the first live run (2026-08-01)
# ---------------------------------------------------------------------------
# Ten of seventy-five register lines were reported as citing a clause "not in the document set".
# None of them was wrong. The stages that produce findings do not all write a reference the way
# the clause index is keyed, and the index keys clauses at the numbered level only.
def test_clause_candidates_handles_the_formats_the_live_stages_actually_produced() -> None:
    # s04 scope-align: several clauses in one string, because the finding is about a CONFLICT.
    assert clause_candidates("8.1; 2.3; 10.1")[1:] == ["8.1", "2.3", "10.1"]
    # s05 programme: the document name in front of the id.
    assert "4.13" in clause_candidates("CIC Conditions of Tender, Clause 4.13")
    # Both at once, joined by a word rather than a separator.
    assert {"3.1", "6.1"} <= set(clause_candidates("CIC Conditions of Tender, Clauses 3.1 and 6.1"))
    # A sub-clause limb must fall back to its parent: the live CIC parse holds '4.4', never '4.4(b)'.
    assert "4.4" in clause_candidates("4.4(b)")
    assert "1.2" in clause_candidates("1.2(d); 2.1; 4.3")
    # An already-clean reference is unchanged, and stays first.
    assert clause_candidates("4.13") == ["4.13"]


def test_a_prose_reference_resolves_to_the_same_clause_a_bare_one_does() -> None:
    """The proof that these were format failures, not missing clauses: on the live register the
    criteria stage cited '4.13' and passed while the programme stage cited
    'CIC Conditions of Tender, Clause 4.13' — the identical clause — and failed."""
    parsed = ParsedDocumentSet(
        set_id="t", name="t", slug="t",
        clauses=[ClauseItem(clause_id="4.13", text="The tender shall remain open for 90 days.")],
    )
    register = DepartureRegister(set_id="t", project="t", package="t", items=[
        DepartureItem(item=1, clause="4.13", cited_text="remain open for 90 days",
                      status=STATUS_CANDIDATE),
        DepartureItem(item=2, clause="CIC Conditions of Tender, Clause 4.13",
                      cited_text="remain open for 90 days", status=STATUS_CANDIDATE),
    ])
    verify_citations(register, parsed)
    assert [i.status for i in register.items] == [STATUS_CANDIDATE, STATUS_CANDIDATE]


# ---------------------------------------------------------------------------
# Composite quotations — a finding about a conflict quotes from several clauses
# ---------------------------------------------------------------------------
def _conflict_parsed() -> ParsedDocumentSet:
    return ParsedDocumentSet(
        set_id="t", name="t", slug="t",
        clauses=[
            ClauseItem(clause_id="1.2", text="The tender documents consist of the following parts."),
            ClauseItem(clause_id="2.1", text="Tenderers are invited to submit a proposal and bid."),
            ClauseItem(clause_id="4.3", text="The tenderer shall state the implementation plan."),
        ],
    )


def test_a_quote_stitched_from_several_cited_clauses_is_supported() -> None:
    """Each fragment lives in a DIFFERENT one of the cited clauses. Checking the whole quotation
    against any single clause has no possible right answer — it is why these lines failed 100% of
    the time on the live run regardless of whether the quotation was honest."""
    register = DepartureRegister(set_id="t", project="t", package="t", items=[
        DepartureItem(
            item=1, clause="1.2(d); 2.1; 4.3", status=STATUS_CANDIDATE,
            cited_text=("The tender documents consist of ... Tenderers are invited to submit "
                        "... the implementation plan"),
        ),
    ])
    verify_citations(register, _conflict_parsed())
    assert register.items[0].status == STATUS_CANDIDATE


def test_one_invented_fragment_still_fails_the_whole_citation() -> None:
    """The half of the guard that matters is untouched: support must come from the clauses the
    line actually cites, and a fabricated fragment is in none of them."""
    register = DepartureRegister(set_id="t", project="t", package="t", items=[
        DepartureItem(
            item=1, clause="1.2; 2.1", status=STATUS_CANDIDATE,
            cited_text="The tender documents consist of ... the Employer shall indemnify the Contractor",
        ),
    ])
    checks = verify_citations(register, _conflict_parsed())
    assert register.items[0].status == STATUS_CITATION_FAILED
    assert "indemnify" in checks[0].note


def test_a_sentence_period_before_an_ellipsis_is_not_mistaken_for_one() -> None:
    """A real quotation reads 'cost incurred. ... There shall be'. A split pattern that allows
    whitespace BETWEEN the dots eats the sentence period plus two ellipsis dots and leaves '. There
    shall be', whose leading period then fails containment. That regression cost 2 of 4 remaining
    live failures before it was caught."""
    parsed = ParsedDocumentSet(
        set_id="t", name="t", slug="t",
        clauses=[
            ClauseItem(clause_id="4.25", text="The tender price shall deem to be included all cost incurred."),
            ClauseItem(clause_id="4.4", text="There shall be no adjustment for any price fluctuations."),
        ],
    )
    register = DepartureRegister(set_id="t", project="t", package="t", items=[
        DepartureItem(item=1, clause="4.25; 4.4", status=STATUS_CANDIDATE,
                      cited_text="included all cost incurred. ... There shall be no adjustment"),
    ])
    verify_citations(register, parsed)
    assert register.items[0].status == STATUS_CANDIDATE


def test_a_clause_that_genuinely_is_not_in_the_set_still_fails_and_says_what_it_tried() -> None:
    register = DepartureRegister(set_id="t", project="t", package="t", items=[
        DepartureItem(item=1, clause="Schedule 7, Clause 99.9", cited_text="anything",
                      status=STATUS_CANDIDATE),
    ])
    checks = verify_citations(register, _conflict_parsed())
    assert register.items[0].status == STATUS_CITATION_FAILED
    assert "not in the document set" in checks[0].note
    assert "99.9" in checks[0].note  # names what it tried, so a real miss stays legible


def test_a_recorded_human_verdict_is_never_overwritten() -> None:
    """s08 runs once in the normal flow, before anyone has decided anything — so it never had to
    guard verdicts. That stops being true the moment it is re-run over a register somebody has
    worked, and a re-verify would silently turn a person's `dismissed` into `citation_failed`,
    losing the decision with no trace. Caught doing exactly that to two dismissed lines on the live
    CIC register while re-verifying it."""
    parsed = ParsedDocumentSet(
        set_id="t", name="t", slug="t",
        clauses=[ClauseItem(clause_id="4.1", text="Something entirely unrelated.")],
    )
    register = DepartureRegister(set_id="t", project="t", package="t", items=[
        # Would fail the guard on its merits — the quote is nowhere in 4.1 — but a person has ruled.
        DepartureItem(item=1, clause="4.1", cited_text="a quotation that is not there",
                      status="dismissed"),
        DepartureItem(item=2, clause="4.1", cited_text="a quotation that is not there",
                      status="confirmed"),
        DepartureItem(item=3, clause="4.1", cited_text="a quotation that is not there",
                      status=STATUS_CANDIDATE),
    ])
    verify_citations(register, parsed)
    assert [i.status for i in register.items] == ["dismissed", "confirmed", STATUS_CITATION_FAILED]
