"""Three re-run defects in the ingest, all of the same shape: a second pass overwrote a first one.

**A re-split wrote the SUPERSEDED reading onto the addendum's revision.** `run_split` re-cuts at
`rev=0` — correct, a manifest edit is a better reading of the SAME document — and then interprets
each part from those rev-0 bytes. It called `save_part_context` with no `rev`, and that defaults to
`MAX(rev)`. Once an addendum had been applied, `MAX(rev)` is 1, so the old pages' summary, key
points and strategy flags were written onto the replacement's row. `load_parts` — the operative
view the review, the bill proposal and the close date all read — then returned the addendum's page
range and `source_doc` paired with the superseded document's reading. `apply_document` passes its
rev explicitly for exactly this reason; `run_split` was the one site that did not.

**One register line raised a new question every time it was queried.** `/review/approve` built an
`RFIItem` with no `rfi_id`, so `save_rfi` allocated `rfi-{COUNT+1}` and inserted. `Register.tsx`
posts one decision per click and has no clear-verdict path, so query → dismissed → query, or simply
pressing Query twice, created `rfi-002` and `rfi-003` identical to `rfi-001`. `open_rfi_count` then
over-reports, which drives the routing proposal's open-queries note, the desk card's blocking
sentence and the freeze gate — and the batch letter carried the same question to the client N times.

**`not_found` left the date it did not find.** `upsert_set_meta` merges, so writing only
`close_date_status` left `close_date`, its clause, page and quote in place from a run that DID find
one. `FolderCard.daysToClose` and the app header read `close_date` with no status check, so the
desk kept counting down to a deadline whose provenance had just vanished from the screen beside it.
"""

import pytest

from client_boq import models, store
from client_boq.models import RFIItem


# -- a question is asked once ------------------------------------------------------------------
def _query(register_item: int, question: str = "Cap the LDs at 10%") -> RFIItem:
    return RFIItem(origin=models.RFI_FROM_REGISTER, register_item=register_item,
                   clause="12.3", question=question)


def test_re_recording_a_query_on_one_line_reuses_its_question():
    conn = store.get_conn()
    try:
        first = store.save_rfi(conn, "nd-2025-04", _query(1))
        again = store.save_rfi(conn, "nd-2025-04", _query(1))

        assert again.rfi_id == first.rfi_id
        assert len(store.load_rfis(conn, "nd-2025-04")) == 1
        assert store.open_rfi_count(conn, "nd-2025-04") == 1
    finally:
        conn.close()


def test_pressing_query_three_times_does_not_ask_the_client_three_times():
    """The count drives the freeze gate, the desk card and the batch letter."""
    conn = store.get_conn()
    try:
        for _ in range(3):
            store.save_rfi(conn, "nd-2025-04", _query(1))
        assert store.open_rfi_count(conn, "nd-2025-04") == 1
    finally:
        conn.close()


def test_a_different_register_line_still_asks_its_own_question():
    conn = store.get_conn()
    try:
        a = store.save_rfi(conn, "nd-2025-04", _query(1))
        b = store.save_rfi(conn, "nd-2025-04", _query(2))

        assert a.rfi_id != b.rfi_id
        assert store.open_rfi_count(conn, "nd-2025-04") == 2
    finally:
        conn.close()


def test_a_different_set_still_asks_its_own_question():
    conn = store.get_conn()
    try:
        a = store.save_rfi(conn, "nd-2025-04", _query(1))
        store.save_rfi(conn, "ge-2026-14", _query(1))

        assert len(store.load_rfis(conn, "nd-2025-04")) == 1
        assert len(store.load_rfis(conn, "ge-2026-14")) == 1
        assert store.load_rfis(conn, "nd-2025-04")[0].rfi_id == a.rfi_id
    finally:
        conn.close()


def test_a_re_query_after_an_answer_is_a_new_question():
    """An answered question is closed history. Asking again is asking again, and overwriting the
    answer would destroy what the client actually said."""
    conn = store.get_conn()
    try:
        first = store.save_rfi(conn, "nd-2025-04", _query(1))
        conn.execute("UPDATE client_boq_rfi_items SET status = ?, answer = ? "
                     "WHERE set_id = ? AND rfi_id = ?",
                     (models.RFI_ANSWERED, "Agreed, 10%.", "nd-2025-04", first.rfi_id))
        conn.commit()
        second = store.save_rfi(conn, "nd-2025-04", _query(1))

        assert second.rfi_id != first.rfi_id
        assert len(store.load_rfis(conn, "nd-2025-04")) == 2
    finally:
        conn.close()


def test_a_question_already_sent_keeps_its_batch_and_its_wording():
    """The trade this must not make: reusing the id but writing every column would reset a SENT
    question to `draft` with no batch — losing one question instead of duplicating it. And what
    went out in the letter is a fact, not a draft to be edited under the client's feet."""
    conn = store.get_conn()
    try:
        first = store.save_rfi(conn, "nd-2025-04", _query(1, "Cap the LDs at 10%"))
        conn.execute("UPDATE client_boq_rfi_items SET status = ?, batch_id = ? "
                     "WHERE set_id = ? AND rfi_id = ?",
                     (models.RFI_SENT, "batch-001", "nd-2025-04", first.rfi_id))
        conn.commit()

        again = store.save_rfi(conn, "nd-2025-04", _query(1, "Cap the LDs at 5% instead"))

        assert again.rfi_id == first.rfi_id
        stored = store.load_rfis(conn, "nd-2025-04")[0]
        assert stored.status == models.RFI_SENT and stored.batch_id == "batch-001"
        assert stored.question == "Cap the LDs at 10%"
    finally:
        conn.close()


def test_a_draft_question_can_still_be_reworded():
    """Nothing has gone out, so editing the wording is editing a draft."""
    conn = store.get_conn()
    try:
        store.save_rfi(conn, "nd-2025-04", _query(1, "Cap the LDs at 10%"))
        store.save_rfi(conn, "nd-2025-04", _query(1, "Cap the LDs at 5% instead"))

        stored = store.load_rfis(conn, "nd-2025-04")
        assert len(stored) == 1 and stored[0].question == "Cap the LDs at 5% instead"
    finally:
        conn.close()


def test_a_question_raised_while_pricing_is_untouched_by_this():
    """Only a register line has one question. A pricing question has no `register_item` and every
    one of them is genuinely new."""
    conn = store.get_conn()
    try:
        a = store.save_rfi(conn, "nd-2025-04", RFIItem(
            origin=models.RFI_FROM_PRICING, question="Which grout mix?"))
        b = store.save_rfi(conn, "nd-2025-04", RFIItem(
            origin=models.RFI_FROM_PRICING, question="Which grout mix?"))

        assert a.rfi_id != b.rfi_id
    finally:
        conn.close()


# -- not_found clears what was found ---------------------------------------------------------------
def _seed_found(conn, set_id: str) -> None:
    store.upsert_set_meta(
        conn, set_id, close_date="2026-09-30", close_date_status="found",
        close_date_clause="4.2", close_date_page=7, close_date_part_id="01-cot",
        close_date_quote="by 12 noon on 30 September 2026")


def test_a_re_derivation_that_finds_nothing_clears_the_date_it_did_not_find():
    """The desk kept counting down: `daysToClose` and the header chip read `close_date` with no
    status check, so the deadline stayed on screen while its citation disappeared."""
    from client_boq.ingest import close_date as cd

    conn = store.get_conn()
    try:
        _seed_found(conn, "nd-2025-04")
        meta = cd.derive(conn, "nd-2025-04")     # DEMO: always not_found

        assert meta["close_date_status"] == "not_found"
        assert meta["close_date"] == ""
        assert meta["close_date_clause"] == "" and meta["close_date_quote"] == ""
        assert meta["close_date_page"] is None and meta["close_date_part_id"] == ""
    finally:
        conn.close()


def test_a_human_confirmed_date_still_outranks_a_re_derivation():
    """A person read the clause. Re-running a machine step does not outrank them — the guard that
    was already there, restated so this change cannot quietly remove it."""
    from client_boq.ingest import close_date as cd

    conn = store.get_conn()
    try:
        _seed_found(conn, "nd-2025-04")
        store.upsert_set_meta(conn, "nd-2025-04", close_date_status="confirmed")

        assert cd.derive(conn, "nd-2025-04") is None
        meta = store.load_set_meta(conn, "nd-2025-04")
        assert meta["close_date"] == "2026-09-30" and meta["close_date_status"] == "confirmed"
    finally:
        conn.close()


# -- the re-split writes revision 0 -------------------------------------------------------------------
def test_the_split_writes_its_context_onto_the_revision_it_cut(monkeypatch):
    """`run_split` cuts rev 0 and knows it — `save_parts(..., rev=0)` twelve lines above. The
    implicit "operative revision" default is only correct for `run_reinterpret`."""
    import inspect

    from client_boq.ingest import run as run_mod

    src = inspect.getsource(run_mod.run_split)
    assert "save_part_context(conn, set_id, part.part_id, context, rev=0)" in src, (
        "the split must name the revision it is writing; MAX(rev) is the addendum's")


def test_a_context_written_at_rev_zero_does_not_touch_rev_one():
    """The mechanism, at the store: two revisions of one part hold two readings."""
    from client_boq.models import PartContext, PartSpec

    conn = store.get_conn()
    try:
        spec = PartSpec(n=1, abbr="COT", slug="cot", title="Conditions of Tender",
                        start=1, end=10, category="contract", source_doc="binder.pdf")
        store.upsert_document_set(conn, set_id="nd-2025-04", name="ND", slug="nd-2025-04",
                                  status="ingested")
        store.save_parts(conn, "nd-2025-04", [spec], {spec.part_id: "a.pdf"}, rev=0)
        store.save_parts(conn, "nd-2025-04", [spec], {spec.part_id: "b.pdf"},
                         doc_id="doc-2", rev=1)
        store.save_part_context(conn, "nd-2025-04", spec.part_id,
                                PartContext(summary="REV1"), rev=1)

        store.save_part_context(conn, "nd-2025-04", spec.part_id,
                                PartContext(summary="REV0"), rev=0)

        operative = {s.part_id: c.summary for s, _p, c in store.load_parts(conn, "nd-2025-04")}
        assert operative[spec.part_id] == "REV1", "the addendum's reading survives the re-split"
    finally:
        conn.close()
