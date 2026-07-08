"""Provenance backstop (classification fail-safe, Commit 3): an extracted item must belong to a
section the Schedule of Rates ITSELF declares. Anything that still slips through — an item whose
section is not among the SoR's own section codes — is quarantined and surfaced, never silently
dropped and never formed into a package. Deterministic; offline."""

import pytest

from api import _quarantine_unrecognised_items
from schemas.models import ScopePackages, SectionMeta, SorItem, TradeWorkPackage


def _pkg(trade, items):
    codes = {(s or "").upper() for _r, _d, s in items if s}
    return TradeWorkPackage(
        trade=trade, scope_summary=trade,
        sor_items=[SorItem(item_ref=r, description=d, section=s) for r, d, s in items],
        sections=[SectionMeta(code=c, item_count=sum(1 for _r, _d, s in items if (s or "").upper() == c))
                  for c in sorted(codes)])


def test_a_phantom_package_from_non_sor_sections_is_dropped_entirely():
    scope = ScopePackages(packages=[
        _pkg("ground_investigation", [("H1", "Rotary drilling", "H"), ("G4", "Trial pit", "G")]),
        _pkg("structural", [("S4", "Sprayed concrete", "S"), ("S5", "Mesh", "S")]),  # phantom (no S in SoR)
    ])
    scrubbed, unrecognised = _quarantine_unrecognised_items(scope, {"G", "H", "I", "J"})
    assert [p.trade for p in scrubbed.packages] == ["ground_investigation"]     # phantom package gone
    assert {i.item_ref for i in scrubbed.packages[0].sor_items} == {"H1", "G4"}  # real items kept
    assert {u.item_ref for u in unrecognised} == {"S4", "S5"}                    # phantom items surfaced
    assert all(u.section == "S" for u in unrecognised)


def test_a_stray_item_is_removed_but_its_real_package_and_counts_survive():
    # An MoM payment row ("010 toolbox talks", no section) leaked into a real GI package.
    scope = ScopePackages(packages=[_pkg("ground_investigation", [
        ("H1", "Rotary drilling", "H"), ("H2", "Standpipe", "H"), ("010", "Toolbox talks", "")])])
    scrubbed, unrecognised = _quarantine_unrecognised_items(scope, {"H"})
    kept = scrubbed.packages[0]
    assert {i.item_ref for i in kept.sor_items} == {"H1", "H2"}          # stray removed, real kept
    assert [u.item_ref for u in unrecognised] == ["010"]                 # the P1/010/S-style stray, flagged
    assert unrecognised[0].section == "" and "not a Schedule-of-Rates section" in unrecognised[0].reason
    assert [(m.code, m.item_count) for m in kept.sections] == [("H", 2)]  # section metadata recomputed


def test_nothing_is_quarantined_when_every_section_is_recognised():
    scope = ScopePackages(packages=[_pkg("ground_investigation", [("H1", "x", "H"), ("I3", "y", "I")])])
    scrubbed, unrecognised = _quarantine_unrecognised_items(scope, {"G", "H", "I", "J"})
    assert unrecognised == []
    assert {i.item_ref for i in scrubbed.packages[0].sor_items} == {"H1", "I3"}


def test_the_section_match_is_case_and_whitespace_tolerant():
    scope = ScopePackages(packages=[_pkg("ground_investigation", [("h1", "x", " h ")])])
    scrubbed, unrecognised = _quarantine_unrecognised_items(scope, {"H"})
    assert unrecognised == [] and scrubbed.packages[0].sor_items[0].item_ref == "h1"


# -- end-to-end: the guard runs at ingest only when the SoR declared section headers -----------
fitz = pytest.importorskip("fitz")


def _sor_pdf():
    """A real four-section SoR PDF (G/H/I/J), so build_doc_index indexes sor_section_pages."""
    doc = fitz.open()
    for header, body in [
        ("SECTION G : TRIAL PITS AND HAND AUGER HOLES", "G1 Excavate trial pit by hand to depth"),
        ("SECTION H : ROTARY DRILLING AND SAMPLING", "H1 Boreholes by rotary drilling in soil"),
        ("SECTION I : LABORATORY TESTING", "I1 Triaxial compression test on samples"),
        ("SECTION J : FIELD INSTRUMENTATION", "J1 Vibrating wire piezometer monitoring"),
    ]:
        page = doc.new_page()
        page.insert_text((72, 72), header)
        page.insert_text((72, 110), body)
    return doc.tobytes()


def test_ingest_quarantines_a_non_sor_section_item_and_warns(monkeypatch, tmp_path):
    from pipeline.tests.test_api_live import _ingest_and_wait

    monkeypatch.setenv("DEMO_MODE", "false")
    monkeypatch.setenv("SITESOURCE_WORKDIR", str(tmp_path))
    monkeypatch.setattr("api.extract_document", lambda data, ct: ("G/H/I/J priced rows", []))
    monkeypatch.setattr("api.to_images", lambda data, ct, max_pages=2: [])

    def fake_ingest(tender, images=None, doc_text="", context_text="", progress_cb=None, on_error=None):
        return ScopePackages(project_name="GE/2026/14", packages=[
            _pkg("ground_investigation", [("H1", "Rotary drilling", "H")]),
            _pkg("structural", [("S4", "Sprayed concrete", "S")])])  # phantom, section not in the SoR
    monkeypatch.setattr("api.ingest_tender", fake_ingest)

    body = _ingest_and_wait(files={"files": ("I-GE_2026_14_TSC-SR-01.pdf", _sor_pdf(), "application/pdf")})
    assert body["status"] == "done", body
    result = body["result"]
    assert [p["trade"] for p in result["scope"]["packages"]] == ["ground_investigation"]  # phantom dropped
    assert [u["item_ref"] for u in result["unrecognised_items"]] == ["S4"]                 # surfaced, not routed
    assert any("S4" in w and "quarantined" in w for w in body["warnings"])                 # loud on the summary


def test_ingest_skips_the_guard_when_the_sor_declares_no_sections(monkeypatch, tmp_path):
    # A fully unindexed SoR (no section headers to check against) must NOT block a legitimate ingest:
    # the guard skips, and even an unusual-section item is kept.
    from pipeline.tests.test_api_live import _ingest_and_wait

    monkeypatch.setenv("DEMO_MODE", "false")
    monkeypatch.setenv("SITESOURCE_WORKDIR", str(tmp_path))
    monkeypatch.setattr("api.extract_document", lambda data, ct: ("rows", []))
    monkeypatch.setattr("api.to_images", lambda data, ct, max_pages=2: [])
    monkeypatch.setattr("api.ingest_tender", lambda tender, images=None, doc_text="", context_text="",
                        progress_cb=None, on_error=None: ScopePackages(
                            project_name="GE/2026/14", packages=[_pkg("ground_investigation", [("Z9", "x", "Z")])]))

    # Not a real PDF -> build_doc_index indexes no sor_section_pages -> the guard is skipped.
    body = _ingest_and_wait(files={"files": ("I-GE_2026_14_TSC-SR-01.pdf", b"not a pdf", "application/pdf")})
    assert body["status"] == "done", body
    assert body["result"]["unrecognised_items"] == []
    assert [i["item_ref"] for i in body["result"]["scope"]["packages"][0]["sor_items"]] == ["Z9"]  # kept
