"""Re-running the review destroyed every verdict and left the gate saying APPROVED.

The register is one JSON blob in one column, so a re-run replaced it wholesale. Every `confirmed`
went back to `candidate`, every `decided_by` emptied, every line of negotiation text the operator
had typed was gone — and `client_boq_review_registers.approved` still read 1, because
`save_register` correctly never touches it. Probed::

    after approve   : {'12.3': ('confirmed', 'R. Lam', 'we press this'), '14.1': ('dismissed', ...)}
    after RE-review : {'12.3': ('candidate', '', ''),                    '14.1': ('candidate', ...)}

That is the worst state the gate can hold: APPROVED over a register nobody has read, and the
estimate opens on it.

The same class as `/route/analyze` wiping a confirmed route — a Layer-1 recomputation erasing the
Layer-4 gate it exists to inform — and it needed the same two answers: carry what the human owns
onto the line it was ABOUT, and be loud about whatever cannot be carried.

**Identity is not position.** `s07.assemble_register` numbers lines 1..N at assembly, so `item.item`
moves the moment a clause is added or dropped — carrying on the number would have attached one
line's verdict to a different departure, which is worse than losing it.

**A machine status is the fresh run's to state.** Only `confirmed`/`dismissed`/`query` travel.
Re-reading the document is the entire point of re-running it.
"""

import pytest

from client_boq import models, store
from client_boq.models import DepartureItem, DepartureRegister


def _item(clause: str, criterion: str = "", **kw) -> DepartureItem:
    kw.setdefault("source", models.SOURCE_CRITERIA)
    return DepartureItem(clause=clause, criterion_id=criterion, **kw)


def _reg(*items: DepartureItem) -> DepartureRegister:
    for i, item in enumerate(items, start=1):
        item.item = i
    return DepartureRegister(set_id="nd-2025-04", items=list(items))


def _view(reg: DepartureRegister) -> dict:
    return {i.clause or i.rationale: (i.status, i.decided_by) for i in reg.items}


# -- the verdict travels ---------------------------------------------------------------------------
def test_a_confirmed_verdict_survives_a_re_review():
    previous = _reg(_item("12.3", "C-01", status=models.STATUS_CONFIRMED, decided_by="R. Lam",
                          register_status="closed"))
    fresh = _reg(_item("12.3", "C-01", status=models.STATUS_CANDIDATE))

    assert store.carry_human_decisions(previous, fresh) == []
    assert fresh.items[0].status == models.STATUS_CONFIRMED
    assert fresh.items[0].decided_by == "R. Lam"
    assert fresh.items[0].register_status == "closed"


def test_the_negotiation_text_travels_with_it():
    """What someone typed into "what you will negotiate instead" is not recoverable from anywhere."""
    previous = _reg(_item("12.3", "C-01", status=models.STATUS_CONFIRMED,
                          contractor_response="cap at 5% of contract sum",
                          client_response="under consideration"))
    fresh = _reg(_item("12.3", "C-01"))
    store.carry_human_decisions(previous, fresh)

    assert fresh.items[0].contractor_response == "cap at 5% of contract sum"
    assert fresh.items[0].client_response == "under consideration"


def test_a_verdict_follows_its_departure_not_its_line_number():
    """s07 numbers lines at assembly. Add one clause and every number below it shifts, so carrying
    on the number attaches a verdict to a DIFFERENT departure — worse than losing it."""
    previous = _reg(_item("12.3", "C-01", status=models.STATUS_CONFIRMED),
                    _item("14.1", "C-02", status=models.STATUS_DISMISSED))
    fresh = _reg(_item("9.9", "C-00"),                      # a new line, first
                 _item("14.1", "C-02"), _item("12.3", "C-01"))
    store.carry_human_decisions(previous, fresh)

    assert _view(fresh) == {"9.9": (models.STATUS_CANDIDATE, ""),
                            "14.1": (models.STATUS_DISMISSED, ""),
                            "12.3": (models.STATUS_CONFIRMED, "")}


def test_a_query_travels_and_stays_open():
    """A query is a verdict — a human decided to ask — and its RFI still exists."""
    previous = _reg(_item("12.3", "C-01", status=models.STATUS_QUERY, register_status="open"))
    fresh = _reg(_item("12.3", "C-01"))
    store.carry_human_decisions(previous, fresh)

    assert fresh.items[0].status == models.STATUS_QUERY
    assert fresh.items[0].register_status == "open"


def test_an_unanchored_finding_is_matched_on_what_it_says():
    """s04's input-gap lines carry neither a clause nor a criterion, and there are several of them
    — their own wording is the only thing that tells them apart."""
    a = _item("", source=models.SOURCE_SCOPE_ALIGNMENT, kind="input_missing",
              rationale="No priced bill of quantities in the document set",
              status=models.STATUS_DISMISSED)
    b = _item("", source=models.SOURCE_SCOPE_ALIGNMENT, kind="input_missing",
              rationale="No programme in the document set")
    fresh = _reg(_item("", source=models.SOURCE_SCOPE_ALIGNMENT, kind="input_missing",
                       rationale="No programme in the document set"),
                 _item("", source=models.SOURCE_SCOPE_ALIGNMENT, kind="input_missing",
                       rationale="No priced bill of quantities in the document set"))
    store.carry_human_decisions(_reg(a, b), fresh)

    assert [i.status for i in fresh.items] == [models.STATUS_CANDIDATE, models.STATUS_DISMISSED]


# -- what does NOT travel ---------------------------------------------------------------------------
def test_a_machine_status_is_the_fresh_runs_to_state():
    """Re-reading the document is the point of re-running it: the new `rule_flagged` stands."""
    previous = _reg(_item("12.3", "C-01", status=models.STATUS_CANDIDATE))
    fresh = _reg(_item("12.3", "C-01", status=models.STATUS_RULE_FLAGGED, rule_ref="R-04"))

    assert store.carry_human_decisions(previous, fresh) == []
    assert fresh.items[0].status == models.STATUS_RULE_FLAGGED


def test_a_verdict_is_not_carried_onto_a_line_whose_citation_no_longer_verifies():
    """`/review/approve` refuses to confirm a `citation_failed` line at all, so carrying one in
    would smuggle past the very gate that refusal is."""
    previous = _reg(_item("12.3", "C-01", status=models.STATUS_CONFIRMED,
                          contractor_response="cap at 5%"))
    fresh = _reg(_item("12.3", "C-01", status=models.STATUS_CITATION_FAILED,
                       citation_note="quote not found in the cited part"))
    lost = store.carry_human_decisions(previous, fresh)

    assert fresh.items[0].status == models.STATUS_CITATION_FAILED
    assert len(lost) == 1 and "no longer verifies" in lost[0]
    assert fresh.items[0].contractor_response == "cap at 5%", \
        "the typed text is not a verdict and is not recoverable from anywhere else"


def test_a_line_the_re_read_no_longer_produces_is_named():
    previous = _reg(_item("99.9", "C-09", status=models.STATUS_CONFIRMED))
    lost = store.carry_human_decisions(previous, _reg(_item("12.3", "C-01")))

    assert len(lost) == 1
    assert "99.9" in lost[0] and "no longer produces" in lost[0]


def test_an_ambiguous_identity_is_refused_rather_than_guessed():
    """Two lines sharing one identity: attaching the verdict to the wrong one is a departure
    schedule that says a person accepted something they never saw."""
    previous = _reg(_item("12.3", "C-01", status=models.STATUS_CONFIRMED))
    fresh = _reg(_item("12.3", "C-01"), _item("12.3", "C-01"))
    lost = store.carry_human_decisions(previous, fresh)

    assert all(i.status == models.STATUS_CANDIDATE for i in fresh.items)
    assert len(lost) == 1 and "share its identity" in lost[0]


def test_an_undecided_line_is_not_reported_as_a_loss():
    """A report that fires on every re-run is a report nobody reads."""
    previous = _reg(_item("12.3", "C-01", status=models.STATUS_CANDIDATE))
    assert store.carry_human_decisions(previous, _reg(_item("14.1", "C-02"))) == []


def test_no_previous_register_carries_nothing_and_reports_nothing():
    assert store.carry_human_decisions(None, _reg(_item("12.3", "C-01"))) == []


# -- the gate ----------------------------------------------------------------------------------------
def test_a_re_review_that_loses_a_verdict_re_opens_the_gate(monkeypatch, tmp_path):
    """The register the human approved is not this register, so the sign-off does not describe it.

    Re-opening is the only gate move any stage makes, and only ever in this direction — the approve
    endpoint stays the sole writer of an APPROVAL.
    """
    from client_boq.review import run as run_mod

    conn = store.get_conn()
    try:
        store.save_register(conn, _reg(_item("99.9", "C-09", status=models.STATUS_CONFIRMED,
                                             decided_by="R. Lam")))
        store.set_review_approved(conn, "nd-2025-04", True)
    finally:
        conn.close()

    notes: list[str] = []
    monkeypatch.setattr(run_mod.s07_register, "assemble_register",
                        lambda *a, **kw: _reg(_item("12.3", "C-01")))
    run_mod.run_review([("terms.pdf", "application/pdf", b"%PDF-1.4 terms")],
                       set_id="nd-2025-04", on_note=notes.append)

    conn = store.get_conn()
    try:
        assert store.review_is_approved(conn, "nd-2025-04") is False
    finally:
        conn.close()
    assert any("re-opened" in n for n in notes), notes
    assert any("99.9" in n and "no longer produces" in n for n in notes), notes


def test_a_re_review_that_carries_everything_leaves_the_gate_alone(monkeypatch, tmp_path):
    """The register IS the approved register — re-opening it would be a false alarm, and the
    operator would learn to click through the next one.

    The line cites no clause (an unresolved criterion), which is the register shape s08's citation
    guard skips — so this test is about the carry and the gate, not about citation verification.
    """
    from client_boq.review import run as run_mod

    conn = store.get_conn()
    try:
        store.save_register(conn, _reg(_item("", "C-01", status=models.STATUS_CONFIRMED,
                                             decided_by="R. Lam")))
        store.set_review_approved(conn, "nd-2025-04", True)
    finally:
        conn.close()

    notes: list[str] = []
    monkeypatch.setattr(run_mod.s07_register, "assemble_register",
                        lambda *a, **kw: _reg(_item("", "C-01")))
    register = run_mod.run_review([("terms.pdf", "application/pdf", b"%PDF-1.4 terms")],
                                  set_id="nd-2025-04", on_note=notes.append)

    conn = store.get_conn()
    try:
        assert store.review_is_approved(conn, "nd-2025-04") is True
    finally:
        conn.close()
    assert register.items[0].status == models.STATUS_CONFIRMED
    assert register.items[0].decided_by == "R. Lam"
    assert not any("re-opened" in n for n in notes), notes


def test_an_unapproved_set_is_not_reported_as_re_opened(monkeypatch, tmp_path):
    """Nothing to re-open. The lost verdicts are still named — they were still decided."""
    from client_boq.review import run as run_mod

    conn = store.get_conn()
    try:
        store.save_register(conn, _reg(_item("99.9", "C-09", status=models.STATUS_DISMISSED)))
    finally:
        conn.close()

    notes: list[str] = []
    monkeypatch.setattr(run_mod.s07_register, "assemble_register",
                        lambda *a, **kw: _reg(_item("12.3", "C-01")))
    run_mod.run_review([("terms.pdf", "application/pdf", b"%PDF-1.4 terms")],
                       set_id="nd-2025-04", on_note=notes.append)

    assert not any("re-opened" in n for n in notes), notes
    assert any("99.9" in n for n in notes), notes


def test_the_first_review_of_a_set_reports_nothing(monkeypatch, tmp_path):
    from client_boq.review import run as run_mod

    notes: list[str] = []
    monkeypatch.setattr(run_mod.s07_register, "assemble_register",
                        lambda *a, **kw: _reg(_item("12.3", "C-01")))
    run_mod.run_review([("terms.pdf", "application/pdf", b"%PDF-1.4 terms")],
                       set_id="nd-2025-04", on_note=notes.append)

    assert not any("Verdict not carried" in n for n in notes), notes


# -- the reopen-on-amendment path is untouched -----------------------------------------------------
def test_reopening_a_line_for_an_amended_part_is_not_undone_by_this():
    """`reopen_verdicts_for_parts` deliberately clears verdicts and saves — the carry-over must not
    live in `save_register`, or it would put back exactly what that function just removed."""
    import inspect

    src = inspect.getsource(store.save_register)
    assert "carry_human_decisions" not in src, (
        "the carry-over belongs at the seam where a FRESH assembly replaces a stored register, "
        "not on every write")
