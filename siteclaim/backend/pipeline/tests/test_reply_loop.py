"""The reply loop — correlation ref (primary) and the AI fallback (secondary), offline.

Ref generation, registry record/resolve, and accumulate-and-relevel are pure JSON work;
the fallback is exercised with a fake client and the DEMO fixture. The full live loop
(inbox -> poller -> processing -> Excel) is verified by the manual smoke note in
stage_04_level/CONTEXT.md, not by these offline tests.
"""

import sys

from pipeline import reply_loop
from pipeline.stage_03_dispatch.dispatch import build_dispatch
from pipeline.workspace import Workspace
from schemas.models import BidLineItem, BidReply, Candidate, FirmProfile, ShortlistSet


def _reply(firm_id, rate):
    return BidReply(firm_id=firm_id, trade="electrical", line_items=[
        BidLineItem(item_ref="E-01", description="LV board", unit="no", qty=1, rate=rate, amount=rate),
    ])


class FakeMatchClient:
    def __init__(self, verdict):
        self.verdict = verdict

    def complete_json(self, *, target_model, **_):
        return target_model(**self.verdict)


def test_make_ref_is_stable_and_safe():
    ref = reply_loop.make_ref("Kwun Tong Tower", "F-EL-02", "electrical")
    assert ref == reply_loop.make_ref("Kwun Tong Tower", "F-EL-02", "electrical")  # stable
    assert ref == "kwun-tong-tower.F-EL-02.electrical"
    assert "]" not in ref  # safe inside an email subject
    assert reply_loop.subject_with_ref("RFQ — Electrical", ref) == f"RFQ — Electrical [SiteSource Ref: {ref}]"


def test_record_and_resolve_ref_roundtrip(tmp_path):
    ws = Workspace(root=tmp_path)
    ref = reply_loop.make_ref("t", "F-EL-02", "electrical")
    reply_loop.record_dispatch(ws, ref, "t", "F-EL-02", "electrical")
    assert reply_loop.resolve_ref(ws, ref) == {"tender_id": "t", "firm_id": "F-EL-02", "trade": "electrical"}
    assert reply_loop.resolve_ref(ws, "unknown.ref.x") is None
    assert reply_loop.resolve_ref(ws, "") is None


def test_accumulate_dedups_by_firm_so_relevel_never_double_counts(tmp_path):
    ws = Workspace(root=tmp_path)
    reply_loop.accumulate_reply(ws, "t", _reply("F-EL-02", 100))
    reply_loop.accumulate_reply(ws, "t", _reply("F-EL-03", 150))
    everything = reply_loop.accumulate_reply(ws, "t", _reply("F-EL-02", 200))  # F-EL-02 resends
    assert {r.firm_id for r in everything} == {"F-EL-02", "F-EL-03"}
    resent = next(r for r in everything if r.firm_id == "F-EL-02")
    assert resent.line_items[0].rate == 200  # the resend replaced the earlier reply


def test_replies_are_per_tender(tmp_path):
    ws = Workspace(root=tmp_path)
    reply_loop.accumulate_reply(ws, "tender-a", _reply("F-EL-02", 100))
    reply_loop.accumulate_reply(ws, "tender-b", _reply("F-EL-03", 100))
    assert {r.firm_id for r in reply_loop.tender_replies(ws, "tender-a")} == {"F-EL-02"}
    assert {r.firm_id for r in reply_loop.tender_replies(ws, "tender-b")} == {"F-EL-03"}


def test_fallback_matches_only_when_confident_and_known(tmp_path):
    ws = Workspace(root=tmp_path)
    ref = reply_loop.make_ref("t", "F-EL-02", "electrical")
    reply_loop.record_dispatch(ws, ref, "t", "F-EL-02", "electrical")

    confident = reply_loop.fallback_match([], ws, client=FakeMatchClient({"matched": True, "ref": ref, "confidence": 0.9}))
    assert confident["firm_id"] == "F-EL-02"
    # low confidence -> None (never guess)
    assert reply_loop.fallback_match([], ws, client=FakeMatchClient({"matched": True, "ref": ref, "confidence": 0.2})) is None
    # a ref that was never dispatched -> None
    assert reply_loop.fallback_match([], ws, client=FakeMatchClient({"matched": True, "ref": "t.NOPE.electrical", "confidence": 0.9})) is None
    # explicit no-match -> None
    assert reply_loop.fallback_match([], ws, client=FakeMatchClient({"matched": False, "ref": "", "confidence": 0.0})) is None


def test_fallback_never_calls_the_model_with_an_empty_registry(tmp_path):
    ws = Workspace(root=tmp_path)

    class Boom:
        def complete_json(self, **_):
            raise AssertionError("must not call the model when there is nothing to match")

    assert reply_loop.fallback_match([], ws, client=Boom()) is None


def test_dispatch_appends_ref_and_records_the_mapping(tmp_path):
    ws = Workspace(root=tmp_path)
    cand = Candidate(
        firm=FirmProfile(firm_id="F-EL-02", name="Vantage E&M Engineering Ltd", registered_grade="", value_band=""),
        trade="electrical", match_score=0.5,
    )
    shortlist = ShortlistSet(per_trade={"electrical": [cand]})
    ds = build_dispatch(
        shortlist, {"electrical": ["F-EL-02"]}, demo_fixture="cases/clean/dispatch.json",
        project_name="Kwun Tong Tower", tender_id="Kwun Tong Tower", workspace=ws,
    )
    ref = reply_loop.make_ref("Kwun Tong Tower", "F-EL-02", "electrical")
    assert f"[SiteSource Ref: {ref}]" in ds.bundles[0].email_subject
    assert reply_loop.resolve_ref(ws, ref) == {"tender_id": "Kwun Tong Tower", "firm_id": "F-EL-02", "trade": "electrical"}


def test_dispatch_without_a_workspace_still_tags_the_subject_but_records_nothing(tmp_path):
    cand = Candidate(
        firm=FirmProfile(firm_id="F-EL-02", name="Vantage", registered_grade="", value_band=""),
        trade="electrical", match_score=0.5,
    )
    ds = build_dispatch(
        ShortlistSet(per_trade={"electrical": [cand]}), {"electrical": ["F-EL-02"]},
        demo_fixture="cases/clean/dispatch.json", project_name="P",
    )
    assert "[SiteSource Ref:" in ds.bundles[0].email_subject  # subject tagged
    assert not reply_loop._registry_path(Workspace(root=tmp_path)).exists()  # nothing recorded


def test_reply_loop_is_offline_with_every_sdk_blocked(monkeypatch, tmp_path):
    monkeypatch.setenv("DEMO_MODE", "true")
    for mod in ("anthropic", "openai", "torch", "sentence_transformers", "fitz"):
        monkeypatch.setitem(sys.modules, mod, None)
    ws = Workspace(root=tmp_path)
    ref = reply_loop.make_ref("t", "F-EL-02", "electrical")
    reply_loop.record_dispatch(ws, ref, "t", "F-EL-02", "electrical")
    assert reply_loop.resolve_ref(ws, ref)["firm_id"] == "F-EL-02"
    # the fallback short-circuits to the DEMO fixture (whose ref is recorded here) — no socket
    reply_loop.record_dispatch(ws, "demo.F-EL-03.electrical", "t", "F-EL-03", "electrical")
    matched = reply_loop.fallback_match([], ws, demo_fixture="cases/inbound/fallback_match.json")
    assert matched and matched["firm_id"] == "F-EL-03"
