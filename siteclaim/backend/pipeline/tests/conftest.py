"""Pipeline test fixtures — everything runs in DEMO_MODE (offline, zero network)."""

from datetime import date
from pathlib import Path

import pytest

from schemas.models import SourceMaterial

_CASES = Path(__file__).resolve().parent.parent.parent / "fixtures" / "cases"


@pytest.fixture(autouse=True)
def _force_demo_mode(monkeypatch):
    """Every pipeline test runs offline against canned fixtures."""
    monkeypatch.setenv("DEMO_MODE", "true")


@pytest.fixture
def load_case():
    """Return a loader for a fixture case's SourceMaterial by id."""

    def _load(case_id: str) -> SourceMaterial:
        return SourceMaterial.model_validate_json(
            (_CASES / case_id / "source.json").read_text(encoding="utf-8")
        )

    return _load


@pytest.fixture
def today() -> date:
    return date(2026, 3, 2)
