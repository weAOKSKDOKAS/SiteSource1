"""Load the acceptable-terms criteria library from ``siteclaim/docs/client_boq/review_criteria.md``.

This is the pluggable input to REVIEW stage 03: a contractor edits rows in the markdown file
without any code change, and this loader turns them into structured :class:`CriteriaLibrary`
objects. Deterministic, no network, no model — a pure markdown-table parse.

Two tables are read:

* the six category tables (``## 1. Time & Progress`` … ``## 6. Other Key Terms``), each a row
  per criterion — the acceptable position, why it matters, and the red flag; and
* the ``## Deterministic threshold checks`` table — the numeric subset the rule layer pre-flags.

The empty ``OK-01`` extension row (``| OK-01 | (to be defined) | | | |``) is TOLERATED: it is loaded
as a placeholder (``is_placeholder=True``) rather than skipped, honouring the "no referenced
criterion is silently dropped" rule, and kept out of the populated ``criteria`` list.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from client_boq.models import Criterion, CriteriaLibrary, ThresholdRule

# siteclaim/backend/client_boq/criteria_loader.py -> parents[2] == siteclaim/
_CRITERIA_PATH = Path(__file__).resolve().parents[2] / "docs" / "client_boq" / "review_criteria.md"

# "## 1. Time & Progress" -> the prefix each ID under it carries.
_CATEGORY_PREFIX = {
    "Time & Progress": "TP",
    "Payment & Security": "PS",
    "Scope, Quality & Design": "SQD",
    "Liability & Risk Allocation": "LR",
    "Site & General Admin": "SGA",
    "Other Key Terms": "OK",
}


def criteria_path() -> Path:
    """The resolved path to the criteria markdown — single source of truth for callers/tests."""
    return _CRITERIA_PATH


def _split_row(line: str) -> Optional[list[str]]:
    """Split a markdown table row ``| a | b | ... |`` into trimmed cells, or None if not a row."""
    s = line.strip()
    if not s.startswith("|"):
        return None
    # Drop the leading/trailing pipe, then split. Separator rows (|---|---|) are filtered by caller.
    cells = [c.strip() for c in s.strip("|").split("|")]
    return cells


def _is_separator(cells: list[str]) -> bool:
    return all(set(c) <= {"-", ":", " "} and c for c in cells)


def load_criteria(path: Optional[Path] = None) -> CriteriaLibrary:
    """Parse the criteria markdown into a :class:`CriteriaLibrary`.

    ``criteria`` holds the populated acceptable-terms rows; ``placeholders`` holds empty extension
    rows (OK-01); ``threshold_rules`` holds the numeric pre-flag subset. Raises ``FileNotFoundError``
    when the markdown is missing (a misconfigured docs path fails loudly, never silently empty).
    """
    md_path = path or _CRITERIA_PATH
    if not md_path.is_file():
        raise FileNotFoundError(
            f"client_boq criteria not found at {md_path}. Expected siteclaim/docs/client_boq/review_criteria.md."
        )
    text = md_path.read_text(encoding="utf-8")

    criteria: list[Criterion] = []
    placeholders: list[Criterion] = []
    threshold_rules: list[ThresholdRule] = []

    current_category: Optional[str] = None
    current_prefix: Optional[str] = None
    in_threshold = False

    for raw in text.splitlines():
        line = raw.rstrip()
        if line.startswith("## "):
            heading = line[3:].strip()
            in_threshold = heading.lower().startswith("deterministic threshold")
            # A numbered category heading like "1. Time & Progress" -> strip the leading "N. ".
            name = heading.split(". ", 1)[1] if heading[:2].strip().rstrip(".").isdigit() else heading
            current_category = name if name in _CATEGORY_PREFIX else None
            current_prefix = _CATEGORY_PREFIX.get(name)
            continue

        cells = _split_row(line)
        if cells is None or _is_separator(cells):
            continue

        first = cells[0]
        if in_threshold:
            # | ID | Rule (flag when true) | Field the AI must extract | ; skip the header row.
            if first == "ID" or not _looks_like_id(first):
                continue
            if len(cells) >= 3:
                threshold_rules.append(ThresholdRule(id=first, rule=cells[1], extract_field=cells[2]))
            continue

        if current_category is None or current_prefix is None:
            continue
        if first == "ID" or not _looks_like_id(first):  # header row / prose
            continue
        # A category row: | ID | Clause Area | Acceptable Position | Why It Matters | Red Flag |
        clause_area = cells[1] if len(cells) > 1 else ""
        acceptable = cells[2] if len(cells) > 2 else ""
        why = cells[3] if len(cells) > 3 else ""
        red_flag = cells[4] if len(cells) > 4 else ""
        is_placeholder = not acceptable.strip()
        crit = Criterion(
            id=first, category_id=current_prefix, category=current_category,
            clause_area=clause_area, acceptable_position=acceptable, why_it_matters=why,
            red_flag=red_flag, is_placeholder=is_placeholder,
        )
        (placeholders if is_placeholder else criteria).append(crit)

    return CriteriaLibrary(criteria=criteria, placeholders=placeholders, threshold_rules=threshold_rules)


def _looks_like_id(cell: str) -> bool:
    """True for a criterion/threshold ID cell like ``TP-04`` (prefix-number), else False."""
    parts = cell.split("-")
    return len(parts) == 2 and parts[0].isalpha() and parts[1].isdigit()
