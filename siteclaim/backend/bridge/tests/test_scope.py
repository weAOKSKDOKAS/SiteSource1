"""Phase 4 — the confirmed bill becomes the scope split, through the EXISTING ingest_tender.

Offline throughout: a stub client stands in for Layer 2 (``ingest_tender`` uses whatever client it
is handed, so no fixture and no network are involved), and the parts are real one-page PDFs written
by pymupdf so the per-part read, the doc index and the provenance guard all run for real.
"""

import pytest
from fastapi.testclient import TestClient

from bridge import parts as parts_mod
from bridge import scope as scope_mod
from schemas.models import DocType, ScopePackages, SorItem, TradeWorkPackage


@pytest.fixture
def client():
    import api

    return TestClient(api.app)


@pytest.fixture
def make_pdf(tmp_path):
    """Write a small real PDF and return its path — parts are read from their own file."""
    def _make(name: str, pages: list[str]) -> str:
        import fitz

        doc = fitz.open()
        for body in pages:
            page = doc.new_page()
            y = 80
            for line in body.splitlines():
                page.insert_text((60, y), line, fontsize=11)
                y += 16
        path = tmp_path / name
        doc.save(str(path))
        doc.close()
        return str(path)

    return _make


class RecordingClient:
    """Captures every prompt Layer 2 would have seen, and returns a scripted split."""

    def __init__(self, scope: ScopePackages | None = None):
        self.prompts: list[str] = []
        self._scope = scope if scope is not None else ScopePackages(packages=[])

    def complete_json(self, *, system, user, target_model, **_kw):
        self.prompts.append(user)
        return self._scope

    @property
    def seen(self) -> str:
        return "\n".join(self.prompts)


def _piling_scope() -> ScopePackages:
    return ScopePackages(project_name="GE/2026/14", packages=[
        TradeWorkPackage(trade="piling", scope_summary="Bored piling", sor_items=[
            SorItem(item_ref="G1", description="Bored piling 600mm", unit="m", qty=100.0, section="G"),
            SorItem(item_ref="G2", description="Bored piling 800mm", unit="m", qty=50.0, section="G"),
        ]),
    ])


BILL_PAGE = "SECTION G: PILING\nG1 Bored piling 600mm m 100\nG2 Bored piling 800mm m 50"
SPEC_PAGE = "PARTICULAR SPECIFICATION\nWorkmanship for bored piling shall comply with clause 7.34."


@pytest.fixture
def piling_set(make_set, part_spec, make_pdf):
    """A three-part set: a pricing bill, a specification, and a conditions part — with cards."""
    from client_boq.models import PartContext

    bill_pdf = make_pdf("bill.pdf", [BILL_PAGE])
    spec_pdf = make_pdf("spec.pdf", [SPEC_PAGE])
    cond_pdf = make_pdf("cond.pdf", ["CONDITIONS OF TENDER\nTenders close 1 March."])
    make_set("ge-2026-14", "Contract No. GE/2026/14", [
        part_spec(1, "CT", "Conditions of Tender", "tender-instructions"),
        part_spec(2, "SR", "Schedule of Rates", "pricing"),
        part_spec(3, "PS", "Particular Specification", "specifications"),
    ], pdf_paths={"01-ct": cond_pdf, "02-sr": bill_pdf, "03-ps": spec_pdf},
        contexts={
            "01-ct": PartContext(part_id="01-ct", title="Conditions of Tender",
                                 category="tender-instructions", readable=True,
                                 summary="How to bid: closing date and submission rules.",
                                 key_points=["Tenders close 1 March"]),
            "03-ps": PartContext(part_id="03-ps", title="Particular Specification",
                                 category="specifications", readable=True,
                                 summary="Workmanship standards for piling.",
                                 key_points=["Bored piling to clause 7.34"]),
        })
    return "ge-2026-14"


# -- the gate ----------------------------------------------------------------------------------
def test_without_a_confirmation_it_raises_rather_than_guessing(piling_set):
    # The bill is the Phase-3 human gate. Guessing it here — even from an obvious single pricing
    # part — would quietly defeat that gate.
    # RE-ANCHORED with the plain-language pass; the gate and its refusal are unchanged in force.
    with pytest.raises(ValueError, match="No document has been confirmed as the priced bill"):
        scope_mod.scope_from_set(piling_set, client=RecordingClient())


def test_an_unknown_set_raises_lookup_not_an_empty_split():
    with pytest.raises(LookupError, match="No parts found"):
        scope_mod.scope_from_set("never-ingested", client=RecordingClient())


# -- doc_text: only the confirmed bill ----------------------------------------------------------
def test_only_the_confirmed_bill_text_reaches_the_extractor(piling_set):
    parts_mod.confirm_bill_parts(piling_set, ["02-sr"])
    client = RecordingClient(_piling_scope())

    scope_mod.scope_from_set(piling_set, client=client)

    assert "SECTION G: PILING" in client.seen                 # the bill's own text was extracted
    assert "=== Schedule of Rates ===" in client.seen         # api.py's label convention
    # The specification's RAW text must never enter the extraction stream — that is exactly how a
    # non-priceable document's item-like rows become phantom items.
    assert "Workmanship for bored piling shall comply" not in client.seen


def test_both_confirmed_pricing_parts_contribute_and_two_is_not_an_error(
    make_set, part_spec, make_pdf
):
    # A bill of quantities AND a daywork schedule: both priceable, both confirmed, both extracted.
    bq = make_pdf("bq.pdf", ["SECTION G: PILING\nG1 Bored piling m 100"])
    dw = make_pdf("dw.pdf", ["SECTION D: DAYWORKS\nD1 Ganger hour 40"])
    make_set("ge-2026-14", "GE/2026/14", [
        part_spec(1, "BQ", "Bills of Quantities", "pricing"),
        part_spec(2, "DW", "Daywork Schedule", "pricing"),
    ], pdf_paths={"01-bq": bq, "02-dw": dw})
    parts_mod.confirm_bill_parts("ge-2026-14", ["01-bq", "02-dw"])
    client = RecordingClient(_piling_scope())

    scope_mod.scope_from_set("ge-2026-14", client=client)     # no exception: two bills is a choice

    assert "=== Bills of Quantities ===" in client.seen
    assert "=== Daywork Schedule ===" in client.seen


def test_a_confirmed_bill_with_no_readable_text_is_refused_loudly(make_set, part_spec):
    # "No items" and "we could not read it" must never look the same.
    make_set("ge-2026-14", "GE/2026/14",
             [part_spec(1, "SR", "Schedule of Rates", "pricing", scanned=True)],
             pdf_paths={"01-sr": ""})
    parts_mod.confirm_bill_parts("ge-2026-14", ["01-sr"])
    notes: list[str] = []

    with pytest.raises(ValueError, match="produced no readable text"):
        scope_mod.scope_from_set("ge-2026-14", client=RecordingClient(), on_error=notes.append)

    assert any("no cut pdf on disk" in n for n in notes)      # said which failure it was


# -- context_text: from the cards, not the raw text ---------------------------------------------
def test_context_comes_from_the_interpreted_cards_not_raw_part_text(piling_set):
    parts_mod.confirm_bill_parts(piling_set, ["02-sr"])
    client = RecordingClient(_piling_scope())

    scope_mod.scope_from_set(piling_set, client=client)

    assert "Workmanship standards for piling." in client.seen      # the card's summary
    assert "Bored piling to clause 7.34" in client.seen            # the card's key point
    assert "How to bid: closing date and submission rules." in client.seen
    # ...and the card, not the page. Raw text would meet a 6000-char hard truncation and silently
    # discard the later parts entirely.
    assert "Workmanship for bored piling shall comply" not in client.seen


def test_an_unreadable_context_part_is_skipped_and_reported(make_set, part_spec, make_pdf):
    from client_boq.models import PartContext

    bill = make_pdf("bill.pdf", [BILL_PAGE])
    make_set("ge-2026-14", "GE/2026/14", [
        part_spec(1, "SR", "Schedule of Rates", "pricing"),
        part_spec(2, "DR", "Drawings", "drawings"),
    ], pdf_paths={"01-sr": bill, "02-dr": make_pdf("dr.pdf", ["drawing sheet"])},
        contexts={"02-dr": PartContext(part_id="02-dr", title="Drawings", category="drawings",
                                       readable=False, summary="")})
    parts_mod.confirm_bill_parts("ge-2026-14", ["01-sr"])
    notes: list[str] = []
    client = RecordingClient(_piling_scope())

    scope_mod.scope_from_set("ge-2026-14", client=client, on_error=notes.append)

    assert any("marked unreadable" in n and "02-dr" in n for n in notes)   # said so, not silent
    assert "=== Drawings (drawings) ===" not in client.seen                # no empty card passed


def test_a_readable_part_with_no_card_still_names_itself(make_set, part_spec, make_pdf):
    # Interpretation may not have run. The title/category still informs the trade split, and the
    # absence of a card is reported rather than looking like an empty document.
    bill = make_pdf("bill.pdf", [BILL_PAGE])
    make_set("ge-2026-14", "GE/2026/14", [
        part_spec(1, "SR", "Schedule of Rates", "pricing"),
        part_spec(2, "SI", "Site Information", "site-information"),
    ], pdf_paths={"01-sr": bill, "02-si": make_pdf("si.pdf", ["ground investigation report"])})
    parts_mod.confirm_bill_parts("ge-2026-14", ["01-sr"])
    notes: list[str] = []
    client = RecordingClient(_piling_scope())

    scope_mod.scope_from_set("ge-2026-14", client=client, on_error=notes.append)

    assert "=== Site Information (site-information) ===" in client.seen
    assert any("no interpreted card" in n for n in notes)


def test_oversized_context_warns_about_the_truncation_it_will_meet():
    from client_boq.models import PartContext, PartSpec

    big = [(
        PartSpec(n=i, abbr=f"P{i}", title=f"Part {i}", category="scope"),
        "",
        PartContext(part_id=f"{i:02d}-p{i}", title=f"Part {i}", readable=True, summary="x" * 900),
    ) for i in range(1, 12)]
    notes: list[str] = []

    scope_mod.context_text_from_cards(big, notes.append)

    assert any("will be truncated" in n and "chars of later parts" in n for n in notes)


# -- DocType mapping ----------------------------------------------------------------------------
def test_the_doctype_mapping_prices_only_the_confirmed_parts():
    assert scope_mod.doc_type_for("pricing", is_bill=True) is DocType.SCHEDULE_OF_RATES
    # An unconfirmed pricing part is context — the human left it out, so it yields no items.
    assert scope_mod.doc_type_for("pricing", is_bill=False) is DocType.GENERAL
    assert scope_mod.doc_type_for("specifications", is_bill=False) is DocType.PARTICULAR_SPECIFICATION
    assert scope_mod.doc_type_for("drawings", is_bill=False) is DocType.GENERAL
    # PartSpec.category is an unvalidated str; an unknown value is a document nobody classified,
    # never a crash.
    assert scope_mod.doc_type_for("something-new", is_bill=False) is DocType.GENERAL
    assert scope_mod.doc_type_for("", is_bill=False) is DocType.GENERAL


# -- the provenance backstop (promoted from api.py) ---------------------------------------------
def test_items_outside_the_bills_own_sections_are_quarantined_not_routed(piling_set):
    parts_mod.confirm_bill_parts(piling_set, ["02-sr"])
    # The model returns a phantom item in section Z — a section the bill never declares.
    scope = _piling_scope()
    scope.packages.append(TradeWorkPackage(
        trade="landscaping", scope_summary="Phantom", sor_items=[
            SorItem(item_ref="Z9", description="Tree planting", unit="nr", qty=5.0, section="Z"),
        ],
    ))
    notes: list[str] = []

    split, unrecognised = scope_mod.scope_from_set(
        piling_set, client=RecordingClient(scope), on_error=notes.append
    )

    assert [u.item_ref for u in unrecognised] == ["Z9"]
    # Asserted on items, not trade labels: Layer 1 normalises trades against the taxonomy
    # (piling -> foundation_substructure), which is its job and not this module's contract.
    kept = {i.item_ref for p in split.packages for i in p.sor_items}
    assert kept == {"G1", "G2"}                                     # the phantom was never routed
    assert all(p.sor_items for p in split.packages)                 # no empty package survived
    assert any("quarantined, not routed" in n for n in notes)       # surfaced


def test_with_no_declared_sections_the_guard_is_skipped_not_blocking(make_set, part_spec, make_pdf):
    # A bill with no "SECTION X:" headers gives nothing to check against. Skip the guard rather
    # than quarantine everything — blocking a legitimate split would be worse than not checking.
    bill = make_pdf("bill.pdf", ["G1 Bored piling 600mm m 100"])   # rows, no section header
    make_set("ge-2026-14", "GE/2026/14", [part_spec(1, "SR", "Schedule of Rates", "pricing")],
             pdf_paths={"01-sr": bill})
    parts_mod.confirm_bill_parts("ge-2026-14", ["01-sr"])
    notes: list[str] = []

    split, unrecognised = scope_mod.scope_from_set(
        "ge-2026-14", client=RecordingClient(_piling_scope()), on_error=notes.append
    )

    assert unrecognised == []
    kept = {i.item_ref for p in split.packages for i in p.sor_items}
    assert kept == {"G1", "G2"}                                     # nothing dropped
    assert any("provenance guard was skipped" in n for n in notes)  # and said so


# -- persistence + endpoints --------------------------------------------------------------------
def test_the_split_round_trips_through_storage(piling_set):
    parts_mod.confirm_bill_parts(piling_set, ["02-sr"])
    split, _ = scope_mod.scope_from_set(piling_set, client=RecordingClient(_piling_scope()))

    scope_mod.save_scope(piling_set, split)
    back = scope_mod.load_scope(piling_set)

    assert back is not None
    assert [p.trade for p in back.packages] == [p.trade for p in split.packages]
    assert [i.item_ref for i in back.packages[0].sor_items] == ["G1", "G2"]


def test_load_scope_is_none_before_the_split_has_run(piling_set):
    assert scope_mod.load_scope(piling_set) is None


def test_the_scope_endpoints_run_persist_and_read_back(client, piling_set, monkeypatch):
    parts_mod.confirm_bill_parts(piling_set, ["02-sr"])
    # The endpoint builds its own client, which in DEMO would look for a baked fixture. Stub the
    # Layer-2 call itself so the wiring is exercised offline without inventing a bridge fixture —
    # a fixture here would risk papering over exactly the degradation paths above (trap 9).
    monkeypatch.setattr(scope_mod, "ingest_tender", lambda *a, **k: _piling_scope())

    posted = client.post(f"/bridge/{piling_set}/scope")
    assert posted.status_code == 200
    body = posted.json()
    assert [p["trade"] for p in body["scope"]["packages"]] == ["piling"]
    assert body["unrecognised_items"] == [] and isinstance(body["notes"], list)

    got = client.get(f"/bridge/{piling_set}/scope")
    assert got.status_code == 200
    assert [p["trade"] for p in got.json()["scope"]["packages"]] == ["piling"]


def test_the_scope_endpoint_409s_without_a_confirmed_bill(client, piling_set):
    resp = client.post(f"/bridge/{piling_set}/scope")
    assert resp.status_code == 409
    # RE-ANCHORED IN THE OPEN: pinned "bq-part" — an endpoint fragment. The refusal still names
    # how to clear itself, now in the user's terms: the tab where the bill is chosen.
    assert "Route tab" in resp.json()["detail"]                    # names how to clear it


def test_the_scope_endpoints_404_for_an_unknown_set(client):
    assert client.post("/bridge/never-ingested/scope").status_code == 404
    assert client.get("/bridge/never-ingested/scope").status_code == 404


@pytest.fixture
def sectionless_set(make_set, part_spec, make_pdf):
    """A set whose bill declares NO section headers — the shape a real uploaded binder takes in
    DEMO, and the provenance guard's own documented skip case ("with no headers to check against,
    skip the guard rather than block a legitimate split")."""
    bill_pdf = make_pdf("bill.pdf", ["PRICED SCHEDULE\nDrilling and testing works, priced monthly."])
    make_set("demo-walk", "Demo Walk Tender", [
        part_spec(1, "SR", "Priced Schedule", "pricing"),
    ], pdf_paths={"01-sr": bill_pdf})
    return "demo-walk"


def test_the_demo_branch_reaches_its_fixture_without_a_stub(client, sectionless_set):
    """THE WALKTHROUGH BUG. The stubbed test above proves the wiring; it also HID that the DEMO
    branch passed no `demo_fixture`, so the first person to press "Run the split" in DEMO got a
    server crash dressed as "Failed to fetch" — `complete_json` refuses a bare call in DEMO by
    design. This walks the same path the button does, stub-free: the deterministic reading
    (parts, confirmed bill, doc text, the index) runs for real, and only the Layer-2 call is
    answered by the baked fixture."""
    parts_mod.confirm_bill_parts(sectionless_set, ["01-sr"])

    posted = client.post(f"/bridge/{sectionless_set}/scope")
    assert posted.status_code == 200, posted.text
    trades = [p["trade"] for p in posted.json()["scope"]["packages"]]
    assert trades == ["ground_investigation", "field_testing", "field_installations"], (
        "the fixture's three taxonomy-valid packages, none quarantined — this bill declares no "
        "sections, so the guard honestly stands down")

    read_back = client.get(f"/bridge/{sectionless_set}/scope")
    assert [p["trade"] for p in read_back.json()["scope"]["packages"]] == trades


def test_the_demo_fixture_is_still_subject_to_the_provenance_guard(client, piling_set):
    """Trap 9, both halves. The piling bill DECLARES `SECTION G`, so the guard is armed — and the
    fixture's sections (2–6) are not the document's, so every fixture item must be quarantined
    with its reason rather than routed. A fixture may stand in for the model; it may never
    outrank the measurement."""
    parts_mod.confirm_bill_parts(piling_set, ["02-sr"])

    posted = client.post(f"/bridge/{piling_set}/scope")
    assert posted.status_code == 200, posted.text
    body = posted.json()
    assert body["scope"]["packages"] == [], "nothing document-grounded survived, and none should"
    reasons = {u["reason"] for u in body["unrecognised_items"] if u["item_ref"] == "2.4"}
    assert any("not a Schedule-of-Rates section" in r for r in reasons)


def test_the_demo_fixture_does_not_paper_over_the_bill_gate(client, piling_set):
    """The gate half: with the fixture wired, an unconfirmed bill must STILL refuse. A fixture
    that answered before the gate would quietly defeat the Phase-3 human decision."""
    resp = client.post(f"/bridge/{piling_set}/scope")
    assert resp.status_code == 409
