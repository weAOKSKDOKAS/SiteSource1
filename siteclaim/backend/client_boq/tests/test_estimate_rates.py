"""rates.py edge cases: unknown resource, duplicate rows, and category coverage."""

from __future__ import annotations

from client_boq.models import RateRow
from client_boq.rates import KNOWN_CATEGORIES, duplicate_rate_ids, load_rates, rate_index


def test_rate_index_unknown_and_duplicate_first_wins() -> None:
    rows = [
        RateRow(rate_id="X", category="labour", code="X", rate=100.0),
        RateRow(rate_id="X", category="labour", code="X-dup", rate=200.0),  # duplicate id
        RateRow(rate_id="Y", category="plant", code="Y", rate=50.0),
    ]
    idx = rate_index(rows)
    assert idx["X"].rate == 100.0            # first-wins: the duplicate never changes the resolved rate
    assert idx.get("Z") is None              # unknown resource → miss (handled as missing_rate downstream)
    assert duplicate_rate_ids(rows) == {"X"}


def test_seed_rates_cover_every_category() -> None:
    rows = load_rates()
    assert len(rows) >= 15                    # enough for a meaningful demo estimate
    assert {r.category for r in rows} == KNOWN_CATEGORIES
    assert len(duplicate_rate_ids(rows)) == 0  # the seed file itself has no duplicate ids
