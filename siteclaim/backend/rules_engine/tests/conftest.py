"""Pytest fixtures for the Rules Engine tests."""

from datetime import date

import pytest

from rules_engine.tests._helpers import TODAY, make_compliant_facts
from schemas.models import ExtractedFacts


@pytest.fixture
def today() -> date:
    """The fixed 'today' the compliant fixture is anchored to."""
    return TODAY


@pytest.fixture
def compliant_facts() -> ExtractedFacts:
    """A fresh, fully-compliant ExtractedFacts for each test to mutate."""
    return make_compliant_facts()
