"""The post-submission change-control log — light, append-only, ordered. Not a re-pricing engine."""

import pytest

from bridge import closeout


def test_an_event_is_logged_and_listed():
    row = closeout.log_event("nd-2025-04", "clarification",
                             "Client asked whether prelims include the site cabin — confirmed yes.")
    assert row["kind"] == "clarification" and "site cabin" in row["detail"]
    assert [e["id"] for e in closeout.list_events("nd-2025-04")] == [row["id"]]


def test_events_list_oldest_first():
    for i in range(3):
        closeout.log_event("nd-2025-04", "note", f"event {i}")
    assert [e["detail"] for e in closeout.list_events("nd-2025-04")] == ["event 0", "event 1", "event 2"]


@pytest.mark.parametrize("kind", ["clarification", "negotiation", "change", "note"])
def test_every_known_kind_is_kept(kind):
    assert closeout.log_event("nd-2025-04", kind, "x")["kind"] == kind


def test_an_unknown_kind_falls_to_note():
    assert closeout.log_event("nd-2025-04", "escalation", "x")["kind"] == "note"


@pytest.mark.parametrize("blank", ["", "  ", "\t"])
def test_an_empty_detail_is_refused(blank):
    with pytest.raises(ValueError, match="an event needs a detail"):
        closeout.log_event("nd-2025-04", "change", blank)


def test_the_log_is_append_only_never_replaced():
    """Two entries of the same kind are two rows, not one upserted row — a trail you can rewrite is
    not a trail."""
    closeout.log_event("nd-2025-04", "negotiation", "first")
    closeout.log_event("nd-2025-04", "negotiation", "second")
    assert len(closeout.list_events("nd-2025-04")) == 2


def test_two_tenders_keep_their_own_logs():
    closeout.log_event("nd-2025-04", "note", "A")
    closeout.log_event("ge-2026-14", "note", "B")
    assert [e["detail"] for e in closeout.list_events("nd-2025-04")] == ["A"]
    assert [e["detail"] for e in closeout.list_events("ge-2026-14")] == ["B"]


def test_a_tender_with_no_events_reads_back_empty():
    assert closeout.list_events("never-touched") == []


def test_an_empty_set_id_is_refused():
    with pytest.raises(ValueError):
        closeout.log_event("", "note", "x")
