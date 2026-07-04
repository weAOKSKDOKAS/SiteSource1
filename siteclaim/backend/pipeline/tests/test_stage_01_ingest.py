"""Stage 01 ingest — DEMO_MODE splits the tender and Layer 1 validates the trades.

DEMO_MODE is forced on by the autouse fixture in ``pipeline/tests/conftest.py``, so
this runs fully offline against the baked fixture.
"""

from pipeline.stage_01_ingest.ingest import ingest_tender
from rules_engine.taxonomy import CANONICAL_TRADES
from schemas.models import DocType, ScopePackages, TenderDocument, TenderPackage

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
