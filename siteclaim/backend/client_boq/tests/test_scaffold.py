"""Scaffold tests for the client_boq module.

These prove the structure is sound — the package imports, the router mounts, and the two real
loaders parse their real source files — WITHOUT exercising any workflow logic (the stages raise
NotImplementedError by design at this phase). Offline, no network, no DB build required.
"""

from __future__ import annotations

import importlib

import pytest


# ---------------------------------------------------------------------------
# Package imports cleanly (every stage module + the loaders + models)
# ---------------------------------------------------------------------------
_MODULES = [
    "client_boq",
    "client_boq.models",
    "client_boq.criteria_loader",
    "client_boq.rates",
    "client_boq.rules",
    "client_boq.store",
    "client_boq.jobs",
    "client_boq.router",
    "client_boq.review.run",
    "client_boq.review.s01_ingest",
    "client_boq.review.s02_context_summary",
    "client_boq.review.s03_criteria_match",
    "client_boq.review.s04_scope_align",
    "client_boq.review.s05_program_check",
    "client_boq.review.s06_cashflow",
    "client_boq.review.s07_register",
    "client_boq.review.s08_citation_verify",
    "client_boq.estimate.s01_scope_review",
    "client_boq.estimate.s02_schedule",
    "client_boq.estimate.s03_cost_buildup",
    "client_boq.estimate.s04_indirects",
    "client_boq.estimate.s05_validate",
    "client_boq.estimate.s06_offer",
]


@pytest.mark.parametrize("name", _MODULES)
def test_module_imports(name: str) -> None:
    assert importlib.import_module(name) is not None


# ---------------------------------------------------------------------------
# Router mounts under /client-boq on the app
# ---------------------------------------------------------------------------
def test_router_mounts_on_app() -> None:
    from api import app

    # This FastAPI includes routers lazily (app.routes holds an _IncludedRouter until the app
    # builds), so assert against the built OpenAPI schema — version-independent and the real
    # source of truth for what is routable.
    paths = set(app.openapi()["paths"])
    # The gate endpoints must be present — they are the module's contract with the app.
    assert "/client-boq/review/approve" in paths
    assert "/client-boq/estimate/run" in paths
    assert any(p.startswith("/client-boq/") for p in paths)


# ---------------------------------------------------------------------------
# Criteria loader parses the REAL review_criteria.md
# ---------------------------------------------------------------------------
def test_criteria_loader_parses_real_file() -> None:
    from client_boq.criteria_loader import criteria_path, load_criteria

    assert criteria_path().is_file(), f"criteria markdown missing at {criteria_path()}"
    lib = load_criteria()

    # 28 populated criteria across the 5 populated categories (TP 6, PS 6, SQD 6, LR 6, SGA 4).
    assert len(lib.criteria) == 28, [c.id for c in lib.criteria]
    assert lib.category_ids() == {"TP", "PS", "SQD", "LR", "SGA"}
    # The 8-row deterministic threshold table.
    assert len(lib.threshold_rules) == 8, [t.id for t in lib.threshold_rules]
    assert {t.id for t in lib.threshold_rules} == {
        "TP-03", "TP-04", "PS-01", "PS-04", "PS-05", "LR-01", "LR-05", "SQD-05",
    }
    # The empty OK-01 extension row is TOLERATED — loaded as a placeholder, never crashing the parse
    # and never counted among the populated criteria.
    assert any(p.id == "OK-01" and p.is_placeholder for p in lib.placeholders)
    assert all(not c.is_placeholder for c in lib.criteria)
    # Every threshold rule references a real populated criterion.
    ids = {c.id for c in lib.criteria}
    assert all(t.id in ids for t in lib.threshold_rules)


# ---------------------------------------------------------------------------
# Rates loader parses the package CSV
# ---------------------------------------------------------------------------
def test_rates_loader_parses_csv() -> None:
    from client_boq.rates import KNOWN_CATEGORIES, load_rates, rates_path

    assert rates_path().is_file(), f"rates csv missing at {rates_path()}"
    rows = load_rates()
    assert len(rows) >= 3
    # Every seeded category is represented and rates parse as numbers.
    cats = {r.category for r in rows}
    assert cats <= KNOWN_CATEGORIES, cats
    assert KNOWN_CATEGORIES <= cats, f"missing categories: {KNOWN_CATEGORIES - cats}"
    assert all(isinstance(r.rate, float) for r in rows)
    # The quoted, comma-bearing description survived CSV parsing intact.
    sub = next(r for r in rows if r.rate_id == "SUB-REBAR")
    assert "," in sub.description and sub.rate == 14500.0


# All REVIEW (s01–s08) and ESTIMATE (s01 scope, s02–s05 spine, s06 letter) stages are implemented and
# covered by their own tests — no stubs remain in the client_boq workflow.
