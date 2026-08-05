"""`/tender/{slug}/replies` reports who was ASKED, not only who is still outstanding.

The screen that lists dispatched packages used to rebuild that list from React state written at
dispatch time. That state dies with the browser session, so six replies on disk rendered as "No
dispatched packages yet" whenever the dispatch had happened in another tab or on another day.

`outstanding` could not fix it on its own: it is dispatched-minus-replied, so it drops exactly the
firms whose returns have landed — the ones the screen most needs to show. `dispatched` is the whole
set with a `received` flag per row, built from the correlation registry, which is the persisted
record of every enquiry that went out.

Deterministic and offline: registry files on disk, no model and no mailbox.
"""

import api
import pytest
from fastapi.testclient import TestClient
from pipeline import reply_loop
from pipeline.workspace import Workspace
from schemas.models import BidLineItem, BidReply

client = TestClient(api.app)


def _reply(firm, key, refs_rates):
    return BidReply(firm_id=firm, trade=key,
                    line_items=[BidLineItem(item_ref=r, rate=v) for r, v in refs_rates])


@pytest.fixture
def ws(tmp_path, monkeypatch):
    monkeypatch.setenv("SITESOURCE_WORKDIR", str(tmp_path))
    return Workspace()


def test_a_dispatch_with_no_reply_is_reported_as_dispatched_not_received(ws):
    reply_loop.record_dispatch(ws, "REF-1", "nd-2025-04", "F001", "electrical")

    body = client.get("/tender/nd-2025-04/replies").json()
    assert body["dispatched"] == [
        {"firm_id": "F001", "trade": "electrical", "ref": "REF-1",
         "firm_name": "F001", "received": False},
    ]


def test_a_replied_firm_stays_in_dispatched_and_is_flagged_received(ws):
    """The bug in one assertion: `outstanding` loses this firm, `dispatched` keeps it."""
    reply_loop.record_dispatch(ws, "REF-1", "nd-2025-04", "F001", "electrical")
    reply_loop.accumulate_replies(ws, "nd-2025-04", [_reply("F001", "electrical", [("E1", 10.0)])])

    body = client.get("/tender/nd-2025-04/replies").json()
    assert body["outstanding"] == []                      # dispatched-minus-replied drops it...
    assert body["dispatched"] == [                        # ...and this is why that is not enough
        {"firm_id": "F001", "trade": "electrical", "ref": "REF-1",
         "firm_name": "F001", "received": True},
    ]


def test_landed_and_awaiting_appear_side_by_side(ws):
    """What the screen actually renders: one list, both states, from one response."""
    reply_loop.record_dispatch(ws, "REF-1", "nd-2025-04", "F001", "electrical")
    reply_loop.record_dispatch(ws, "REF-2", "nd-2025-04", "F002", "electrical")
    reply_loop.record_dispatch(ws, "REF-3", "nd-2025-04", "F003", "plumbing")
    reply_loop.accumulate_replies(ws, "nd-2025-04", [_reply("F002", "electrical", [("E1", 10.0)])])

    body = client.get("/tender/nd-2025-04/replies").json()
    assert {(d["firm_id"], d["trade"], d["received"]) for d in body["dispatched"]} == {
        ("F001", "electrical", False),
        ("F002", "electrical", True),
        ("F003", "plumbing", False),
    }
    assert body["reply_count"] == 1


def test_another_tenders_dispatches_are_not_reported(ws):
    reply_loop.record_dispatch(ws, "REF-1", "nd-2025-04", "F001", "electrical")
    reply_loop.record_dispatch(ws, "REF-9", "ge-2026-14", "F009", "electrical")

    body = client.get("/tender/nd-2025-04/replies").json()
    assert [d["firm_id"] for d in body["dispatched"]] == ["F001"]


def test_the_tender_id_is_matched_by_slug_not_by_raw_string(ws):
    # Dispatch records the project NAME; the screen asks by slug. Both resolve to one tender.
    reply_loop.record_dispatch(ws, "REF-1", "Contract No. ND/2025/04", "F001", "electrical")

    body = client.get("/tender/nd-2025-04/replies").json()
    assert [d["ref"] for d in body["dispatched"]] == ["REF-1"]


def test_a_withdrawn_reply_leaves_the_firm_dispatched_and_awaiting_again(ws):
    """Withdrawing a bad upload must put the firm back on the awaiting list, not erase it."""
    reply_loop.record_dispatch(ws, "REF-1", "nd-2025-04", "F001", "electrical")
    reply_loop.accumulate_replies(ws, "nd-2025-04", [_reply("F001", "electrical", [("E1", 10.0)])])
    reply_loop.withdraw_reply(ws, "nd-2025-04", "F001", "electrical")

    body = client.get("/tender/nd-2025-04/replies").json()
    assert [(d["firm_id"], d["received"]) for d in body["dispatched"]] == [("F001", False)]
    assert body["outstanding"] == [{"firm_id": "F001", "trade": "electrical"}]


def test_no_dispatches_is_an_empty_list_not_a_404(ws):
    body = client.get("/tender/never-dispatched/replies").json()
    assert body["dispatched"] == [] and body["outstanding"] == []


def test_a_firm_name_is_resolved_when_the_register_knows_it(ws):
    """The registry stores identity, not display text — the name comes from the firm register."""
    from db import store

    try:
        conn = store.get_connection()
        row = conn.execute(
            "SELECT firm_id, name_en FROM firms WHERE name_en != '' LIMIT 1").fetchone()
        conn.close()
    except Exception:                                     # noqa: BLE001
        pytest.skip("no firm register in this environment")
    if row is None:
        pytest.skip("firm register is empty")

    reply_loop.record_dispatch(ws, "REF-1", "nd-2025-04", row["firm_id"], "electrical")
    body = client.get("/tender/nd-2025-04/replies").json()
    assert body["dispatched"][0]["firm_name"] == row["name_en"]


def test_an_unknown_firm_id_degrades_to_the_id_rather_than_hiding_the_row(ws):
    # A dispatched enquiry the register cannot name is still a dispatched enquiry. Showing the id
    # is honest; dropping the row would tell the operator nobody was asked.
    reply_loop.record_dispatch(ws, "REF-1", "nd-2025-04", "NOT-A-REAL-FIRM", "electrical")

    body = client.get("/tender/nd-2025-04/replies").json()
    assert body["dispatched"][0]["firm_name"] == "NOT-A-REAL-FIRM"
