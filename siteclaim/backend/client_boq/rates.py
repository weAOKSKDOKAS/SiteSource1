"""Load the estimate's rate source from ``client_boq/data/rates.csv`` (a hand-editable CSV).

This is the ESTIMATE cost build-up's rate source (stage 03). Per the locked v1 decisions the
rates are a hand-editable CSV with a manual-override intent, NOT a DB-backed corpus — and this
module is deliberately the SEAM where that swap will happen later: ``load_rates`` returns
:class:`RateRow` objects, and a future company-DB source only has to return the same list from a
different reader. Nothing downstream reads the CSV directly.

Independent of the procurement ``pipeline/estimate/`` estimator by design (locked Q2): no import,
no shared table, no shared schema. Deterministic, offline — a pure CSV read.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Optional

from client_boq.models import RateRow

_RATES_PATH = Path(__file__).resolve().parent / "data" / "rates.csv"

# The categories the estimate recognises; a row outside these is still loaded (never dropped) so a
# typo is visible rather than silently missing.
KNOWN_CATEGORIES = {"labour", "plant", "material", "subcontract", "productivity"}


def rates_path() -> Path:
    """The resolved path to the rates CSV — single source of truth for callers/tests."""
    return _RATES_PATH


def load_rates(path: Optional[Path] = None) -> list[RateRow]:
    """Parse the rates CSV into :class:`RateRow` objects.

    Raises ``FileNotFoundError`` when the CSV is missing (a misconfigured path fails loudly). A row
    with a non-numeric ``rate`` raises ``ValueError`` naming the ``rate_id`` — a bad rate must never
    silently become 0. This is the seam a future DB-backed source replaces.
    """
    csv_path = path or _RATES_PATH
    if not csv_path.is_file():
        raise FileNotFoundError(
            f"client_boq rates not found at {csv_path}. Expected client_boq/data/rates.csv."
        )
    rows: list[RateRow] = []
    with csv_path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for i, raw in enumerate(reader, start=2):  # start=2: header is line 1
            rate_id = (raw.get("rate_id") or "").strip()
            if not rate_id:
                continue  # blank line
            try:
                rate = float((raw.get("rate") or "0").strip() or 0)
            except ValueError as exc:
                raise ValueError(f"rates.csv line {i}: non-numeric rate for {rate_id!r}") from exc
            rows.append(RateRow(
                rate_id=rate_id,
                category=(raw.get("category") or "").strip(),
                code=(raw.get("code") or "").strip(),
                description=(raw.get("description") or "").strip(),
                unit=(raw.get("unit") or "").strip(),
                rate=rate,
                currency=(raw.get("currency") or "").strip(),
                source=(raw.get("source") or "").strip(),
                notes=(raw.get("notes") or "").strip(),
            ))
    return rows
