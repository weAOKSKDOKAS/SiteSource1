"""Stage 01 document classification for per-trade routing (offline).

These tests drive the classifier with a scripted fake client (per-document variety)
and with the DEMO_MODE fixture short-circuit — never a socket. They assert the tags
land on ``TenderDocument.trades`` and that the unchanged ``route_documents`` then sends
the right whole files. The LIVE LLM path is verified separately by the manual smoke
procedure (see stage_01_ingest/CONTEXT.md), not by these offline tests.
"""

import sys

from pipeline.stage_01_ingest.classify import DocClassification, classify_documents
from pipeline.stage_03_dispatch.attachments import build_attachments, route_documents
from pipeline.workspace import Workspace
from schemas.models import (
    AttachmentKind,
    DocType,
    ScopePackages,
    SorItem,
    TenderDocument,
    TenderPackage,
    TradeWorkPackage,
)


class FakeClient:
    """A stand-in LLM client: returns a scripted DocClassification per filename."""

    def __init__(self, by_filename: dict):
        self.by_filename = dict(by_filename)

    def complete_json(self, *, user, target_model, **_):
        for name, result in self.by_filename.items():
            if f"Filename: {name}" in user:
                return target_model(**result)
        return target_model(general=True, confidence=1.0)  # default: general


def _tender(names_types):
    return TenderPackage(project_name="GE/2026/14", documents=[
        TenderDocument(doc_type=dt, filename=fn) for fn, dt in names_types
    ])


def test_classify_tags_documents_and_route_documents_sends_the_right_files():
    tender = _tender([
        ("clarification.pdf", DocType.TENDER_ADDENDUM),
        ("ps_electrical.pdf", DocType.PARTICULAR_SPECIFICATION),
        ("sr01_combined.pdf", DocType.SCHEDULE_OF_RATES),
    ])
    client = FakeClient({
        "clarification.pdf": {"general": True, "confidence": 1.0},
        "ps_electrical.pdf": {"general": False, "trades": ["electrical"], "confidence": 0.95},
        "sr01_combined.pdf": {"general": True, "confidence": 0.9},  # combined SoR -> general
    })
    tagged = classify_documents(tender, client=client)
    by_name = {d.filename: d for d in tagged.documents}
    assert by_name["clarification.pdf"].trades == []
    assert by_name["ps_electrical.pdf"].trades == ["electrical"]
    assert by_name["sr01_combined.pdf"].trades == []

    # Whole-file routing: electrical gets both general docs + the electrical spec …
    general_e, specific_e = route_documents(tagged, "electrical")
    assert {d.filename for d in general_e} == {"clarification.pdf", "sr01_combined.pdf"}
    assert {d.filename for d in specific_e} == {"ps_electrical.pdf"}
    # … and fire services gets the general docs but NOT the electrical spec.
    general_f, specific_f = route_documents(tagged, "fire_services")
    assert {d.filename for d in general_f} == {"clarification.pdf", "sr01_combined.pdf"}
    assert specific_f == []


def test_low_confidence_and_unmapped_labels_fall_back_to_general():
    tender = _tender([
        ("lowconf.pdf", DocType.PARTICULAR_SPECIFICATION),
        ("unmapped.pdf", DocType.PARTICULAR_SPECIFICATION),
    ])
    client = FakeClient({
        "lowconf.pdf": {"general": False, "trades": ["electrical"], "confidence": 0.2},  # low confidence
        "unmapped.pdf": {"general": False, "trades": ["basket weaving"], "confidence": 0.95},  # maps to nothing
    })
    tagged = classify_documents(tender, client=client)
    assert all(d.trades == [] for d in tagged.documents)  # both general — never withheld


def test_trade_labels_are_normalised_to_canonical_keys():
    tender = _tender([("ps.pdf", DocType.PARTICULAR_SPECIFICATION)])
    client = FakeClient({"ps.pdf": {"general": False, "trades": ["Fire Services Installation"], "confidence": 0.9}})
    tagged = classify_documents(tender, client=client)
    assert tagged.documents[0].trades == ["fire_services"]  # normalised via rules_engine.taxonomy


def test_geotechnical_spec_now_classifies_to_ground_investigation():
    # v2: a Geotechnical Works spec (like GE/2026/14 PS-S07) resolves to the real GI
    # trade instead of falling to general.
    tender = _tender([("ps_s07_geotechnical.pdf", DocType.PARTICULAR_SPECIFICATION)])
    client = FakeClient({"ps_s07_geotechnical.pdf": {"general": False, "trades": ["Geotechnical Works"], "confidence": 0.9}})
    tagged = classify_documents(tender, client=client)
    assert tagged.documents[0].trades == ["ground_investigation"]
    assert tagged.documents[0].filename in {d.filename for d in route_documents(tagged, "ground_investigation")[1]}


def test_a_document_specific_to_two_trades_routes_to_both():
    tender = _tender([("mep.pdf", DocType.PARTICULAR_SPECIFICATION)])
    client = FakeClient({"mep.pdf": {"general": False, "trades": ["electrical", "mechanical & plumbing"], "confidence": 0.9}})
    tagged = classify_documents(tender, client=client)
    assert set(tagged.documents[0].trades) == {"electrical", "mechanical_plumbing"}
    assert tagged.documents[0].filename in {d.filename for d in route_documents(tagged, "electrical")[1]}
    assert tagged.documents[0].filename in {d.filename for d in route_documents(tagged, "mechanical_plumbing")[1]}


def test_combined_sor_still_generates_a_per_trade_sor_sheet(tmp_path):
    # A combined SoR is classified general (whole file to everyone); the priceable items
    # are still delivered by the generated per-trade SoR sheet.
    tender = _tender([("sr01.pdf", DocType.SCHEDULE_OF_RATES)])
    tagged = classify_documents(tender, client=FakeClient({"sr01.pdf": {"general": True, "confidence": 0.9}}))
    scope = ScopePackages(project_name="GE/2026/14", packages=[
        TradeWorkPackage(trade="electrical", scope_summary="LV works",
                         sor_items=[SorItem(item_ref="E1", description="LV board", unit="no", qty=2)]),
    ])
    attachments = build_attachments("electrical", scope, tagged, project_name="GE/2026/14",
                                    tender_id="GE/2026/14", workspace=Workspace(root=tmp_path))
    kinds = {a.kind for a in attachments}
    assert AttachmentKind.GENERAL in kinds and AttachmentKind.SOR_SHEET in kinds
    sor = next(a for a in attachments if a.kind is AttachmentKind.SOR_SHEET)
    assert sor.source_path  # the per-trade sheet is generated even for a combined SoR


def test_demo_fixture_short_circuits_through_complete_json(monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "true")
    tender = _tender([("x.pdf", DocType.PARTICULAR_SPECIFICATION)])
    # real LLMClient (client=None): DEMO_MODE short-circuits to the fixture, no socket
    tagged = classify_documents(tender, demo_fixture="cases/clean/doc_classification.json")
    assert tagged.documents[0].trades == ["electrical"]


def test_classify_is_fully_offline_with_every_sdk_blocked(monkeypatch):
    # The new path imports no provider SDK and opens no socket in DEMO_MODE.
    monkeypatch.setenv("DEMO_MODE", "true")
    for mod in ("anthropic", "openai", "torch", "sentence_transformers", "fitz"):
        monkeypatch.setitem(sys.modules, mod, None)
    tender = _tender([("x.pdf", DocType.PARTICULAR_SPECIFICATION)])
    tagged = classify_documents(tender, demo_fixture="cases/clean/doc_classification.json")
    assert tagged.documents[0].trades == ["electrical"]  # ran with all SDKs blocked


def test_classification_result_defaults_are_safe():
    # An empty/degenerate model result resolves to general (never a stray trade).
    tender = _tender([("x.pdf", DocType.PARTICULAR_SPECIFICATION)])
    tagged = classify_documents(tender, client=FakeClient({"x.pdf": {}}))
    assert tagged.documents[0].trades == []


# -- doc_type: the extraction-gating axis, orthogonal to routing -----------
def test_classify_sets_doc_type_independently_of_general_routing():
    tender = _tender([
        ("sr01_combined.pdf", DocType.SCHEDULE_OF_RATES),
        ("mm01.pdf", DocType.SCHEDULE_OF_RATES),          # uploaded default; classifier corrects it
        ("clarification.pdf", DocType.SCHEDULE_OF_RATES),
    ])
    client = FakeClient({
        # A combined SoR is general for ROUTING yet schedule_of_rates for KIND (extract).
        "sr01_combined.pdf": {"general": True, "doc_type": "schedule_of_rates", "confidence": 0.9},
        "mm01.pdf": {"general": True, "doc_type": "method_of_measurement", "confidence": 0.9},
        "clarification.pdf": {"general": True, "doc_type": "clarification", "confidence": 0.9},
    })
    by_name = {d.filename: d for d in classify_documents(tender, client=client).documents}

    assert by_name["sr01_combined.pdf"].doc_type is DocType.SCHEDULE_OF_RATES  # extract items
    assert by_name["mm01.pdf"].doc_type is DocType.METHOD_OF_MEASUREMENT       # NOT extracted
    assert by_name["clarification.pdf"].doc_type is DocType.TENDER_ADDENDUM    # clarification -> addendum
    assert all(d.trades == [] for d in by_name.values())                      # all general (routing)


def test_low_confidence_doc_type_keeps_the_uploaded_kind():
    tender = _tender([("mystery.pdf", DocType.SCHEDULE_OF_RATES)])
    client = FakeClient({"mystery.pdf": {"general": True, "doc_type": "method_of_measurement", "confidence": 0.2}})
    # Low confidence -> the classifier's kind is not trusted; the uploaded doc_type stays.
    assert classify_documents(tender, client=client).documents[0].doc_type is DocType.SCHEDULE_OF_RATES


def test_classify_prompt_requests_doc_type_and_general_for_cross_trade_docs():
    from pipeline.stage_01_ingest.classify import _system_prompt

    prompt = _system_prompt()
    assert "doc_type" in prompt and "schedule_of_rates" in prompt and "method_of_measurement" in prompt
    assert "INDEPENDENT" in prompt                       # doc_type orthogonal to general
    assert "never leaning to the tender's dominant trade" in prompt  # cross-trade -> general


# -- text-first classification: text when available, vision only for scanned docs ------
class RecordingClient:
    """Records images and user prompt per call; returns a fixed general classification."""

    def __init__(self):
        self.calls = []

    def complete_json(self, *, user, target_model, images=None, **_):
        self.calls.append({"user": user, "images": images})
        return target_model(general=True, doc_type="general", confidence=0.9)


def test_a_document_with_text_classifies_from_text_and_renders_no_image():
    tender = _tender([("ps_electrical.pdf", DocType.PARTICULAR_SPECIFICATION)])
    client = RecordingClient()
    classify_documents(
        tender, per_doc_images=[["would-be-render"]],  # available, but must NOT be used
        per_doc_text=["PARTICULAR SPECIFICATION — ELECTRICAL INSTALLATION, Section 16"],
        client=client,
    )
    (call,) = client.calls
    assert call["images"] is None                         # text-first: no vision render
    assert "PARTICULAR SPECIFICATION" in call["user"]     # the text reached the prompt


def test_a_scanned_document_with_no_text_falls_back_to_vision():
    tender = _tender([("scan.pdf", DocType.SCHEDULE_OF_RATES)])
    client = RecordingClient()
    classify_documents(
        tender, per_doc_images=[["scanned-page-png"]],
        per_doc_text=[""],  # no usable text layer
        client=client,
    )
    (call,) = client.calls
    assert call["images"] == ["scanned-page-png"]         # vision fallback for a scanned doc
