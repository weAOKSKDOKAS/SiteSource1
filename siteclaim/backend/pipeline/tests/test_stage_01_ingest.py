"""Stage 01 ingest — DEMO_MODE splits the tender and Layer 1 validates the trades.

DEMO_MODE is forced on by the autouse fixture in ``pipeline/tests/conftest.py``, so
this runs fully offline against the baked fixture.
"""

import pipeline.stage_01_ingest.ingest as ingest_mod
from pipeline.stage_01_ingest.ingest import _chunk_text, _merge_scopes, ingest_tender
from rules_engine.taxonomy import CANONICAL_TRADES
from schemas.models import (
    DocType,
    ScopePackages,
    SorItem,
    TenderDocument,
    TenderPackage,
    TradeWorkPackage,
)

_FIXTURE = "cases/clean/scope_packages.json"


def _tender() -> TenderPackage:
    return TenderPackage(
        project_name="Kwun Tong Commercial Tower — Category-A Office Fit-out",
        description="Cat-A office fit-out across 12 floors.",
        documents=[
            TenderDocument(doc_type=DocType.METHOD_OF_MEASUREMENT, filename="method_of_measurement.pdf"),
            TenderDocument(doc_type=DocType.PARTICULAR_SPECIFICATION, filename="particular_specification.pdf"),
            TenderDocument(doc_type=DocType.TENDER_ADDENDUM, filename="tender_addendum.pdf"),
            TenderDocument(doc_type=DocType.SCHEDULE_OF_RATES, filename="schedule_of_rates.pdf"),
        ],
    )


def test_ingest_returns_scope_packages():
    scope = ingest_tender(_tender(), demo_fixture=_FIXTURE)
    assert isinstance(scope, ScopePackages)
    assert scope.project_name.startswith("Kwun Tong")


def test_ingest_splits_into_at_least_four_trades_including_electrical():
    scope = ingest_tender(_tender(), demo_fixture=_FIXTURE)
    trades = [pkg.trade for pkg in scope.packages]
    assert len(trades) >= 4
    assert "electrical" in trades


def test_every_trade_is_canonical_after_validation():
    # The fixture uses real-world labels ("Mechanical & Plumbing", "Fire Services");
    # Layer 1 normalises them all to canonical taxonomy keys.
    scope = ingest_tender(_tender(), demo_fixture=_FIXTURE)
    assert all(pkg.trade in CANONICAL_TRADES for pkg in scope.packages)
    assert {"electrical", "mechanical_plumbing", "fire_services", "joinery_fitting_out"} <= {
        pkg.trade for pkg in scope.packages
    }


def test_scope_items_and_sources_survive_the_split():
    scope = ingest_tender(_tender(), demo_fixture=_FIXTURE)
    electrical = next(pkg for pkg in scope.packages if pkg.trade == "electrical")
    assert electrical.sor_items and electrical.sor_items[0].qty > 0
    assert electrical.source_refs  # each package cites which tender document it came from


def test_scope_packages_accepts_package_name_and_missing_project_name():
    # The Sonnet-5 drift: a package uses `package_name` instead of `trade`, and the
    # top-level `project_name` is omitted. Both are now accepted (no ValidationError).
    payload = (
        '{"packages": [{"package_name": "Electrical", "scope_summary": "LV distribution", '
        '"sor_items": [], "source_refs": []}]}'
    )
    scope = ScopePackages.model_validate_json(payload)
    assert scope.project_name == ""                 # defaulted, not required
    assert scope.packages[0].trade == "Electrical"  # package_name mapped to trade (pre-normalisation)


def test_ingest_tolerates_the_drift_and_fills_project_name():
    # End to end: a model payload with `package_name` and no `project_name` no longer
    # 500s — project_name is injected from the tender and the trade is normalised.
    scope = ingest_tender(_tender(), demo_fixture="cases/messy/scope_drift.json")
    assert isinstance(scope, ScopePackages)
    assert scope.project_name.startswith("Kwun Tong")           # injected from the tender
    assert scope.packages[0].trade == "ground_investigation"    # package_name -> trade -> canonical


def test_system_prompt_names_fields_and_lists_canonical_trades():
    # The prompt states the exact field names and embeds the taxonomy trade list, so a
    # newer model does not guess (`package_name`) and the list stays in sync.
    from pipeline.stage_01_ingest.ingest import _system_prompt

    prompt = _system_prompt()
    assert '"trade"' in prompt and '"scope_summary"' in prompt and "package_name" in prompt
    assert "ground_investigation" in prompt and "electrical" in prompt  # from rules_engine.taxonomy
    assert "sor_items" in prompt and "EVERY" in prompt  # row-by-row extraction, not a summary


def test_ingest_populates_sor_items_row_by_row_from_a_text_sor():
    # Text-first ingest yields row-level sor_items (the fix for the empty-sor_items bug),
    # not a section-level summary. Driven offline by a fixture shaped like the real SR-01.
    scope = ingest_tender(_tender(), demo_fixture="cases/messy/scope_sor_rows.json")
    pkg = scope.packages[0]
    assert pkg.trade == "ground_investigation"
    assert len(pkg.sor_items) >= 3  # one object per priced row, not one summary item
    first = pkg.sor_items[0]
    assert first.item_ref == "M1" and first.unit == "%" and first.qty == 50.0
    assert "Landfill" in first.description


def test_ingest_threads_extracted_document_text_into_the_prompt():
    # The extracted text layer reaches the model (text-first), not page images.
    captured = {}

    class FakeClient:
        def complete_json(self, *, system, user, target_model, **_):
            captured["user"] = user
            return target_model(project_name="P", packages=[])

    ingest_tender(_tender(), client=FakeClient(), doc_text="M1 | rotary drilling in rock | m | 300.00")
    assert "rotary drilling in rock" in captured["user"]
    assert "Extracted tender document text" in captured["user"]


# -- chunked, per-section extraction ---------------------------------------
def test_chunk_text_splits_on_sections_and_never_mid_line():
    text = "\n".join([
        "SECTION A", "A-01 rotary drilling m 300", "A-02 undisturbed sampling no 45",
        "SECTION B", "B-01 trial pit no 12",
        "SECTION C", "C-01 laboratory testing no 200",
    ])
    chunks = _chunk_text(text, max_chars=45)  # small -> forces several chunks
    assert len(chunks) >= 2
    # every original line survives intact in some chunk (no item row cut in half)
    for line in text.splitlines():
        assert any(line in chunk for chunk in chunks), line


def test_chunk_text_small_text_is_one_chunk_and_empty_is_none():
    assert len(_chunk_text("SECTION A\nA-01 drilling", max_chars=12000)) == 1
    assert _chunk_text("") == []


def test_merge_scopes_concats_items_and_dedupes_by_item_ref():
    def scope(items):
        return ScopePackages(project_name="", packages=[TradeWorkPackage(
            trade="ground_investigation", scope_summary="GI", source_refs=["SR-01"],
            sor_items=[SorItem(item_ref=r, description=d, unit="no", qty=None) for (r, d) in items],
        )])

    merged = _merge_scopes(
        [scope([("A-01", "drilling"), ("A-02", "sampling")]),
         scope([("B-01", "trial pit")]),
         scope([("C-01", "lab"), ("A-01", "dup")])],  # A-01 repeats -> deduped
        TenderPackage(project_name="GE/2026/14"),
    )
    assert len(merged.packages) == 1  # one trade, all sections merged
    assert [i.item_ref for i in merged.packages[0].sor_items] == ["A-01", "A-02", "B-01", "C-01"]
    assert merged.project_name == "GE/2026/14"  # derived from the tender (chunks had none)


def test_ingest_chunks_and_merges_items_across_sections_without_loss_or_dup(monkeypatch):
    monkeypatch.setattr(ingest_mod, "MAX_CHUNK_CHARS", 45)  # force one call per section

    def pkg(items):
        return {"project_name": "GI", "packages": [{
            "trade": "ground_investigation", "scope_summary": "GI", "source_refs": ["SR-01"],
            "sor_items": [{"item_ref": r, "description": d, "unit": "no"} for (r, d) in items],
        }]}

    class SectionFakeClient:
        def complete_json(self, *, user, target_model, **_):
            for marker, payload in self.by_marker.items():
                if marker in user:
                    return target_model(**payload)
            return target_model(project_name="", packages=[])

    client = SectionFakeClient()
    client.by_marker = {
        "SECTION A": pkg([("A-01", "drilling")]),
        "SECTION B": pkg([("B-01", "trial pit")]),
        "SECTION C": pkg([("C-01", "lab"), ("A-01", "dup")]),  # A-01 duplicate across chunks
    }
    doc_text = "SECTION A\nA-01 drilling\nSECTION B\nB-01 trial pit\nSECTION C\nC-01 lab\nA-01 dup"
    scope = ingest_tender(_tender(), client=client, doc_text=doc_text)
    assert len(scope.packages) == 1
    assert sorted(i.item_ref for i in scope.packages[0].sor_items) == ["A-01", "B-01", "C-01"]


# -- item_ref exactness (mangled "BA BB BC…" refs seen live on SR-01) -------
def test_system_prompt_demands_exact_printed_item_codes():
    # The live SR-01 extraction yielded refs like BA/BB/BC — the section letter fused
    # with a neighbouring column. The prompt now pins item_ref to the exact printed
    # code and forbids fabricating one for a code-less row.
    from pipeline.stage_01_ingest.ingest import _system_prompt

    prompt = _system_prompt()
    assert "EXACT printed item code" in prompt
    assert "section" in prompt and "fused" in prompt      # never section-letter concatenation
    assert "SKIP that row" in prompt                       # code-less row -> skipped, not invented
    assert 'A1a(a)' in prompt                              # the real SR-01 code shape is shown


def test_sr01_shaped_refs_come_through_the_chunked_path_verbatim(monkeypatch):
    # Rows shaped like the real SR-01 (code | description | PS-ref | unit | rate): a
    # faithful per-chunk extraction must land every printed code verbatim — parens,
    # mixed case, digits — through chunking, merging, and taxonomy normalisation,
    # with no post-hoc mangling. (Exactness at the source is the prompt's job, above.)
    monkeypatch.setattr(ingest_mod, "MAX_CHUNK_CHARS", 120)  # force one call per section

    class FaithfulClient:
        """Copies each data row's printed code from the chunk it was given — the
        behaviour the exactness instruction demands of the model."""

        def complete_json(self, *, user, target_model, **_):
            refs = [
                line.split(" | ")[0].strip()
                for line in user.splitlines()
                if " | " in line
            ]
            return target_model(project_name="", packages=[{
                "trade": "ground_investigation", "scope_summary": "GI", "source_refs": ["SR-01"],
                "sor_items": [{"item_ref": r, "description": "row", "unit": "m"} for r in refs],
            }] if refs else [])

    doc_text = "\n".join([
        "SECTION A",
        "A1a(a) | Rotary drilling in soil | PS 1.13.1A | m | ",
        "A1a(b) | Rotary drilling in rock | PS 1.13.1B | m | ",
        "M2 | Percentage adjustment, Landfill areas | PS 2.1 | % | ",
        "SECTION B",
        "H14 | Standard penetration test | PS 3.4 | no | ",
    ])
    scope = ingest_tender(_tender(), client=FaithfulClient(), doc_text=doc_text)

    assert len(scope.packages) == 1
    refs = [i.item_ref for i in scope.packages[0].sor_items]
    assert refs == ["A1a(a)", "A1a(b)", "M2", "H14"]  # verbatim — no BA/BB/BC style fusion


# -- SoR with no quantities (qty optional) ---------------------------------
def test_sor_item_qty_is_optional():
    item = SorItem(item_ref="M1", description="Percentage adjustment", unit="%")  # no qty column
    assert item.qty is None


def test_ingest_parses_a_sor_with_no_quantities():
    scope = ingest_tender(_tender(), demo_fixture="cases/messy/scope_no_qty.json")
    items = scope.packages[0].sor_items
    assert items and all(item.qty is None for item in items)  # a SoR with no qty column parses
