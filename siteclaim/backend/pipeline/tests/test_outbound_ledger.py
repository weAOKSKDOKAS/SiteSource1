"""FIX 3 — the poller must not ingest our own outbound RFQ as a reply.

Every dispatched RFQ is addressed to the operator by ``GMAIL_TEST_RECIPIENT`` during live testing,
so it lands in the very mailbox the poller watches, carrying ``[SiteSource Ref: …]`` and the blank
Schedule of Rates. That is ``DEFAULT_QUERY`` exactly. Unguarded, ``poll_once`` would resolve its
ref, parse the blank sheet as a bid with no rates, and ``accumulate_replies`` would file it —
SUPERSEDING the firm's genuine reply, because ``(firm_id, trade)`` is the supersede identity.

Filtering the query is not available. ``-from:me`` and ``-in:sent`` both drop the genuine reply
too, because in this test loop the operator is both sender and recipient. Identity has to be
explicit, which is what the ledger is.

Confirmed off in production at the time of writing (``polling_enabled: False``, 4 drafts created),
so nothing has been corrupted — this lands before ``GMAIL_POLLING_ENABLED=true`` is ever set.

**Known gap, stated rather than implied away:** a message the operator sends BY HAND from the
Gmail UI is not in the ledger and can still be self-ingested. See the last test.
"""

import pytest
from pipeline import reply_loop, reply_poller
from pipeline.workspace import Workspace


@pytest.fixture
def ws(tmp_path, monkeypatch):
    monkeypatch.setenv("SITESOURCE_WORKDIR", str(tmp_path / "work"))
    return Workspace()


class StubGmail:
    """The two calls `poll_once` makes, and nothing else."""

    def __init__(self, messages):
        self.messages = messages
        self.fetched: list[str] = []


@pytest.fixture
def gmail(monkeypatch):
    """Patch the module `poll_once` imports lazily, so no Google SDK is involved."""
    from pipeline import gmail_client

    state = {"messages": [], "fetched": []}

    def list_replies(query, **_kw):
        return state["messages"]

    def get_attachments(mid, **_kw):
        state["fetched"].append(mid)
        return [("SoR_return.xlsx", b"bytes")]

    monkeypatch.setattr(gmail_client, "list_replies", list_replies)
    monkeypatch.setattr(gmail_client, "get_attachments", get_attachments)
    monkeypatch.setattr(gmail_client, "_log", lambda *a, **k: None)
    return state


def _msg(mid, ref="t.F1.gi"):
    return {"id": mid, "subject": f"Re: RFQ [SiteSource Ref: {ref}]"}


# ---------------------------------------------------------------------------
# The ledger itself
# ---------------------------------------------------------------------------
def test_a_recorded_message_id_reads_back(ws):
    reply_loop.record_outbound(ws, "m-1", ref="t.F1.gi", to="op@x.com")
    assert reply_loop.outbound_message_ids(ws) == {"m-1"}


def test_the_ledger_is_additive(ws):
    reply_loop.record_outbound(ws, "m-1")
    reply_loop.record_outbound(ws, "m-2")
    assert reply_loop.outbound_message_ids(ws) == {"m-1", "m-2"}


def test_an_empty_message_id_is_not_recorded(ws):
    """A draft that came back without a message id must not put "" in the ledger — an empty id
    would match nothing, but it would sit there looking like a record of something."""
    reply_loop.record_outbound(ws, "")
    assert reply_loop.outbound_message_ids(ws) == set()


def test_an_absent_ledger_is_an_empty_set_not_an_error(ws):
    assert reply_loop.outbound_message_ids(ws) == set()


def test_the_ledger_lives_beside_the_ref_registry(ws):
    reply_loop.record_outbound(ws, "m-1")
    assert (ws.root / "outbound_messages.json").is_file()


# ---------------------------------------------------------------------------
# The poll
# ---------------------------------------------------------------------------
def test_our_own_outbound_is_skipped_and_counted_as_own(ws, gmail):
    """The defect in one assertion: the blank RFQ must not reach processing at all."""
    reply_loop.record_outbound(ws, "m-out", ref="t.F1.gi")
    gmail["messages"] = [_msg("m-out"), _msg("m-reply")]
    seen: list[str] = []

    summary = reply_poller.poll_once(
        lambda ref, atts: (seen.append(ref), "matched")[1], workspace=ws)

    assert summary["own"] == 1
    assert summary["processed"] == 1
    assert seen == ["t.F1.gi"]              # ONE call — the reply, never the outbound
    assert gmail["fetched"] == ["m-reply"]  # and its attachment was never even downloaded


def test_own_is_its_own_counter_not_folded_into_skipped(ws, gmail):
    """Skipping an already-processed message and refusing to eat our own RFQ are different events.
    One number would hide the one worth watching: `own` climbing while `processed` stays flat is
    the loop talking to itself."""
    reply_loop.record_outbound(ws, "m-out")
    gmail["messages"] = [_msg("m-out")]
    summary = reply_poller.poll_once(lambda ref, atts: "matched", workspace=ws)
    assert summary["own"] == 1 and summary["skipped"] == 0


def test_an_empty_ledger_behaves_exactly_as_before(ws, gmail):
    gmail["messages"] = [_msg("m-1"), _msg("m-2")]
    summary = reply_poller.poll_once(lambda ref, atts: "matched", workspace=ws)
    assert summary["own"] == 0
    assert summary["processed"] == 2
    assert summary["found"] == 2


def test_an_own_message_is_not_marked_processed(ws, gmail):
    """The ledger is the authority on what is ours. Marking it processed too would put one fact in
    two places where they could disagree — and a pruned ledger would then let it back in silently."""
    reply_loop.record_outbound(ws, "m-out")
    gmail["messages"] = [_msg("m-out")]
    reply_poller.poll_once(lambda ref, atts: "matched", workspace=ws)
    assert "m-out" not in reply_poller.load_processed(ws)


def test_the_own_skip_survives_a_second_poll(ws, gmail):
    """It is skipped every sweep, not once — the message stays in the mailbox for `newer_than:7d`."""
    reply_loop.record_outbound(ws, "m-out")
    gmail["messages"] = [_msg("m-out")]
    first = reply_poller.poll_once(lambda ref, atts: "matched", workspace=ws)
    second = reply_poller.poll_once(lambda ref, atts: "matched", workspace=ws)
    assert first["own"] == second["own"] == 1


# ---------------------------------------------------------------------------
# The gap this does NOT close
# ---------------------------------------------------------------------------
def test_a_hand_sent_message_is_not_covered(ws, gmail):
    """STATED, not worked around. The ledger only knows messages this system created. A message the
    operator composes BY HAND in the Gmail UI — carrying the ref tag and an attachment, because
    that is what makes it match — is not in it and WILL be ingested as a reply.

    This test exists so the limit is a recorded fact rather than an assumption someone makes later.
    Closing it needs a different signal (a header we set, or sender-side identity), which is a
    larger change than this fix and is not made here.
    """
    gmail["messages"] = [_msg("m-hand-sent")]
    summary = reply_poller.poll_once(lambda ref, atts: "matched", workspace=ws)
    assert summary["own"] == 0
    assert summary["processed"] == 1        # ingested — the known, reported gap


# ---------------------------------------------------------------------------
# The message id, not the draft id
# ---------------------------------------------------------------------------
def test_create_draft_ids_returns_the_message_id_not_the_draft_id(monkeypatch):
    """`drafts().create` answers {"id": <draft id>, "message": {"id": <message id>}}. The poller
    lists MESSAGES, so a draft id in the ledger would never match one and the guard would be inert
    while looking exactly like it worked."""
    from pipeline import gmail_client

    class Drafts:
        def create(self, userId, body):
            class R:
                def execute(_self):
                    return {"id": "DRAFT-1", "message": {"id": "MSG-1"}}
            return R()

    class Users:
        def drafts(self):
            return Drafts()

    class Svc:
        def users(self):
            return Users()

    monkeypatch.setattr(gmail_client, "_log", lambda *a, **k: None)
    draft_id, message_id = gmail_client.create_draft_ids(
        "to@x.com", "s", "b", [], service=Svc())
    assert (draft_id, message_id) == ("DRAFT-1", "MSG-1")
    # And the original single-value entry point still answers the DRAFT id, unchanged.
    assert gmail_client.create_draft("to@x.com", "s", "b", [], service=Svc()) == "DRAFT-1"
