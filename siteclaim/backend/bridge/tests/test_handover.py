"""The handover package — a read-only projection of a won tender, and the closeout aggregate read.

Nothing is re-typed; every section is read back from an artifact that already exists, and anything
absent is NAMED rather than silently dropped.
"""

import pytest

from bridge import closeout
from client_boq import store
from client_boq.models import (
    DepartureItem,
    DepartureRegister,
    Estimate,
    EstimateTotals,
    LetterOfOffer,
    ScopeItem,
)

SET = "nd-2025-04"


def _seed_full() -> None:
    conn = store.get_conn()
    try:
        store.upsert_document_set(conn, set_id=SET, name="ND/2025/04", slug=SET, status="estimated")
        store.save_letter(conn, LetterOfOffer(set_id=SET, price=1_250_000.0, price_str="HK$1,250,000"))
        store.save_estimate(conn, Estimate(set_id=SET, totals=EstimateTotals(
            total_direct=900_000.0, total_indirect=150_000.0, total_cost=1_050_000.0,
            margin_pct=19.0, price=1_250_000.0)))
        store.save_register(conn, DepartureRegister(set_id=SET, items=[
            DepartureItem(item=1, clause="12.3", criterion_id="C-01", status="confirmed",
                          proposed_position="Cap LDs at 10% of the contract sum."),
            DepartureItem(item=2, clause="14.1", criterion_id="C-02", status="candidate"),
        ]))
        store.save_scope_item(conn, SET, ScopeItem(
            section="inclusions", title="Rotary drilling", text="500m of rotary core drilling.",
            badge="user"))
    finally:
        conn.close()


# -- gated on won -----------------------------------------------------------------------------------
def test_handover_is_not_ready_before_won():
    _seed_full()
    h = closeout.assemble_handover(SET)
    assert h["ready"] is False
    assert "not marked 'won'" in h["pending"]
    assert "PREVIEW" in h["markdown"]


def test_handover_is_ready_once_won():
    _seed_full()
    closeout.set_outcome(SET, "won", "Awarded at HK$1.25m.")
    h = closeout.assemble_handover(SET)

    assert h["ready"] is True and h["pending"] == ""
    assert "PREVIEW" not in h["markdown"]
    assert "Handover — ND/2025/04" in h["markdown"]


def test_a_lost_tender_is_not_handover_ready():
    _seed_full()
    closeout.set_outcome(SET, "lost")
    assert closeout.assemble_handover(SET)["ready"] is False


# -- it projects the real artifacts -----------------------------------------------------------------
def test_the_projection_reads_the_existing_artifacts():
    _seed_full()
    closeout.set_outcome(SET, "won")
    closeout.add_lesson(SET, "pricing", "Rock rate was light.")
    closeout.log_event(SET, "clarification", "Confirmed prelims include the cabin.")
    md = closeout.assemble_handover(SET)["markdown"]

    assert "HK$1,250,000" in md, "the price is read from the letter"
    assert "total cost 1050000.0" in md, "the cost baseline is read from the estimate"
    assert "Rotary drilling" in md, "the scope of record is read"
    assert "Cap LDs at 10%" in md, "only the CONFIRMED register position is carried"
    assert "Cap LDs" in md and "14.1" not in md, "the candidate line is not a confirmed position"
    assert "Rock rate was light" in md and "cabin" in md


def test_nothing_is_re_typed_it_is_read_back():
    """The projection holds no authored fields — it is the stored data laid out."""
    _seed_full()
    closeout.set_outcome(SET, "won")
    sections = closeout.assemble_handover(SET)["sections"]

    assert sections["price"]["price"] == 1_250_000.0
    assert sections["estimate_totals"]["total_cost"] == 1_050_000.0
    assert [p["clause"] for p in sections["confirmed_positions"]] == ["12.3"]


# -- missing pieces are named, never dropped --------------------------------------------------------
def test_a_bare_tender_names_every_missing_piece():
    closeout.set_outcome(SET, "won")
    h = closeout.assemble_handover(SET)

    joined = " | ".join(h["missing"])
    for piece in ("bill part", "scope of record", "priced estimate", "review register",
                  "submission record"):
        assert piece in joined, f"{piece!r} not named in {h['missing']}"
    assert "Not yet available" in h["markdown"]


def test_a_seeded_piece_drops_off_the_missing_list():
    _seed_full()
    closeout.set_outcome(SET, "won")
    missing = " | ".join(closeout.assemble_handover(SET)["missing"])

    assert "scope of record" not in missing
    assert "priced estimate" not in missing
    assert "review register" not in missing
    assert "bill part" in missing, "still genuinely absent, still named"


# -- the closeout aggregate read --------------------------------------------------------------------
def test_closeout_state_aggregates_the_three_logs():
    closeout.set_outcome(SET, "won", "Awarded.")
    closeout.add_lesson(SET, "scope", "Tighten the exclusions.")
    closeout.log_event(SET, "negotiation", "Agreed a 2-week extension of time.")
    state = closeout.closeout_state(SET)

    assert state["outcome"]["status"] == "won"
    assert len(state["lessons"]) == 1 and len(state["events"]) == 1
    assert state["handover_ready"] is True


def test_closeout_state_is_not_ready_without_a_won():
    closeout.set_outcome(SET, "submitted")
    assert closeout.closeout_state(SET)["handover_ready"] is False


def test_closeout_state_of_an_untouched_tender_is_empty_not_an_error():
    state = closeout.closeout_state("never-touched")
    assert state["outcome"] is None and state["lessons"] == [] and state["events"] == []
    assert state["handover_ready"] is False


def test_an_empty_set_id_is_refused():
    with pytest.raises(ValueError):
        closeout.assemble_handover("")
